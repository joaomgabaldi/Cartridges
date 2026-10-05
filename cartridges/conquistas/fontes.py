"""De onde vêm as conquistas de cada jogo — ou de lugar nenhum, e o cartão some.

Três respostas: a conta Xbox (jogo do Xbox/Game Pass com a conta Microsoft
conectada), a Steam ou um emulador (appID e onde ler o progresso: atalho
`steam://`, arquivo de emulador, ou sinal de emulador na pasta do jogo), ou
nenhuma. Jogo do Xbox sem conta não cai para a Steam: o catálogo da Steam
ficaria parado em "0 de N", que é justamente o que esta regra acaba.

`do_jogo` olha o disco e roda em thread (varredura, vigia). A página do jogo
não pode tocar no disco do jogo (um HD dormindo travaria a tela), então a
varredura grava a fonte no histórico (`historico.registrar(..., fonte=)`) e o
cartão usa `gravada`.
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from cartridges.conquistas import arquivos, historico
from cartridges.conquistas.xbox import api, conta
from cartridges.utils.run_executable import aumid_from_command

XBOX = "xbox"
STEAM = "steam"
SINAIS_DE_EMULADOR = frozenset(
    {
        "steam_settings",
        "steam_emu.ini",
        "ali213.ini",
        "onlinefix.ini",
        "onlinefix64.dll",
        "cream_api.ini",
        "codex.ini",
        "3dmgame.ini",
    }
)


@dataclass(frozen=True)
class Fonte:
    tipo: str
    # titleId (xbox) ou appID (steam); "" num xbox ainda sem titleId (nunca gravado).
    id: str

    @property
    def texto(self) -> str:
        return f"{self.tipo}:{self.id}"

    @staticmethod
    def de_texto(texto: Optional[str]) -> Optional["Fonte"]:
        if not isinstance(texto, str) or texto.count(":") != 1:
            return None
        tipo, id_ = texto.split(":")
        if tipo not in (XBOX, STEAM) or not arquivos.appid_valido(id_):
            return None
        return Fonte(tipo, id_)


def pfn(game: Any) -> Optional[str]:
    aumid = aumid_from_command(getattr(game, "executable", "") or "")
    return (aumid.split("!", 1)[0] or None) if aumid else None


def bases(game: Any) -> list[Path]:
    return arquivos.bases_do_jogo(getattr(game, "executable", "") or "")


def _tem_config(pastas: list[Path]) -> bool:
    return any((base / "MicrosoftGame.config").is_file() for base in pastas)


def eh_do_xbox(game: Any) -> bool:
    try:
        return pfn(game) is not None or _tem_config(bases(game))
    except OSError:
        return False


def _tem_sinal(pastas: list[Path]) -> bool:
    for base in pastas:
        try:
            if any(item.name.casefold() in SINAIS_DE_EMULADOR for item in base.iterdir()):
                return True
        except OSError:
            continue
    return False


def _da_steam(game: Any) -> Optional[Fonte]:
    appid = getattr(game, "steam_appid", None)
    if not arquivos.appid_valido(appid):
        return None
    executavel = getattr(game, "executable", "") or ""
    if (
        arquivos.eh_jogo_da_steam(executavel)
        or arquivos.arquivos_do_jogo(str(appid), executavel)
        or _tem_sinal(arquivos.bases_do_jogo(executavel))
    ):
        return Fonte(STEAM, str(appid))
    return None


def do_jogo(game: Any) -> Optional[Fonte]:
    """A fonte do jogo, olhando o disco. Roda em thread e nunca levanta."""
    try:
        if eh_do_xbox(game):
            if not conta.conectada():
                return None
            titulo = api.titulo_local(pfn(game), bases(game))
            if titulo is None:
                return Fonte(XBOX, "")
            if titulo:
                return Fonte(XBOX, titulo)
            # "" é pacote sabidamente sem Xbox Live: vale a regra da Steam.
        return _da_steam(game)
    except Exception:  # pylint: disable=broad-exception-caught
        logging.warning(
            "Falha ao decidir a fonte das conquistas de %s", getattr(game, "name", "?"), exc_info=True
        )
        return None


def gravada(game: Any) -> Optional[Fonte]:
    """A fonte guardada no histórico. Só lê o arquivo do histórico, nunca o disco do jogo."""
    return Fonte.de_texto(historico.fonte(game.game_id))


def ativa(fonte: Optional[Fonte]) -> bool:
    return fonte is not None and (fonte.tipo != XBOX or conta.conectada())


def chave_do_catalogo(fonte: Fonte) -> str:
    return api.chave_do_catalogo(fonte.id) if fonte.tipo == XBOX else fonte.id
