"""A API da Epic: catálogo de conquistas, progresso da conta e a biblioteca.

É o GraphQL da loja da Epic (`store.epicgames.com/graphql`), que só aceita consultas
registradas (*persisted queries*, pelo hash), por GET — os hashes são os que o achievist
usa (`app/platforms/epic.py`). Prova em ``docs/superpowers/prova-epic/resultado.md``.

- O catálogo é pedido por namespace (o ``sandboxId``), sem login, e traz o ``productId``.
- O progresso é pedido por ``productId`` e só reconhece a conta com o token no cookie
  ``EPIC_EG1``, como o site da Epic faz. A resposta diz se reconheceu
  (``relationship: SELF``); com a conta reconhecida, ``ServiceError`` é "nunca jogou".
- A biblioteca da conta (com o token no cabeçalho) liga o ``AppName`` dos atalhos antigos
  ao namespace.

Roda só em thread (varredura e vigia): faz rede e pode esperar o limitador. Todo dado que
vem da rede ou do cache é tratado como não confiável. Nada de token, variáveis ou corpo vai
para o log: só o tipo da exceção e o status.
"""

import json
import logging
import math
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Optional

import requests

from cartridges import shared
from cartridges.conquistas import catalogo
from cartridges.conquistas.catalogo import Catalogo, ConquistaInfo
from cartridges.conquistas.contas import Leitura
from cartridges.conquistas.epic import conta
from cartridges.conquistas.formatos import Desbloqueio
from cartridges.conquistas.saneamento import codifica, limpo, segundos_iso
from cartridges.utils import download
from cartridges.utils.ler_json import ler_json
from cartridges.utils.rate_limiter import RateLimiter

PREFIXO = "EPIC:"
LOCALE = "pt-BR"
_LOJA = "https://store.epicgames.com/graphql"
_BIBLIOTECA = "https://library-service.live.use1a.on.epicgames.com/library/api/public/items"
_CATALOGO = ("Achievement", "9284d2fe200e351d1496feda728db23bb52bfd379b236fc3ceca746c1f1b33f2")
_PROGRESSO = (
    "playerProfileAchievementsByProductId",
    "70ff714976f88a85aafa3cb5abb9909d52e12a3ff585d7b49550d2493a528fb0",
)
# Sem User-Agent, o Cloudflare da loja responde 403.
_NAVEGADOR = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
)
_SUCESSO = "PlayerProductAchievementsResponseSuccess"
_PAGINAS_DA_BIBLIOTECA = 20
_BIBLIOTECA_VALE = 24 * 3600
_TEMPO = 15
_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")


class FalhaDeRede(Exception):
    """A Epic não respondeu como devia (rede, 5xx, 429, não-JSON)."""


class EpicLimiter(RateLimiter):
    """Bem abaixo do que a loja da Epic faz numa página de perfil."""

    refill_period_seconds = 60
    refill_period_tokens = 30
    burst_tokens = 10


_limitador: Optional[EpicLimiter] = None
_trava_do_limitador = threading.Lock()
_trava_dos_arquivos = threading.Lock()


def _limite() -> EpicLimiter:
    global _limitador  # pylint: disable=global-statement
    with _trava_do_limitador:
        if _limitador is None:
            _limitador = EpicLimiter()
        return _limitador


def namespace_valido(valor: Any) -> bool:
    return isinstance(valor, str) and _ID.fullmatch(valor) is not None


def chave_do_catalogo(ns: str) -> str:
    return f"epic-{ns}"


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


def _pedir(metodo: str, url: str, **kwargs: Any) -> requests.Response:
    try:
        with _limite():
            return _requisitar(metodo, url, **kwargs)
    except requests.RequestException as erro:
        # Só o tipo: a mensagem do requests pode trazer a URL.
        logging.info("Epic: pedido falhou (%s)", type(erro).__name__)
        raise FalhaDeRede() from None


def _json(resposta: requests.Response) -> Optional[Any]:
    """O JSON da resposta; ``None`` para 4xx. Levanta ``FalhaDeRede`` para 429, 5xx e não-JSON."""
    status = resposta.status_code
    if status == 429 or status >= 500:
        logging.info("Epic: a Epic respondeu %s", status)
        raise FalhaDeRede()
    if status >= 400:
        logging.info("Epic: pedido recusado (%s)", status)
        return None
    try:
        return resposta.json()
    except (ValueError, RecursionError):
        logging.info("Epic: resposta que não é JSON")
        raise FalhaDeRede() from None


def _sem_autorizacao() -> None:
    """Sem token: sem conta (ou recusada e já desconectada) é None; conta ainda
    conectada é a renovação que falhou por rede (Ruling 5 da fase 4)."""
    if conta.conectada():
        logging.info("Epic: a renovação do acesso falhou")
        raise FalhaDeRede()
    return None


def _caminho(dados: Any, *chaves: str) -> Any:
    for chave in chaves:
        if not isinstance(dados, dict):
            return None
        dados = dados.get(chave)
    return dados


def _consulta(operacao: tuple[str, str], variaveis: dict[str, str], acesso: Optional[str] = None) -> Optional[dict]:
    """Uma consulta registrada na loja. ``acesso`` vai no cookie do site."""
    nome, hash_ = operacao
    compacto = {"separators": (",", ":")}
    params = {
        "operationName": nome,
        "variables": json.dumps(variaveis, **compacto),
        "extensions": json.dumps({"persistedQuery": {"version": 1, "sha256Hash": hash_}}, **compacto),
    }
    cabecalhos = {
        "User-Agent": _NAVEGADOR,
        "Origin": "https://store.epicgames.com",
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json",
    }
    if acesso:
        cabecalhos["Cookie"] = f"EPIC_EG1={acesso}"
    corpo = _json(_pedir("GET", _LOJA, params=params, headers=cabecalhos))
    if corpo is None:
        return None
    if not isinstance(corpo, dict) or corpo.get("errors"):
        # Nunca a mensagem: ela pode repetir as variáveis.
        logging.info("Epic: a consulta voltou com erro ou fora do formato")
        return None
    dados = corpo.get("data")
    return dados if isinstance(dados, dict) else None


# --- catálogo ---------------------------------------------------------------


def _texto(item: dict, chave: str, reserva: str) -> Optional[str]:
    valor = item.get(chave)
    if not isinstance(valor, str) or not valor:
        valor = item.get(reserva)
    return limpo(valor) if isinstance(valor, str) else None


def _icone(valor: Any) -> str:
    return valor if isinstance(valor, str) and valor.startswith("https://") and codifica(valor) else ""


def _porcentagem(item: dict) -> Optional[float]:
    valor = _caminho(item, "rarity", "percent")
    if (
        isinstance(valor, bool)
        or not isinstance(valor, (int, float))
        or not math.isfinite(valor)
        or not 0 <= valor <= 100
    ):
        return None
    return float(valor)


def _info(item: Any) -> Optional[ConquistaInfo]:
    if not isinstance(item, dict):
        return None
    nome = item.get("name")
    # O nome vira a chave do histórico: um que não grava em UTF-8 derruba a conquista.
    if not isinstance(nome, str) or not nome.strip() or not codifica(nome):
        return None
    titulo = _texto(item, "unlockedDisplayName", "lockedDisplayName")
    if titulo is None:
        return None
    return ConquistaInfo(
        nome=f"{PREFIXO}{nome}",
        titulo=titulo.strip() or nome,
        descricao=_texto(item, "unlockedDescription", "lockedDescription") or "",
        icone=_icone(item.get("unlockedIconLink")),
        icone_cinza=_icone(item.get("lockedIconLink")),
        oculta=item.get("hidden") is True,
        porcentagem=_porcentagem(item),
    )


def _catalogo(ns: str) -> Optional[tuple[str, list[ConquistaInfo]]]:
    """``(productId, conquistas)``; ``("", [])`` = jogo sem conquistas. Sem login."""
    dados = _consulta(_CATALOGO, {"sandboxId": ns, "locale": LOCALE})
    registro = _caminho(dados, "Achievement", "productAchievementsRecordBySandbox")
    if not isinstance(registro, dict):
        if dados is not None:
            logging.info("Epic: catálogo fora do formato")
        return None
    itens = registro.get("achievements")
    if itens is None:
        return "", []
    produto = registro.get("productId")
    if not isinstance(itens, list) or not namespace_valido(produto):
        logging.info("Epic: catálogo fora do formato")
        return None
    infos = []
    for item in itens:
        info = _info(item.get("achievement") if isinstance(item, dict) else None)
        if info is not None:
            infos.append(info)
        else:
            logging.info("Epic: conquista com campo inválido descartada")
    return produto, infos


# --- progresso --------------------------------------------------------------


def _feitas(lista: Any) -> list[Desbloqueio]:
    achados = []
    for item in lista if isinstance(lista, list) else []:
        feita = item.get("playerAchievement") if isinstance(item, dict) else None
        if not isinstance(feita, dict) or feita.get("unlocked") is not True:
            continue
        nome = feita.get("achievementName")
        if not isinstance(nome, str) or not nome.strip() or not codifica(nome):
            continue
        achados.append(Desbloqueio(f"{PREFIXO}{nome}", segundos_iso(feita.get("unlockDate"))))
    return achados


def _desbloqueios(produto: str) -> Optional[list[Desbloqueio]]:
    """O progresso da conta no produto. Levanta ``FalhaDeRede``."""
    conta_id = conta.account_id()
    if not conta_id:
        return None
    perfil = None
    for forcar in (False, True):
        acesso = conta.autorizacao(forcar=forcar)
        if acesso is None:
            return _sem_autorizacao()
        dados = _consulta(_PROGRESSO, {"epicAccountId": conta_id, "productId": produto}, acesso)
        perfil = _caminho(dados, "PlayerProfile", "playerProfile")
        if not isinstance(perfil, dict):
            if dados is not None:
                logging.info("Epic: progresso fora do formato")
            return None
        if perfil.get("relationship") == "SELF":
            break
        # A loja não reconheceu a conta: o token pode ter vencido antes da hora.
        logging.info("Epic: a loja não reconheceu a conta")
    else:
        # Duas vezes sem reconhecer: não é a conta (a renovação diria), é a loja. Só log.
        return None
    resultado = perfil.get("productAchievements")
    tipo = resultado.get("__typename") if isinstance(resultado, dict) else None
    if tipo == "ServiceError":
        # Com a conta reconhecida, é o jogo que nunca foi jogado nesta conta.
        return []
    if tipo != _SUCESSO:
        logging.info("Epic: progresso fora do formato")
        return None
    return _feitas(_caminho(resultado, "data", "playerAchievements"))


# --- produto de cada namespace (o progresso é por produto) ------------------


def _arquivo_dos_produtos() -> Path:
    return shared.conquistas_cache_dir / "epic-produtos.json"


def _ler_dicionario(arquivo: Path) -> dict:
    try:
        dados = ler_json(arquivo)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError, RecursionError) as erro:
        logging.info("Cache da Epic ilegível (%s)", type(erro).__name__)
        return {}
    return dados if isinstance(dados, dict) else {}


def _gravar(arquivo: Path, dados: dict) -> None:
    temporario = arquivo.with_name(f"{arquivo.name}.{uuid.uuid4().hex}.tmp")
    try:
        arquivo.parent.mkdir(parents=True, exist_ok=True)
        temporario.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
        temporario.replace(arquivo)
    except (OSError, ValueError) as erro:
        logging.warning("Cache da Epic não gravado: %s", type(erro).__name__)
    finally:
        try:
            temporario.unlink(missing_ok=True)
        except OSError:
            pass


def _produto_guardado(ns: str) -> Optional[str]:
    produto = _ler_dicionario(_arquivo_dos_produtos()).get(ns)
    return produto if namespace_valido(produto) else None


def _guardar_produto(ns: str, produto: str) -> None:
    with _trava_dos_arquivos:
        dados = {k: v for k, v in _ler_dicionario(_arquivo_dos_produtos()).items() if namespace_valido(v)}
        if dados.get(ns) != produto:
            dados[ns] = produto
            _gravar(_arquivo_dos_produtos(), dados)


# --- o que a varredura e o vigia pedem --------------------------------------


def ler(ns: str) -> Optional[Leitura]:
    """Catálogo e progresso da conta; guarda o catálogo no cache.

    Levanta ``FalhaDeRede``. ``None``: sem conta, desconectou, namespace inválido
    ou resposta inválida.
    """
    if not namespace_valido(ns):
        return None
    lido = _catalogo(ns)
    if lido is None:
        return None
    produto, infos = lido
    if produto:
        _guardar_produto(ns, produto)
        desbloqueios = _desbloqueios(produto)
        if desbloqueios is None:
            return None
    else:
        desbloqueios = []
    cat = Catalogo(
        tuple(infos),
        int(time.time()),
        False,
        "",
        sem_raridade=bool(infos) and all(i.porcentagem is None for i in infos),
    )
    try:
        catalogo.guardar(chave_do_catalogo(ns), cat)
    except (OSError, ValueError) as erro:
        logging.warning("Catálogo de conquistas da Epic não gravado: %s", type(erro).__name__)
    return Leitura(cat, desbloqueios)


def desbloqueadas(ns: str) -> Optional[list[Desbloqueio]]:
    """Só o progresso, para o vigia. Levanta ``FalhaDeRede``."""
    if not namespace_valido(ns):
        return None
    produto = _produto_guardado(ns)
    if produto is None:
        lido = _catalogo(ns)
        if lido is None:
            return None
        produto = lido[0]
        if not produto:
            return []
        _guardar_produto(ns, produto)
    return _desbloqueios(produto)


# --- biblioteca -------------------------------------------------------------


def _arquivo_da_biblioteca() -> Path:
    return shared.conquistas_cache_dir / "epic-biblioteca.json"


def _ler_biblioteca() -> tuple[dict[str, str], float]:
    """``(AppName sem caixa → namespace, quando foi buscada)``; ilegível = vazia e velha."""
    dados = _ler_dicionario(_arquivo_da_biblioteca())
    apps, em = dados.get("apps"), dados.get("em")
    if not isinstance(apps, dict):
        return {}, 0.0
    limpos = {k: v for k, v in apps.items() if isinstance(k, str) and namespace_valido(v)}
    valido = isinstance(em, (int, float)) and not isinstance(em, bool) and math.isfinite(em)
    return limpos, float(em) if valido else 0.0


def _chamar_biblioteca(params: dict[str, str]) -> Optional[Any]:
    """Um pedido à biblioteca, com o token no cabeçalho; 401 renova uma vez."""
    for forcar in (False, True):
        acesso = conta.autorizacao(forcar=forcar)
        if acesso is None:
            return _sem_autorizacao()
        resposta = _pedir(
            "GET", _BIBLIOTECA, params=params,
            headers={"Authorization": f"bearer {acesso}", "Accept": "application/json"},
        )
        if resposta.status_code != 401:
            return _json(resposta)
    logging.info("Epic: biblioteca recusou o acesso duas vezes; desconectando a conta")
    conta.recusada()
    return None


def _buscar_biblioteca() -> Optional[dict[str, str]]:
    """A biblioteca inteira da conta. Levanta ``FalhaDeRede``; ``None`` = sem conta ou fora do formato."""
    apps: dict[str, str] = {}
    cursor: Optional[str] = None
    for _pagina in range(_PAGINAS_DA_BIBLIOTECA):
        params = {"includeMetadata": "true"}
        if cursor:
            params["cursor"] = cursor
        corpo = _chamar_biblioteca(params)
        registros = corpo.get("records") if isinstance(corpo, dict) else None
        if not isinstance(registros, list):
            if corpo is not None:
                logging.info("Epic: biblioteca fora do formato")
            return None
        for registro in registros:
            if not isinstance(registro, dict):
                continue
            app, ns = registro.get("appName"), registro.get("namespace")
            if isinstance(app, str) and app and codifica(app) and namespace_valido(ns):
                apps[app.casefold()] = ns
        cursor = _caminho(corpo, "responseMetadata", "nextCursor")
        if not isinstance(cursor, str) or not cursor:
            break
    with _trava_dos_arquivos:
        _gravar(_arquivo_da_biblioteca(), {"apps": apps, "em": int(time.time())})
    return apps


def namespace_local_do_app(app_name: str) -> Optional[str]:
    """O namespace do ``AppName`` pelo cache da biblioteca, sem rede; None se não está lá."""
    if not isinstance(app_name, str) or not app_name:
        return None
    return _ler_biblioteca()[0].get(app_name.casefold())


def namespace_do_app(app_name: str) -> Optional[str]:
    """O namespace do ``AppName``: o cache e, se faltar e ele tiver mais de um dia, a
    biblioteca da conta. ``""`` = fora da biblioteca (até a próxima busca);
    ``None`` = não se sabe (sem conta). Levanta ``FalhaDeRede``."""
    if not isinstance(app_name, str) or not app_name:
        return ""
    chave = app_name.casefold()
    apps, em = _ler_biblioteca()
    if chave in apps:
        return apps[chave]
    if 0 <= time.time() - em < _BIBLIOTECA_VALE:
        return ""
    novos = _buscar_biblioteca()
    if novos is None:
        return None
    return novos.get(chave, "")
