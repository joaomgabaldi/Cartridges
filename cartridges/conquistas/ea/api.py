"""A API da EA: biblioteca e conjunto de conquistas (Juno), catálogo e progresso (API antiga).

- A Juno (``service-aggregation-layer.juno.ea.com``, GraphQL) dá o ``psd`` da conta, a
  biblioteca (título → ofertas) e, por oferta, o id do conjunto de conquistas.
- A API antiga (``achievements.gameservices.ea.com``) devolve num pedido só o catálogo e o
  progresso do conjunto, em português. Prova em ``docs/superpowers/prova-ea/``.

Roda só em thread (varredura e vigia): faz rede e pode esperar o limitador. Todo dado que
vem da rede ou do cache é tratado como não confiável. Nada de token, persona, psd, consulta,
corpo ou título vai para o log: só o tipo da exceção e o status.
"""

import json
import logging
import re
import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, Optional

import requests

from cartridges import shared
from cartridges.conquistas import catalogo
from cartridges.conquistas.catalogo import Catalogo, ConquistaInfo
from cartridges.conquistas.contas import Leitura
from cartridges.conquistas.ea import conta
from cartridges.conquistas.ea.jogo import normalizar
from cartridges.conquistas.formatos import Desbloqueio
from cartridges.conquistas.saneamento import codifica, limpo, numero_finito
from cartridges.utils import download
from cartridges.utils.gravar_atomico import gravar_atomico
from cartridges.utils.ler_json import ler_json
from cartridges.utils.rate_limiter import RateLimiter

PREFIXO = "EA:"
JUNO = "https://service-aggregation-layer.juno.ea.com/graphql"
ANTIGA = "https://achievements.gameservices.ea.com/achievements/personas"
_PSD = "query { me { player { psd } } }"
_BIBLIOTECA = (
    'query { me { ownedGameProducts(locale: "pt-BR", entitlementEnabled: true, storefronts: [EA], '
    "platforms: [PC], type: [DIGITAL_FULL_GAME, PACKAGED_FULL_GAME], paging: {limit: 9999}) "
    "{ items { originOfferId product { id name gameSlug } } } } }"
)
# Oferta e psd vão como variáveis, nunca dentro do texto da consulta.
_CONJUNTO = (
    "query ($o: String!, $p: String!) { achievements(offerId: $o, playerPsd: $p, "
    'showHidden: true, locale: "pt-BR") { id } }'
)
_ESCONDIDA = "Conquista Escondida"
_UM_DIA = 24 * 3600
_DESDE_1971 = 365 * 2 * 24 * 3600
_TEMPO = 15
_ID = re.compile(r"[0-9A-Za-z_-]{1,64}")


class FalhaDeRede(Exception):
    """A EA não respondeu como devia (rede, 5xx, 429, não-JSON)."""


class EaLimiter(RateLimiter):
    """Bem abaixo do que o EA app faz."""

    refill_period_seconds = 60
    refill_period_tokens = 30
    burst_tokens = 10


_limitador: Optional[EaLimiter] = None
_trava_do_limitador = threading.Lock()
_trava_dos_arquivos = threading.Lock()
# (token com que foi pedido, psd): esquecido quando o token muda.
_psd: Optional[tuple[str, str]] = None
_trava_do_psd = threading.Lock()
# O último token obtido à força: não se força de novo enquanto ele for o vigente.
_acesso_ja_renovado: Optional[str] = None
_trava_do_acesso = threading.Lock()


def _limite() -> EaLimiter:
    global _limitador  # pylint: disable=global-statement
    with _trava_do_limitador:
        if _limitador is None:
            _limitador = EaLimiter()
        return _limitador


def conjunto_valido(valor: Any) -> bool:
    return isinstance(valor, str) and _ID.fullmatch(valor) is not None


def chave_do_catalogo(conjunto: str) -> str:
    return f"ea-{conjunto}"


def _requisitar(metodo: str, url: str, **kwargs: Any) -> requests.Response:
    """O único ponto de rede. O corpo é lido sob um teto antes de devolver."""
    return download.request_capped(metodo, url, timeout=_TEMPO, **kwargs)


def _pedir(metodo: str, url: str, **kwargs: Any) -> requests.Response:
    try:
        with _limite():
            return _requisitar(metodo, url, **kwargs)
    except requests.RequestException as erro:
        # Só o tipo: a mensagem do requests pode trazer a URL.
        logging.info("EA: pedido falhou (%s)", type(erro).__name__)
        raise FalhaDeRede() from None


def _json(resposta: requests.Response) -> Optional[Any]:
    """O JSON da resposta; ``None`` para 4xx. Levanta ``FalhaDeRede`` para 429, 5xx e não-JSON."""
    status = resposta.status_code
    if status == 429 or status >= 500:
        logging.info("EA: a EA respondeu %s", status)
        raise FalhaDeRede()
    if status >= 400:
        logging.info("EA: pedido recusado (%s)", status)
        return None
    try:
        return resposta.json()
    except (ValueError, RecursionError):
        logging.info("EA: resposta que não é JSON")
        raise FalhaDeRede() from None


def _caminho(dados: Any, *chaves: str) -> Any:
    for chave in chaves:
        if not isinstance(dados, dict):
            return None
        dados = dados.get(chave)
    return dados


def _autorizado(metodo: str, url: str, cabecalhos: Callable[[str], dict], **kwargs: Any) -> Optional[Any]:
    """O JSON de um pedido com o token; 401/403 renova uma vez. A segunda recusa só vai
    para o log (``None``): a conta continua conectada, só a recusa do ``remid`` a desconecta."""
    global _acesso_ja_renovado  # pylint: disable=global-statement
    for forcar in (False, True):
        acesso = conta.autorizacao(forcar=forcar)
        if acesso is None:
            # Sem conta é None; conta ainda conectada é a renovação que falhou por rede.
            if conta.conectada():
                logging.info("EA: a renovação do acesso falhou")
                raise FalhaDeRede()
            return None
        if forcar:
            with _trava_do_acesso:
                _acesso_ja_renovado = acesso
        resposta = _pedir(metodo, url, headers=cabecalhos(acesso), **kwargs)
        if resposta.status_code not in (401, 403):
            return _json(resposta)
        with _trava_do_acesso:
            ja_renovado = not forcar and acesso == _acesso_ja_renovado
        if ja_renovado:
            # No máximo uma renovação forçada por acesso: sem isto, uma recusa persistente
            # faria o vigia gastar um `remid` a cada 15 s.
            logging.info("EA: este acesso já foi renovado à força; sem nova tentativa")
            return None
    logging.info("EA: acesso recusado duas vezes")
    return None


# --- Juno -------------------------------------------------------------------


def _juno(consulta: str, variaveis: Optional[dict[str, str]] = None) -> Optional[dict]:
    """O ``data`` de uma consulta GraphQL; ``None`` = sem conta, recusa, ``errors`` ou fora do formato."""
    corpo = {"query": consulta}
    if variaveis:
        corpo["variables"] = variaveis
    resposta = _autorizado(
        "POST", JUNO, lambda token: {"Authorization": f"Bearer {token}", "User-Agent": conta.UA}, json=corpo
    )
    if resposta is None:
        return None
    if not isinstance(resposta, dict) or resposta.get("errors"):
        # Nunca a mensagem: ela pode repetir as variáveis.
        logging.info("EA: a consulta voltou com erro ou fora do formato")
        return None
    dados = resposta.get("data")
    return dados if isinstance(dados, dict) else None


def _psd_da_conta() -> Optional[str]:
    global _psd  # pylint: disable=global-statement
    token = conta.autorizacao()
    if token is None:
        # Sem token: deixa o pedido seguinte dizer se é sem conta ou falha de rede.
        return _psd_novo()
    with _trava_do_psd:
        if _psd is not None and _psd[0] == token:
            return _psd[1]
    valor = _psd_novo()
    if valor is not None:
        with _trava_do_psd:
            _psd = (token, valor)
    return valor


def _psd_novo() -> Optional[str]:
    valor = _caminho(_juno(_PSD), "me", "player", "psd")
    if not isinstance(valor, str) or not valor or not codifica(valor):
        if valor is not None:
            logging.info("EA: psd fora do formato")
        return None
    return valor


def conjunto_da_oferta(oferta: str) -> Optional[str]:
    """O id do conjunto de conquistas da oferta; ``""`` = oferta sem conquistas;
    ``None`` = sem conta ou resposta inválida. Levanta ``FalhaDeRede``."""
    if not isinstance(oferta, str) or not oferta or not codifica(oferta):
        return None
    psd = _psd_da_conta()
    if psd is None:
        return None
    dados = _juno(_CONJUNTO, {"o": oferta, "p": psd})
    lista = dados.get("achievements") if dados is not None else None
    if not isinstance(lista, list):
        if dados is not None:
            logging.info("EA: conjunto fora do formato")
        return None
    for item in lista:
        identificador = item.get("id") if isinstance(item, dict) else None
        if conjunto_valido(identificador):
            return identificador
    return ""


# --- arquivos de cache ------------------------------------------------------


def _ler_dicionario(arquivo: Path) -> dict:
    try:
        dados = ler_json(arquivo)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError, RecursionError) as erro:
        logging.info("Cache da EA ilegível (%s)", type(erro).__name__)
        return {}
    return dados if isinstance(dados, dict) else {}


def _gravar(arquivo: Path, dados: dict) -> None:
    try:
        gravar_atomico(arquivo, json.dumps(dados, ensure_ascii=False))
    except (OSError, ValueError) as erro:
        logging.warning("Cache da EA não gravado: %s", type(erro).__name__)


def _arquivo_da_biblioteca() -> Path:
    return shared.conquistas_cache_dir / "ea-biblioteca.json"


def _arquivo_dos_jogos() -> Path:
    return shared.conquistas_cache_dir / "ea-jogos.json"


def _oferta_valida(oferta: Any) -> bool:
    return isinstance(oferta, str) and 0 < len(oferta) <= 256 and codifica(oferta)


def _ler_biblioteca() -> tuple[dict[str, list[str]], float]:
    """``(título normalizado → ofertas, quando foi buscada)``; ilegível = vazia e velha."""
    dados = _ler_dicionario(_arquivo_da_biblioteca())
    titulos, em = dados.get("titulos"), dados.get("em")
    if not isinstance(titulos, dict):
        return {}, 0.0
    limpos = {
        k: v for k, v in titulos.items()
        if isinstance(k, str) and isinstance(v, list) and all(_oferta_valida(o) for o in v)
    }
    return limpos, float(em) if numero_finito(em) else 0.0


def _buscar_biblioteca() -> Optional[dict[str, list[str]]]:
    """A biblioteca da conta. Levanta ``FalhaDeRede``; ``None`` = sem conta ou fora do formato."""
    itens = _caminho(_juno(_BIBLIOTECA), "me", "ownedGameProducts", "items")
    if not isinstance(itens, list):
        if itens is not None:
            logging.info("EA: biblioteca fora do formato")
        return None
    titulos: dict[str, list[str]] = {}
    for item in itens:
        oferta = item.get("originOfferId") if isinstance(item, dict) else None
        nome = _caminho(item, "product", "name")
        if not _oferta_valida(oferta) or not isinstance(nome, str):
            continue
        chave = normalizar(nome)
        ofertas_ = titulos.setdefault(chave, []) if chave else []
        if oferta not in ofertas_:
            ofertas_.append(oferta)
    with _trava_dos_arquivos:
        _gravar(_arquivo_da_biblioteca(), {"titulos": titulos, "em": int(time.time())})
    return titulos


def ofertas(titulo: str) -> Optional[list[str]]:
    """As ofertas da biblioteca com esse título (já normalizado), em ordem. ``[]`` = fora da
    biblioteca; ``None`` = sem conta ou resposta inválida. Só busca de novo se o jogo faltar e
    o cache tiver mais de um dia. Levanta ``FalhaDeRede``."""
    titulos, em = _ler_biblioteca()
    if titulo in titulos:
        return titulos[titulo]
    if 0 <= time.time() - em < _UM_DIA:
        return []
    novos = _buscar_biblioteca()
    if novos is None:
        return None
    return novos.get(titulo, [])


def conjunto_guardado(pasta: str) -> Optional[str]:
    """O conjunto guardado para a pasta do jogo; ``""`` = sem conquistas (vale um dia);
    ``None`` = não se sabe."""
    item = _ler_dicionario(_arquivo_dos_jogos()).get(pasta)
    if not isinstance(item, dict):
        return None
    conjunto, em = item.get("conjunto"), item.get("em")
    if conjunto == "":
        return "" if numero_finito(em) and 0 <= time.time() - em < _UM_DIA else None
    return conjunto if conjunto_valido(conjunto) else None


def guardar_conjunto(pasta: str, conjunto: str) -> None:
    if conjunto != "" and not conjunto_valido(conjunto):
        return
    with _trava_dos_arquivos:
        dados = _ler_dicionario(_arquivo_dos_jogos())
        dados[pasta] = {"conjunto": conjunto, "em": int(time.time())}
        _gravar(_arquivo_dos_jogos(), dados)


# --- API antiga -------------------------------------------------------------


def _porcentagem(valor: Any) -> Optional[float]:
    if not isinstance(valor, str):
        return None
    try:
        numero = float(valor)
    except ValueError:
        return None
    return numero if numero_finito(numero) and 0 <= numero <= 100 else None


def _icone(icones: Any) -> str:
    valor = _caminho({"i": icones}, "i", "208")
    return valor if isinstance(valor, str) and valor.startswith("https://") and codifica(valor) else ""


def _quando(valor: Any) -> int:
    if isinstance(valor, bool) or not isinstance(valor, int):
        return 0
    return valor if _DESDE_1971 <= valor < 2**63 else 0


def _conquista(chave: Any, item: Any) -> Optional[tuple[ConquistaInfo, Optional[Desbloqueio]]]:
    if not isinstance(chave, str) or not chave.strip() or not codifica(chave) or not isinstance(item, dict):
        return None
    nome, desc = item.get("name"), item.get("desc")
    feita, oculta = item.get("complete"), item.get("hidden")
    if not (isinstance(nome, str) and isinstance(desc, str) and isinstance(feita, bool) and isinstance(oculta, bool)):
        return None
    if oculta and not feita:
        titulo, descricao = _ESCONDIDA, ""
    else:
        titulo, descricao = limpo(nome).strip() or chave, limpo(desc)
    info = ConquistaInfo(
        nome=f"{PREFIXO}{chave}",
        titulo=titulo,
        descricao=descricao,
        icone=_icone(item.get("icons")),
        icone_cinza="",
        oculta=oculta,
        porcentagem=_porcentagem(item.get("achievedPercentage")),
    )
    # Na bloqueada o `u` é ignorado: a EA põe a hora da consulta.
    return info, Desbloqueio(info.nome, _quando(item.get("u"))) if feita else None


def _antiga(conjunto: str) -> Optional[tuple[list[ConquistaInfo], list[Desbloqueio]]]:
    """Catálogo e progresso do conjunto, num pedido só. Levanta ``FalhaDeRede``."""
    persona = conta.persona()
    if not conjunto_valido(conjunto) or not persona:
        return None
    corpo = _autorizado(
        "GET", f"{ANTIGA}/{persona}/{conjunto}/all",
        lambda token: {
            "AuthToken": token, "X-Api-Version": "2", "X-Application-Key": "Origin", "User-Agent": conta.UA,
        },
        params={"lang": "pt_BR", "metadata": "true", "fullset": "true"},
    )
    itens = corpo.get("achievements") if isinstance(corpo, dict) else None
    if not isinstance(itens, dict):
        if corpo is not None:
            logging.info("EA: conjunto de conquistas fora do formato")
        return None
    infos, feitas = [], []
    for chave, item in itens.items():
        lida = _conquista(chave, item)
        if lida is None:
            logging.info("EA: conquista com campo inválido descartada")
            continue
        infos.append(lida[0])
        if lida[1] is not None:
            feitas.append(lida[1])
    if not any(i.porcentagem for i in infos):
        # A EA não calcula raridade de alguns jogos (Battlefield 6): tudo vem
        # "0.00", e mostrar 0,0% em todas as conquistas seria enganoso.
        infos = [replace(i, porcentagem=None) for i in infos]
    return infos, feitas


# --- o que a varredura e o vigia pedem --------------------------------------


def ler(conjunto: str) -> Optional[Leitura]:
    """Catálogo e progresso da conta; guarda o catálogo no cache.

    Levanta ``FalhaDeRede``. ``None``: sem conta, acesso recusado, conjunto inválido
    ou resposta inválida.
    """
    lido = _antiga(conjunto)
    if lido is None:
        return None
    infos, feitas = lido
    cat = Catalogo(
        tuple(infos), int(time.time()), False, "",
        sem_raridade=bool(infos) and all(i.porcentagem is None for i in infos),
    )
    try:
        catalogo.guardar(chave_do_catalogo(conjunto), cat)
    except (OSError, ValueError) as erro:
        logging.warning("Catálogo de conquistas da EA não gravado: %s", type(erro).__name__)
    return Leitura(cat, feitas)


def desbloqueadas(conjunto: str) -> Optional[list[Desbloqueio]]:
    """Só o progresso, para o vigia. Levanta ``FalhaDeRede``."""
    lido = _antiga(conjunto)
    return None if lido is None else lido[1]
