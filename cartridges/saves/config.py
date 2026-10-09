"""O `config.yaml` do Ludusavi, montado como função pura.

O Ludusavi lê YAML, e JSON é YAML: o arquivo sai de `json.dumps`. Aqui só se
decide o que ele precisa saber (onde guardar os saves, as raízes das lojas, e
as pastas de emulador e da pasta do jogo de cada título); rodá-lo é de `ludusavi.py`.
"""

import json
import re
import winreg
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from cartridges.conquistas import arquivos
from cartridges.utils.gravar_atomico import gravar_atomico

# A pasta do sistema (atributo de `arquivos.Pastas`) e o seu nome no Ludusavi.
_PLACEHOLDERS = {
    "appdata": "<winAppData>",
    "localappdata": "<winLocalAppData>",
    "documentos": "<winDocuments>",
    "documentos_publicos": "<winPublic>/Documents",
    "programdata": "<winProgramData>",
}
_LAUNCHER_DA_UBISOFT = (
    winreg.HKEY_LOCAL_MACHINE,
    r"SOFTWARE\WOW6432Node\Ubisoft\Launcher",
    "InstallDir",
)


# O Ludusavi lê cada entrada de `files` como glob: `[`, `]`, `*` e `?` da pasta do
# jogo (`Jogo [Repack]`) precisam ser literais, como em `glob::Pattern::escape`.
_CURINGAS = re.compile(r"[\[\]*?]")


@dataclass(frozen=True)
class JogoNoConfig:
    nome: str
    appid: Optional[str]
    executavel: str
    no_manifesto: bool


def pastas_de_emulador(appid: str) -> list[str]:
    """A pasta do jogo em cada emulador: a que guarda o save e as conquistas.

    Sai de `arquivos._FIXOS`, cortada no appID (o Ludusavi copia a pasta inteira),
    sem repetição — as duas linhas do OnlineFix caem na mesma pasta.
    """
    pastas: dict[str, None] = {}
    for pasta, modelo, _formato in arquivos._FIXOS:
        pastas[f"{_PLACEHOLDERS[pasta]}/{modelo.split('{appid}')[0]}{appid}"] = None
    return list(pastas)


def na_pasta_do_jogo(executavel: str, appid: str) -> list[str]:
    """Os lugares de save que moram ao lado do executável, com `/` e absolutos."""
    caminhos = []
    for base in arquivos.bases_do_jogo(executavel):
        raiz = _CURINGAS.sub(lambda m: f"[{m.group()}]", base.as_posix())
        caminhos += [
            f"{raiz}/steam_settings/{appid}",
            f"{raiz}/coldclient/steam_settings/{appid}",
            f"{raiz}/SteamData/user_stats.ini",
            f"{raiz}/3DMGAME/*",
            f"{raiz}/Profile/*",
        ]
    return caminhos


def raizes(jogos: list[JogoNoConfig]) -> list[tuple[str, Path]]:
    """As raízes que o Ludusavi usa para achar os jogos: Steam, Ubisoft Connect e
    a pasta que contém a pasta de cada jogo (`otherWindows`), sem repetição."""
    achadas: list[tuple[str, Path]] = []
    if (steam := arquivos.pasta_da_steam()) is not None:
        achadas.append(("steam", steam))
    ubisoft = arquivos._valor_do_registro(*_LAUNCHER_DA_UBISOFT)
    if ubisoft and Path(ubisoft).is_absolute():
        achadas.append(("uplay", Path(ubisoft)))
    vistas = set()
    for jogo in jogos:
        bases = arquivos.bases_do_jogo(jogo.executavel)
        # Pai que é a raiz do disco (jogo em `C:\X`) pegaria todo jogo instalado nele.
        if not bases or (pai := bases[-1].parent).parent == pai or str(pai).casefold() in vistas:
            continue
        vistas.add(str(pai).casefold())
        achadas.append(("otherWindows", pai))
    return achadas


def montar(jogos: list[JogoNoConfig], pasta_dos_saves: Path, raizes: list[tuple[str, Path]]) -> dict:
    """O config completo. Jogo sem appID não tem como ser achado: fica de fora."""
    customizados = [
        {
            "name": jogo.nome,
            "integration": "extend" if jogo.no_manifesto else "override",
            "files": pastas_de_emulador(jogo.appid) + na_pasta_do_jogo(jogo.executavel, jogo.appid),
        }
        for jogo in jogos
        if jogo.appid is not None and arquivos.appid_valido(jogo.appid)
    ]
    return {
        "release": {"check": False},
        "backup": {
            "path": str(pasta_dos_saves),
            "format": {"chosen": "zip"},
            "retention": {"full": 5, "differential": 0},
        },
        "restore": {"path": str(pasta_dos_saves)},
        "roots": [{"store": loja, "path": str(pasta)} for loja, pasta in raizes],
        "customGames": customizados,
    }


def gravar(config: dict, pasta_config: Path) -> None:
    """Grava `<pasta_config>/config.yaml`. O Ludusavi só aceita `--config` absoluto."""
    gravar_atomico(pasta_config / "config.yaml", json.dumps(config, ensure_ascii=False, indent=2))
