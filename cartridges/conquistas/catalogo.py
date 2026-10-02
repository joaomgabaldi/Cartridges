"""O catálogo de conquistas de um jogo: nomes, descrições, ícones e raridade.

Primeiro, o schema que a Steam deste PC já guardou para o jogo
(`appcache\\stats\\UserGameStatsSchema_<appid>.bin`): o catálogo inteiro, em
português e sem rede. Sem ele, com a chave da Steam Web API (Preferências), vem
da Steam em português (`GetSchemaForGame`, ``l=brazilian``). Sem nenhum dos
dois, ou quando a Steam não tem catálogo, vem do
`steam_settings\\achievements.json` que muitos jogos trazem ao lado do
executável. A porcentagem global (`GetGlobalAchievementPercentagesForApp`)
não exige chave e é o que marca as raras (menos de 10% dos jogadores).

Guardado em cache por appID durante 7 dias (1 dia quando a raridade não pôde
ser buscada e nenhuma conquista tem porcentagem). Rede fora usa o cache vencido: o
catálogo muda pouco, e um catálogo de ontem é melhor que nenhum. O schema local
da Steam, quando existe, vem antes e não precisa de rede nem de chave; um schema
mais novo que o cache também o renova.

Nada aqui levanta para quem chama: resposta da rede, arquivo do jogo e cache em
disco são lidos como dado não confiável, e o que não serve vira log e lista vazia.
"""

import hashlib
import json
import logging
import math
import re
import threading
import time
import uuid
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Iterable, Optional
from urllib.parse import quote

from requests.exceptions import RequestException

from cartridges import shared
from cartridges.conquistas import arquivos, keyvalues, schema_da_steam
from cartridges.utils.download import get_capped
from cartridges.utils.ler_json import ler_json
from cartridges.utils.rate_limiter import RateLimiter

VALIDADE = 7 * 24 * 3600
# Catálogo feito sem a raridade (sem rede, ou o pedido falhou): refeito mais cedo.
VALIDADE_SEM_RARIDADE = 24 * 3600
_FUTURO_TOLERADO = 24 * 3600
RARA_ABAIXO_DE = 10.0
_API = "https://api.steampowered.com/ISteamUserStats"
_ICONE_DA_STEAM = "https://shared.steamstatic.com/community_assets/images/apps/{appid}/{arquivo}"
# O schema traz só o nome do arquivo do ícone; qualquer outra coisa é ignorada.
_NOME_DE_ICONE = re.compile(r"^[A-Za-z0-9_-][A-Za-z0-9_.-]*$")


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
    # Se nenhuma conquista ficou com porcentagem porque a raridade não pôde ser
    # buscada: o catálogo vale 1 dia, não 7 (`VALIDADE_SEM_RARIDADE`).
    sem_raridade: bool = False

    def por_nome(self) -> dict[str, ConquistaInfo]:
        return {info.nome.upper(): info for info in self.conquistas}


@dataclass(frozen=True)
class Renovacao:
    catalogo: Optional[Catalogo]
    chave_recusada: bool = False
    # Um pedido à Steam falhou por rede (conexão, tempo esgotado, erro HTTP):
    # quem varre vários jogos para de pedir pelo resto da passada.
    rede_falhou: bool = False


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
        # Caminho de rede nunca: só checar o arquivo já conecta no servidor.
        if arquivos.eh_caminho_de_rede(valor):
            return ""
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


def _sem_token(valor: Any) -> Any:
    """Só texto: tira o "token" (identificador de tradução, nunca texto para ler) das
    línguas e ignora o que não é texto (uma seção dentro do schema, por exemplo)."""
    if isinstance(valor, dict):
        return {
            lingua: texto
            for lingua, texto in valor.items()
            if lingua != "token" and isinstance(texto, str)
        }
    return valor if isinstance(valor, str) else ""


def arquivo_do_schema_local(appid: str) -> Optional[Path]:
    """O schema do jogo que a Steam deste PC guardou, se houver."""
    steam = arquivos.pasta_da_steam()
    if steam is None or not arquivos.appid_valido(appid):
        return None
    arquivo = steam / "appcache" / "stats" / f"UserGameStatsSchema_{appid}.bin"
    return arquivo if arquivo.is_file() else None


def ler_schema_local(arquivo: Path, appid: str) -> list[ConquistaInfo]:
    dados = keyvalues.ler(arquivo)
    if dados is None:
        logging.info("Schema local da Steam ilegível: %s", arquivo)
        return []

    def icone(valor: Any) -> str:
        nome = str(valor or "").strip()
        return _ICONE_DA_STEAM.format(appid=appid, arquivo=nome) if _NOME_DE_ICONE.match(nome) else ""

    infos = []
    for conquista in schema_da_steam.conquistas(dados, appid):
        exibicao = conquista.display
        colorido = icone(exibicao.get("icon"))
        infos.append(
            ConquistaInfo(
                nome=conquista.nome,
                titulo=_no_idioma(_sem_token(exibicao.get("name"))) or conquista.nome,
                descricao=_no_idioma(_sem_token(exibicao.get("desc"))),
                icone=colorido,
                icone_cinza=icone(exibicao.get("icon_gray")) or colorido,
                oculta=_sim(exibicao.get("hidden", 0)),
            )
        )
    return infos


def _do_schema_local(appid: str) -> list[ConquistaInfo]:
    arquivo = arquivo_do_schema_local(appid)
    return ler_schema_local(arquivo, appid) if arquivo is not None else []


def _schema_local_mudou_em(appid: str, agora: int) -> Optional[int]:
    arquivo = arquivo_do_schema_local(appid)
    if arquivo is None:
        return None
    try:
        mudou_em = int(arquivo.stat().st_mtime)
    except (OSError, ValueError, OverflowError):
        return None
    # Data muito à frente do relógio (relógio errado quando a Steam gravou): o
    # catálogo nunca a alcançaria e seria refeito a cada abertura.
    return None if mudou_em - agora > _FUTURO_TOLERADO else mudou_em


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


def _sem_raridade_do_cache(valor: Any) -> bool:
    if not isinstance(valor, bool):
        raise TypeError("sem_raridade de tipo errado")
    return valor


def em_cache(appid: str) -> Optional[Catalogo]:
    try:
        dados = ler_json(_arquivo_do_cache(appid))
        return Catalogo(
            tuple(_info_do_cache(item) for item in dados["conquistas"]),
            int(dados["obtido_em"]),
            bool(dados["com_chave"]),
            _impressao_do_cache(dados.get("impressao_da_chave", "")),
            _sem_raridade_do_cache(dados.get("sem_raridade", False)),
        )
    except FileNotFoundError:
        return None
    except (OSError, ValueError, TypeError, KeyError, OverflowError, RecursionError) as erro:
        logging.info("Catálogo de conquistas em cache ilegível (%s): %s", appid, erro)
        return None


def _gravar_cache(appid: str, cat: Catalogo) -> None:
    destino = _arquivo_do_cache(appid)
    destino.parent.mkdir(parents=True, exist_ok=True)
    # Um nome por gravação: a varredura e a varredura de um jogo só podem
    # gravar o mesmo appID ao mesmo tempo.
    temporario = destino.with_name(f"{destino.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporario.write_text(
            json.dumps(
                {
                    "obtido_em": cat.obtido_em,
                    "com_chave": cat.com_chave,
                    "impressao_da_chave": cat.impressao_da_chave,
                    "sem_raridade": cat.sem_raridade,
                    "conquistas": [asdict(info) for info in cat.conquistas],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        temporario.replace(destino)
    finally:
        try:
            temporario.unlink(missing_ok=True)
        except OSError:
            pass


def _impressao(chave: str) -> str:
    """Identifica a chave sem guardá-la: o cache fica em disco."""
    if not chave:
        return ""
    return hashlib.sha256(chave.encode()).hexdigest()[:16]


def vencido(
    cat: Catalogo, agora: int, impressao_atual: str, schema_mudou_em: Optional[int] = None
) -> bool:
    # Cache de mais de um dia no futuro (relógio errado quando foi feito, ou
    # arquivo adulterado) nunca venceria: conta como vencido. Schema local mais
    # novo que o catálogo: a Steam o regravou (o jogo ganhou conquistas numa
    # atualização). Sem raridade, vale só 1 dia: a próxima abertura com rede a busca.
    validade = VALIDADE_SEM_RARIDADE if cat.sem_raridade else VALIDADE
    return (
        agora - cat.obtido_em >= validade
        or cat.obtido_em - agora > _FUTURO_TOLERADO
        or cat.impressao_da_chave != impressao_atual
        or (schema_mudou_em is not None and schema_mudou_em > cat.obtido_em)
    )


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


def renovar(
    appid: str,
    executavel: str,
    agora: Optional[int] = None,
    rede: bool = True,
    usar_chave: bool = True,
) -> Renovacao:
    """Busca o catálogo de novo e grava no cache. Nunca levanta.

    Com ``rede=False`` nada vai à Steam: vale o cache (mesmo vencido) ou o
    arquivo do jogo. É o que quem varre vários jogos usa depois que um pedido
    falhou por rede, para não esperar o tempo limite de cada jogo. O schema que a
    Steam deste PC guardou, quando existe, vem antes de tudo isso: não precisa de
    rede nem de chave.

    Com `usar_chave=False` a Steam já recusou a chave nesta passada: o schema
    não é pedido de novo, e o resultado sai como se a recusa tivesse acabado de
    voltar (``chave_recusada``). Com o schema local presente, nem a chave nem a
    recusa entram: o catálogo vem dele.
    """
    if not arquivos.appid_valido(appid):
        return Renovacao(None)
    agora = int(time.time()) if agora is None else agora
    chave = _chave()
    anterior = em_cache(appid)
    recusada = False
    rede_falhou = False
    schema_respondeu = False
    com_chave = False
    impressao = _impressao(chave)
    # O schema que a Steam deste PC já guardou é o catálogo inteiro, em
    # português e sem rede: com ele, a chave nem é usada neste jogo.
    infos: list[ConquistaInfo] = _do_schema_local(appid)

    if not infos and chave:
        if not rede:
            if anterior is not None:
                return Renovacao(anterior)
            # Nada foi perguntado à Steam, então não há veredito sobre a chave:
            # sem impressão, a próxima abertura tenta de novo.
            impressao = ""
        elif not usar_chave:
            recusada = True
        else:
            try:
                infos = ler_schema_da_steam(
                    _pedir(
                        f"{_API}/GetSchemaForGame/v2/"
                        f"?key={quote(chave, safe='')}&appid={appid}&l=brazilian"
                    )
                )
                com_chave = bool(infos)
                schema_respondeu = True
            except ChaveRecusada:
                recusada = True
            except (RequestException, ValueError, RecursionError) as erro:
                rede_falhou = isinstance(erro, RequestException)
                # Só o tipo: a mensagem do requests traz a URL, e a URL traz a chave.
                logging.info(
                    "Catálogo de conquistas indisponível para %s: %s", appid, type(erro).__name__
                )
                if anterior is not None:
                    return Renovacao(anterior, rede_falhou=rede_falhou)
                # Falha de rede não é veredito sobre a chave: sem impressão, a
                # próxima abertura tenta a Steam de novo.
                impressao = ""

    if not infos:
        infos = _local(executavel)
    if not infos:
        if (schema_respondeu or recusada) and (anterior is None or not anterior.conquistas):
            # A Steam respondeu à chave e o jogo não tem conquistas, ou recusou a
            # chave: guarda o "nenhuma" pelos mesmos 7 dias, em vez de perguntar a
            # cada abertura (trocar a chave muda a impressão e renova). O cartão
            # segue escondido (`progresso.montar` não monta catálogo vazio).
            vazio = Catalogo((), agora, schema_respondeu, impressao)
            try:
                _gravar_cache(appid, vazio)
            except OSError as erro:
                logging.warning("Catálogo de conquistas de %s não gravado: %s", appid, erro)
            return Renovacao(vazio, recusada)
        return Renovacao(anterior, recusada, rede_falhou)

    porcentagens = {
        info.nome.upper(): info.porcentagem
        for info in (anterior.conquistas if anterior else ())
        if info.porcentagem is not None
    }
    buscou_a_raridade = False
    if rede and not rede_falhou:
        try:
            porcentagens.update(
                ler_porcentagens(
                    _pedir(f"{_API}/GetGlobalAchievementPercentagesForApp/v2/?gameid={appid}")
                )
            )
            buscou_a_raridade = True
        except (ChaveRecusada, RequestException, ValueError, RecursionError) as erro:
            rede_falhou = isinstance(erro, RequestException)
            logging.info("Raridade das conquistas indisponível para %s: %s", appid, erro)

    conquistas = tuple(com_porcentagens(infos, porcentagens))
    sem_raridade = not buscou_a_raridade and not any(
        info.porcentagem is not None for info in conquistas
    )
    cat = Catalogo(conquistas, agora, com_chave, impressao, sem_raridade)
    try:
        _gravar_cache(appid, cat)
    except OSError as erro:
        logging.warning("Catálogo de conquistas de %s não gravado: %s", appid, erro)
    return Renovacao(cat, recusada, rede_falhou)


def obter(
    appid: str,
    executavel: str,
    agora: Optional[int] = None,
    rede: bool = True,
    usar_chave: bool = True,
) -> Renovacao:
    """O catálogo em cache, renovado só quando venceu."""
    if not arquivos.appid_valido(appid):
        return Renovacao(None)
    agora = int(time.time()) if agora is None else agora
    cat = em_cache(appid)
    if cat is not None and not vencido(
        cat, agora, _impressao(_chave()), _schema_local_mudou_em(appid, agora)
    ):
        return Renovacao(cat)
    return renovar(appid, executavel, agora, rede, usar_chave)
