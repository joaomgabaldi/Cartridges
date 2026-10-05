"""A API do Xbox: o titleId de um jogo, o catálogo de conquistas e o progresso.

Os endpoints são os documentados no GDK (``achievements.xboxlive.com``, contrato
2; o 4 traz também a raridade, ver ``docs/superpowers/prova-xbox``) e o
``titlehub`` que o Playnite usa (``XboxAccountClient.cs``). Uma chamada só traz
o catálogo e o progresso da conta: cada conquista vem com nome, descrição,
ícone, raridade e, se já foi conseguida, quando.

O PFN do pacote vira titleId pelo ``MicrosoftGame.config`` do jogo, quando ele
existe, ou pelo titlehub; o resultado fica em ``xbox-titulos.json``, no cache.

Roda só em thread (varredura e vigia): faz rede e pode esperar o limitador. Todo
dado que vem da rede, do jogo ou do cache é tratado como não confiável: o que
não serve vira log e é descartado, sem derrubar o resto. Nada de token nem
cabeçalho ``Authorization`` vai para o log, e a mensagem de uma exceção do
``requests`` (que pode trazer a URL) também não: só o tipo e o status.
"""

import json
import logging
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Optional
from xml.etree import ElementTree

import requests

from cartridges import shared
from cartridges.conquistas import arquivos, catalogo
from cartridges.conquistas.catalogo import Catalogo, ConquistaInfo
from cartridges.conquistas.contas import Leitura
from cartridges.conquistas.formatos import Desbloqueio
from cartridges.conquistas.saneamento import codifica, limpo, numero_finito, segundos_iso
from cartridges.conquistas.xbox import conta
from cartridges.utils import download
from cartridges.utils.ler_json import ler_json
from cartridges.utils.rate_limiter import RateLimiter

# Aprovado pela prova: as mesmas chaves do contrato 2, mais a raridade.
CONTRATO = "4"
PREFIXO = "XBOX:"
_IDIOMAS = "pt-BR, pt;q=0.9, en-US;q=0.8"
_CONQUISTAS = "https://achievements.xboxlive.com/users/xuid({xuid})/achievements"
_TITULOS = "https://titlehub.xboxlive.com/titles/batch/decoration/detail"
_PAGINAS = 10
_SEM_XBOX_LIVE_VALE = 7 * 24 * 3600
_TAMANHO_DO_CONFIG = 1024 * 1024
_TEMPO = 15
_TITULO_EM_HEX = re.compile(r"[0-9A-Fa-f]{1,8}")


class FalhaDeRede(Exception):
    """A Microsoft não respondeu como devia (rede, 5xx, 429, não-JSON)."""


class XboxLimiter(RateLimiter):
    """Bem abaixo do limite por usuário que o Xbox Live aplica."""

    refill_period_seconds = 60
    refill_period_tokens = 30
    burst_tokens = 10


_limitador: Optional[XboxLimiter] = None
_trava_do_limitador = threading.Lock()
_trava_dos_titulos = threading.Lock()


def _limite() -> XboxLimiter:
    global _limitador  # pylint: disable=global-statement
    with _trava_do_limitador:
        if _limitador is None:
            _limitador = XboxLimiter()
        return _limitador


def chave_do_catalogo(titulo: str) -> str:
    return f"xbox-{titulo}"


def _requisitar(metodo: str, url: str, **kwargs: Any) -> requests.Response:
    """O único ponto de rede. O corpo é lido sob um teto antes de devolver."""
    resposta = requests.request(metodo, url, timeout=_TEMPO, stream=True, **kwargs)
    try:
        corpo = download.read_capped(resposta, download.MAX_RESPONSE_BYTES)
    except BaseException:
        resposta.close()
        raise
    # Mesmo atalho de `download.get_capped`: o cache do corpo do próprio requests.
    resposta._content = corpo  # pylint: disable=protected-access
    return resposta


def _pedir(metodo: str, url: str, contrato: str, aut: tuple[str, str], kwargs: dict) -> requests.Response:
    uhs, xsts = aut
    cabecalhos = {
        "Authorization": f"XBL3.0 x={uhs};{xsts}",
        "x-xbl-contract-version": contrato,
        "Accept-Language": _IDIOMAS,
        "Accept": "application/json",
    }
    try:
        with _limite():
            return _requisitar(metodo, url, headers=cabecalhos, **kwargs)
    except requests.RequestException as erro:
        # Só o tipo: a mensagem do requests pode trazer a URL.
        logging.info("Xbox: pedido falhou (%s)", type(erro).__name__)
        raise FalhaDeRede() from None


def _sem_autorizacao() -> None:
    """`conta.autorizacao` devolveu None: sem conta (ou recusada e já desconectada)
    é None; conta ainda conectada é a renovação que falhou por rede, e quem varre
    precisa saber para parar de esperar o tempo limite de cada jogo."""
    if conta.conectada():
        logging.info("Xbox: a renovação do acesso falhou")
        raise FalhaDeRede()
    return None


def _chamar(metodo: str, url: str, contrato: str, **kwargs: Any) -> Optional[Any]:
    """O JSON da resposta. ``None``: sem conta, conta recusada ou resposta 4xx.

    Levanta ``FalhaDeRede`` para rede, 5xx, 429, resposta que não é JSON e
    renovação do acesso que falhou com a conta ainda conectada.
    """
    aut = conta.autorizacao()
    if aut is None:
        return _sem_autorizacao()
    resposta = _pedir(metodo, url, contrato, aut, kwargs)
    if resposta.status_code == 401:
        aut = conta.autorizacao(forcar=True)
        if aut is None:
            return _sem_autorizacao()
        resposta = _pedir(metodo, url, contrato, aut, kwargs)
        if resposta.status_code == 401:
            logging.info("Xbox: acesso recusado duas vezes; desconectando a conta")
            conta.recusada()
            return None
    status = resposta.status_code
    if status == 429 or status >= 500:
        logging.info("Xbox: a Microsoft respondeu %s", status)
        raise FalhaDeRede()
    if status >= 400:
        logging.info("Xbox: pedido recusado (%s)", status)
        return None
    try:
        return resposta.json()
    except (ValueError, RecursionError):
        logging.info("Xbox: resposta que não é JSON")
        raise FalhaDeRede() from None


def _titulo_valido(valor: Any) -> bool:
    return isinstance(valor, str) and arquivos.appid_valido(valor)


# --- titleId ----------------------------------------------------------------


def _do_config(bases: list[Path]) -> Optional[str]:
    """O titleId do ``MicrosoftGame.config`` do jogo (hex no arquivo, decimal na API)."""
    for base in bases:
        try:
            arquivo = Path(base) / "MicrosoftGame.config"
            if not arquivo.is_file() or arquivo.stat().st_size > _TAMANHO_DO_CONFIG:
                continue
            raiz = ElementTree.parse(arquivo).getroot()
            elemento = next(
                (e for e in raiz.iter() if isinstance(e.tag, str) and e.tag.endswith("TitleId")),
                None,
            )
            texto = (elemento.text or "").strip() if elemento is not None else ""
            if not _TITULO_EM_HEX.fullmatch(texto):
                continue
            valor = int(texto, 16)
        except (OSError, ElementTree.ParseError, ValueError, RecursionError):
            continue
        if valor > 0:
            return str(valor)
    return None


def _arquivo_dos_titulos() -> Path:
    return shared.conquistas_cache_dir / "xbox-titulos.json"


def _ler_titulos() -> dict[str, Any]:
    try:
        dados = ler_json(_arquivo_dos_titulos())
    except FileNotFoundError:
        return {}
    except (OSError, ValueError, RecursionError) as erro:
        logging.info("Cache de títulos do Xbox ilegível (%s)", type(erro).__name__)
        return {}
    return dados if isinstance(dados, dict) else {}


def _guardar_titulo(pfn: str, titulo: Optional[str]) -> None:
    with _trava_dos_titulos:
        dados = {chave: valor for chave, valor in _ler_titulos().items() if isinstance(valor, dict)}
        dados[pfn] = {"titulo": titulo, "em": int(time.time())}
        destino = _arquivo_dos_titulos()
        temporario = destino.with_name(f"{destino.name}.{uuid.uuid4().hex}.tmp")
        try:
            destino.parent.mkdir(parents=True, exist_ok=True)
            temporario.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
            temporario.replace(destino)
        except (OSError, ValueError) as erro:
            logging.warning("Cache de títulos do Xbox não gravado: %s", type(erro).__name__)
        finally:
            try:
                temporario.unlink(missing_ok=True)
            except OSError:
                pass


def titulo_local(pfn: Optional[str], bases: list[Path]) -> Optional[str]:
    """O titleId sem rede: ``MicrosoftGame.config`` e depois o cache.

    ``"123"`` é o titleId; ``""`` é "sabidamente sem Xbox Live" (cache negativo
    de 7 dias); ``None`` é "não se sabe".
    """
    do_config = _do_config(bases)
    if do_config is not None:
        return do_config
    if not isinstance(pfn, str) or not pfn:
        return None
    entrada = _ler_titulos().get(pfn)
    if not isinstance(entrada, dict):
        return None
    titulo = entrada.get("titulo")
    if _titulo_valido(titulo):
        return titulo
    em = entrada.get("em")
    if titulo is None and numero_finito(em) and 0 <= time.time() - em < _SEM_XBOX_LIVE_VALE:
        return ""
    return None


def titulo(pfn: Optional[str], bases: list[Path]) -> Optional[str]:
    """``titulo_local`` e, sem resposta, o titlehub (que grava o cache).

    Levanta ``FalhaDeRede``. ``None`` também quando a conta não está conectada.
    """
    achado = titulo_local(pfn, bases)
    if achado is not None or not isinstance(pfn, str) or not pfn:
        return achado
    corpo = _chamar("POST", _TITULOS, "2", json={"pfns": [pfn], "windowsPhoneProductIds": []})
    if corpo is None:
        return None
    titulos = corpo.get("titles") if isinstance(corpo, dict) else None
    if not isinstance(titulos, list):
        # Não é a resposta do titlehub: nada se sabe, nada vai para o cache.
        logging.info("Xbox: resposta do titlehub fora do formato")
        return None
    # Só vale o item do pacote pedido: o primeiro da lista pode ser de outro.
    pedido = pfn.casefold()
    do_pacote = next(
        (
            item
            for item in titulos
            if isinstance(item, dict)
            and isinstance(item.get("pfn"), str)
            and item["pfn"].casefold() == pedido
        ),
        None,
    )
    achado = do_pacote.get("titleId") if do_pacote is not None else None
    if _titulo_valido(achado):
        _guardar_titulo(pfn, achado)
        return achado
    _guardar_titulo(pfn, None)
    return ""


# --- conquistas -------------------------------------------------------------


def _icone(item: dict) -> str:
    assets = item.get("mediaAssets")
    for asset in assets if isinstance(assets, list) else []:
        if not isinstance(asset, dict) or asset.get("type") != "Icon":
            continue
        url = asset.get("url")
        if isinstance(url, str) and url.startswith("https://") and codifica(url):
            return url
    return ""


def _porcentagem(item: dict) -> Optional[float]:
    if CONTRATO != "4":
        return None
    raridade = item.get("rarity")
    valor = raridade.get("currentPercentage") if isinstance(raridade, dict) else None
    if not numero_finito(valor) or not 0 <= valor <= 100:
        return None
    return float(valor)


def _info(item: Any) -> Optional[tuple[ConquistaInfo, Optional[Desbloqueio]]]:
    if not isinstance(item, dict):
        return None
    id_, nome = item.get("id"), item.get("name")
    # O id vira a chave do histórico: um id que não grava em UTF-8 derruba a conquista.
    if not isinstance(id_, str) or not id_.strip() or not codifica(id_) or not isinstance(nome, str):
        return None
    descricao = item.get("description")
    if not isinstance(descricao, str) or not descricao:
        descricao = item.get("lockedDescription")
    chave = f"{PREFIXO}{id_}"
    info = ConquistaInfo(
        nome=chave,
        titulo=limpo(nome).strip() or id_,
        descricao=limpo(descricao) if isinstance(descricao, str) else "",
        icone=_icone(item),
        icone_cinza="",
        oculta=item.get("isSecret") is True,
        porcentagem=_porcentagem(item),
    )
    desbloqueio = None
    # Só `Achieved`: `unlockedOnly=true` também devolve as `InProgress`.
    if item.get("progressState") == "Achieved":
        progresso = item.get("progression")
        quando = segundos_iso(progresso.get("timeUnlocked")) if isinstance(progresso, dict) else 0
        desbloqueio = Desbloqueio(chave, quando)
    return info, desbloqueio


def _todas(titulo: str, extra: dict[str, str]) -> Optional[list[tuple[ConquistaInfo, Optional[Desbloqueio]]]]:
    xuid = conta.xuid()
    if not _titulo_valido(xuid) or not _titulo_valido(titulo):
        return None
    url = _CONQUISTAS.format(xuid=xuid)
    achadas: list[tuple[ConquistaInfo, Optional[Desbloqueio]]] = []
    continuar: Optional[str] = None
    for _pagina in range(_PAGINAS):
        params: dict[str, Any] = {"titleId": titulo, "maxItems": 1000, **extra}
        if continuar:
            params["continuationToken"] = continuar
        corpo = _chamar("GET", url, CONTRATO, params=params)
        if not isinstance(corpo, dict) or not isinstance(corpo.get("achievements"), list):
            if corpo is not None:
                logging.info("Xbox: resposta de conquistas fora do formato")
            return None
        for item in corpo["achievements"]:
            lida = _info(item)
            if lida is not None:
                achadas.append(lida)
            else:
                logging.info("Xbox: conquista com campo inválido descartada")
        paginacao = corpo.get("pagingInfo")
        continuar = paginacao.get("continuationToken") if isinstance(paginacao, dict) else None
        if not isinstance(continuar, str) or not continuar:
            break
    return achadas


def ler(titulo: str) -> Optional[Leitura]:
    """Catálogo e progresso da conta numa chamada; guarda o catálogo no cache.

    Levanta ``FalhaDeRede``. ``None``: sem conta, desconectou ou resposta inválida.
    """
    achadas = _todas(titulo, {})
    if achadas is None:
        return None
    infos = tuple(info for info, _ in achadas)
    cat = Catalogo(
        infos,
        int(time.time()),
        False,
        "",
        sem_raridade=CONTRATO == "4" and bool(infos) and all(i.porcentagem is None for i in infos),
    )
    try:
        catalogo.guardar(chave_do_catalogo(titulo), cat)
    except (OSError, ValueError) as erro:
        logging.warning("Catálogo de conquistas do Xbox não gravado: %s", type(erro).__name__)
    return Leitura(cat, [d for _, d in achadas if d is not None])


def desbloqueadas(titulo: str) -> Optional[list[Desbloqueio]]:
    """Só o progresso (``unlockedOnly=true``), sem tocar no cache.

    Levanta ``FalhaDeRede``. ``None``: sem conta, desconectou ou resposta inválida.
    """
    achadas = _todas(titulo, {"unlockedOnly": "true"})
    if achadas is None:
        return None
    return [d for _, d in achadas if d is not None]
