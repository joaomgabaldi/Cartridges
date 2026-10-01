"""O catálogo de conquistas de um jogo: nomes, descrições, ícones e raridade.

Com a chave da Steam Web API (Preferências), vem da Steam em português
(`GetSchemaForGame`, ``l=brazilian``). Sem chave, ou quando a Steam não tem
catálogo, vem do `steam_settings\\achievements.json` que muitos jogos trazem ao
lado do executável. A porcentagem global (`GetGlobalAchievementPercentagesForApp`)
não exige chave e é o que marca as raras (menos de 10% dos jogadores).

Guardado em cache por appID durante 7 dias. Rede fora usa o cache vencido: o
catálogo muda pouco, e um catálogo de ontem é melhor que nenhum.

Nada aqui levanta para quem chama: resposta da rede, arquivo do jogo e cache em
disco são lidos como dado não confiável, e o que não serve vira log e lista vazia.
"""

import hashlib
import json
import logging
import math
import threading
import time
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Iterable, Optional

from requests.exceptions import RequestException

from cartridges import shared
from cartridges.conquistas import arquivos
from cartridges.utils.download import get_capped
from cartridges.utils.ler_json import ler_json
from cartridges.utils.rate_limiter import RateLimiter

VALIDADE = 7 * 24 * 3600
RARA_ABAIXO_DE = 10.0
_API = "https://api.steampowered.com/ISteamUserStats"


class ChaveRecusada(Exception):
    """A Steam respondeu 403 à chave informada nas Preferências."""


@dataclass(frozen=True)
class ConquistaInfo:
    nome: str
    titulo: str
    descricao: str
    # URL da Steam ou caminho de um arquivo do jogo; "" quando não há.
    icone: str
    icone_cinza: str
    oculta: bool
    porcentagem: Optional[float] = None

    @property
    def rara(self) -> bool:
        return self.porcentagem is not None and self.porcentagem < RARA_ABAIXO_DE


@dataclass(frozen=True)
class Catalogo:
    conquistas: tuple[ConquistaInfo, ...]
    obtido_em: int
    # Se veio da Steam com chave.
    com_chave: bool
    # Impressão da chave configurada quando o catálogo foi feito ("" se não havia).
    # Chave nova, trocada ou removida renova o catálogo; a mesma chave, mesmo
    # recusada, não é tentada de novo antes dos 7 dias.
    impressao_da_chave: str = ""

    def por_nome(self) -> dict[str, ConquistaInfo]:
        return {info.nome.upper(): info for info in self.conquistas}


@dataclass(frozen=True)
class Renovacao:
    catalogo: Optional[Catalogo]
    chave_recusada: bool = False


class SteamWebApiLimiter(RateLimiter):
    """A Web API permite 100 mil pedidos por dia; isto só evita rajadas."""

    refill_period_seconds = 60
    refill_period_tokens = 60
    burst_tokens = 10


_limitador: Optional[SteamWebApiLimiter] = None
_trava_do_limitador = threading.Lock()


def _limite() -> SteamWebApiLimiter:
    global _limitador  # pylint: disable=global-statement
    with _trava_do_limitador:
        if _limitador is None:
            _limitador = SteamWebApiLimiter()
        return _limitador


def _pedir(url: str) -> Any:
    with _limite():
        with get_capped(url, timeout=10) as resposta:
            if resposta.status_code == 403:
                raise ChaveRecusada()
            resposta.raise_for_status()
            return resposta.json()


def _sim(valor: Any) -> bool:
    return str(valor).strip().lower() in ("1", "true")


def ler_schema_da_steam(payload: Any) -> list[ConquistaInfo]:
    try:
        lista = payload["game"]["availableGameStats"]["achievements"]
    except (KeyError, TypeError):
        return []
    infos = []
    for item in lista if isinstance(lista, list) else []:
        if not isinstance(item, dict) or not str(item.get("name", "")).strip():
            continue
        nome = str(item["name"]).strip()
        infos.append(
            ConquistaInfo(
                nome=nome,
                titulo=str(item.get("displayName") or nome),
                descricao=str(item.get("description") or ""),
                icone=str(item.get("icon") or ""),
                icone_cinza=str(item.get("icongray") or item.get("icon") or ""),
                oculta=_sim(item.get("hidden", 0)),
            )
        )
    return infos


def _no_idioma(valor: Any) -> str:
    if isinstance(valor, dict):
        for idioma in ("brazilian", "portuguese", "english"):
            if valor.get(idioma):
                return str(valor[idioma])
        return next((str(texto) for texto in valor.values() if texto), "")
    return str(valor or "")


def ler_steam_settings(arquivo: Path) -> list[ConquistaInfo]:
    try:
        dados = json.loads(arquivo.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, RecursionError) as erro:
        logging.info("Catálogo local ilegível (%s): %s", arquivo, erro)
        return []
    if not isinstance(dados, list):
        return []

    def icone(valor: Any) -> str:
        valor = str(valor or "")
        if not valor or valor.startswith(("http://", "https://")):
            return valor
        local = arquivo.parent / valor
        return str(local) if local.is_file() else ""

    infos = []
    for item in dados:
        if not isinstance(item, dict) or not str(item.get("name", "")).strip():
            continue
        nome = str(item["name"]).strip()
        infos.append(
            ConquistaInfo(
                nome=nome,
                titulo=_no_idioma(item.get("displayName")) or nome,
                descricao=_no_idioma(item.get("description")),
                icone=icone(item.get("icon")),
                icone_cinza=icone(item.get("icon_gray") or item.get("icongray") or item.get("icon")),
                oculta=_sim(item.get("hidden", "0")),
            )
        )
    return infos


def ler_porcentagens(payload: Any) -> dict[str, float]:
    try:
        lista = payload["achievementpercentages"]["achievements"]
    except (KeyError, TypeError):
        return {}
    porcentagens = {}
    for item in lista if isinstance(lista, list) else []:
        try:
            porcentagem = float(item["percent"])
            nome = str(item["name"]).upper()
        except (KeyError, TypeError, ValueError, OverflowError):
            continue
        # "1e999" vira inf e "nan" é aceito por float(): nenhum dos dois é porcentagem.
        if math.isfinite(porcentagem):
            porcentagens[nome] = porcentagem
    return porcentagens


def com_porcentagens(
    infos: Iterable[ConquistaInfo], porcentagens: dict[str, float]
) -> list[ConquistaInfo]:
    return [
        replace(info, porcentagem=porcentagens.get(info.nome.upper(), info.porcentagem))
        for info in infos
    ]


def _arquivo_do_cache(appid: str) -> Path:
    return shared.conquistas_cache_dir / f"{appid}.json"


def _info_do_cache(item: Any) -> ConquistaInfo:
    """Um item do cache, ou levanta TypeError/OverflowError se o arquivo foi adulterado."""
    info = ConquistaInfo(**item)
    textos = (info.nome, info.titulo, info.descricao, info.icone, info.icone_cinza)
    porcentagem = info.porcentagem
    if (
        not all(isinstance(texto, str) for texto in textos)
        or not isinstance(info.oculta, bool)
        or (
            porcentagem is not None
            and (
                isinstance(porcentagem, bool)
                or not isinstance(porcentagem, (int, float))
                or not math.isfinite(porcentagem)
            )
        )
    ):
        raise TypeError("campo de tipo errado")
    return info


def _impressao_do_cache(valor: Any) -> str:
    if not isinstance(valor, str):
        raise TypeError("impressão da chave de tipo errado")
    return valor


def em_cache(appid: str) -> Optional[Catalogo]:
    try:
        dados = ler_json(_arquivo_do_cache(appid))
        return Catalogo(
            tuple(_info_do_cache(item) for item in dados["conquistas"]),
            int(dados["obtido_em"]),
            bool(dados["com_chave"]),
            _impressao_do_cache(dados.get("impressao_da_chave", "")),
        )
    except FileNotFoundError:
        return None
    except (OSError, ValueError, TypeError, KeyError, OverflowError, RecursionError) as erro:
        logging.info("Catálogo de conquistas em cache ilegível (%s): %s", appid, erro)
        return None


def _gravar_cache(appid: str, cat: Catalogo) -> None:
    destino = _arquivo_do_cache(appid)
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporario = destino.with_name(destino.name + ".tmp")
    temporario.write_text(
        json.dumps(
            {
                "obtido_em": cat.obtido_em,
                "com_chave": cat.com_chave,
                "impressao_da_chave": cat.impressao_da_chave,
                "conquistas": [asdict(info) for info in cat.conquistas],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    temporario.replace(destino)


def _impressao(chave: str) -> str:
    """Identifica a chave sem guardá-la: o cache fica em disco."""
    if not chave:
        return ""
    return hashlib.sha256(chave.encode()).hexdigest()[:16]


def vencido(cat: Catalogo, agora: int, impressao_atual: str) -> bool:
    return agora - cat.obtido_em >= VALIDADE or cat.impressao_da_chave != impressao_atual


def _local(executavel: str) -> list[ConquistaInfo]:
    for base in arquivos.bases_do_jogo(executavel):
        for arquivo in (
            base / "steam_settings" / "achievements.json",
            base / "coldclient" / "steam_settings" / "achievements.json",
        ):
            if arquivo.is_file() and (infos := ler_steam_settings(arquivo)):
                return infos
    return []


def _chave() -> str:
    return shared.schema.get_string("conquistas-chave-steam").strip()


def renovar(appid: str, executavel: str, agora: Optional[int] = None) -> Renovacao:
    """Busca o catálogo de novo e grava no cache. Nunca levanta."""
    agora = int(time.time()) if agora is None else agora
    chave = _chave()
    anterior = em_cache(appid)
    recusada = False
    infos: list[ConquistaInfo] = []
    com_chave = False
    impressao = _impressao(chave)

    if chave:
        try:
            infos = ler_schema_da_steam(
                _pedir(f"{_API}/GetSchemaForGame/v2/?key={chave}&appid={appid}&l=brazilian")
            )
            com_chave = bool(infos)
        except ChaveRecusada:
            recusada = True
        except (RequestException, ValueError, RecursionError) as erro:
            # Só o tipo: a mensagem do requests traz a URL, e a URL traz a chave.
            logging.info(
                "Catálogo de conquistas indisponível para %s: %s", appid, type(erro).__name__
            )
            if anterior is not None:
                return Renovacao(anterior)
            # Falha de rede não é veredito sobre a chave: sem impressão, a
            # próxima abertura tenta a Steam de novo.
            impressao = ""

    if not infos:
        infos = _local(executavel)
    if not infos:
        return Renovacao(anterior, recusada)

    porcentagens = {
        info.nome.upper(): info.porcentagem
        for info in (anterior.conquistas if anterior else ())
        if info.porcentagem is not None
    }
    try:
        porcentagens.update(
            ler_porcentagens(
                _pedir(f"{_API}/GetGlobalAchievementPercentagesForApp/v2/?gameid={appid}")
            )
        )
    except (ChaveRecusada, RequestException, ValueError, RecursionError) as erro:
        logging.info("Raridade das conquistas indisponível para %s: %s", appid, erro)

    cat = Catalogo(
        tuple(com_porcentagens(infos, porcentagens)), agora, com_chave, impressao
    )
    try:
        _gravar_cache(appid, cat)
    except OSError as erro:
        logging.warning("Catálogo de conquistas de %s não gravado: %s", appid, erro)
    return Renovacao(cat, recusada)


def obter(appid: str, executavel: str, agora: Optional[int] = None) -> Renovacao:
    """O catálogo em cache, renovado só quando venceu."""
    agora = int(time.time()) if agora is None else agora
    cat = em_cache(appid)
    if cat is not None and not vencido(cat, agora, _impressao(_chave())):
        return Renovacao(cat)
    return renovar(appid, executavel, agora)
