"""As conferências antes de deixar o Ludusavi restaurar uma versão.

Funções puras sobre nomes e caminhos: se o zip da versão está inteiro, que caminhos
trocar quando o usuário do Windows ou a pasta do jogo mudaram, e se os destinos que
a prévia da restauração mostra são lugares de save. Um backup importado não pode
gravar fora das pastas de save nem deixar um executável ou um script para trás.
Rodar o Ludusavi e avisar o usuário é de quem chama.
"""

import os
import re
import zipfile
import zlib
from dataclasses import dataclass
from pathlib import Path

from cartridges.conquistas import arquivos
from cartridges.saves.ludusavi import Previa
from cartridges.saves.pasta import dentro

# Dentro do zip de uma versão cada arquivo fica em `drive-<letra>/<caminho>`; o
# registro vai em `registry.reg`, na raiz.
_NOME_NO_ZIP = re.compile(r"drive-([A-Za-z])/(.*[^/])")


def integra(arquivo: Path | None) -> bool:
    """Se o zip da versão existe, abre e todos os seus arquivos passam no CRC."""
    if arquivo is None:
        return False
    try:
        with zipfile.ZipFile(arquivo) as zip_:
            return zip_.testzip() is None
    # Tudo o que o `zipfile` levanta ao ler um zip ausente, truncado ou estragado
    # (`ValueError` inclui o `UnicodeDecodeError` de um nome de arquivo danificado).
    except (
        OSError,
        ValueError,
        zipfile.BadZipFile,
        zlib.error,
        EOFError,
        NotImplementedError,
        RuntimeError,
    ):
        return False


def caminhos_no_zip(arquivo: Path) -> list[str]:
    """Os arquivos da versão com o caminho de origem: `drive-C/Users/x/a.sav` vira
    `C:/Users/x/a.sav`. O que não está numa pasta `drive-<letra>` (o registro) fica de fora."""
    with zipfile.ZipFile(arquivo) as zip_:
        nomes = zip_.namelist()
    achados = (_NOME_NO_ZIP.fullmatch(nome) for nome in nomes)
    return [f"{achado[1]}:/{achado[2]}" for achado in achados if achado]


# O que, dentro da pasta de um jogo, é save de emulador (as entradas de
# `config.na_pasta_do_jogo`): o que vem antes do marcador é a pasta do jogo.
MARCADORES = (
    "/coldclient/steam_settings/",
    "/steam_settings/",
    "/SteamData/user_stats.ini",
    "/3DMGAME/",
    "/Profile/",
)
_USUARIO = re.compile(r"[A-Za-z]:/Users/[^/]+", re.IGNORECASE)
_MARCADOR = re.compile("|".join(map(re.escape, MARCADORES)), re.IGNORECASE)


def redirecionamentos(
    caminhos: list[str], casa: Path, bases_atuais: list[Path]
) -> list[tuple[str, str]]:
    """Os (origem, destino) que levam os saves da versão ao lugar de hoje, sem repetição.

    Primeiro os usuários: `X:/Users/<nome>`, que não é a pasta de `casa` e não existe,
    vai para `casa`. Depois a pasta do jogo: das pastas de jogo (antes de um marcador)
    que não existem mais e não são as atuais, a mais alta dá a raiz antiga (subindo pelas
    pastas de binários, como `arquivos.bases_da_pasta`), e um redirecionamento só leva
    essa raiz à raiz atual (a última de `bases_atuais`): a estrutura de dentro se mantém.
    A origem fica com o texto do zip: o Ludusavi a compara sem trocar maiúsculas.
    """
    usuarios: dict[str, None] = {}
    antigas: list[Path] = []
    for caminho in caminhos:
        if usuario := _USUARIO.match(caminho):
            if not dentro(Path(usuario[0]), casa) and not Path(usuario[0]).exists():
                usuarios[usuario[0]] = None
            # ponytail: um jogo instalado dentro do perfil de um usuário não ganha
            # redirecionamento da pasta do jogo — o do usuário já leva o caminho (o
            # Ludusavi encadeia dois sobre o mesmo caminho). Para tratar, o do jogo
            # teria de substituir o do usuário.
            continue
        if (marcador := _MARCADOR.search(caminho)) and bases_atuais:
            pasta = Path(caminho[: marcador.start()])
            if pasta not in bases_atuais and not pasta.exists():
                antigas.append(pasta)
    achados = [(origem, casa.as_posix()) for origem in usuarios]
    if antigas:
        antiga = arquivos.bases_da_pasta(min(antigas, key=lambda pasta: len(pasta.parts)))[-1]
        if antiga != bases_atuais[-1] and not antiga.exists():
            achados.append((antiga.as_posix(), bases_atuais[-1].as_posix()))
    return achados


@dataclass(frozen=True)
class Raizes:
    """Onde uma restauração pode gravar, as pastas dentro disso onde nunca grava, e a
    pasta do usuário (`casa`), onde nenhum arquivo solto pode ser gravado."""

    permitidas: tuple[Path, ...]
    proibidas: tuple[Path, ...]
    casa: Path


def raizes(pastas: arquivos.Pastas, casa: Path, extras: list[Path]) -> Raizes:
    """As pastas do usuário e do sistema onde um jogo guarda o save, mais as `extras`
    (a Steam, o Ubisoft Connect, a pasta do jogo). Documentos entra como o Windows o
    informa: pode estar em outro disco. As proibidas são onde um arquivo vira programa
    ou credencial."""
    return Raizes(
        permitidas=(
            casa,
            pastas.appdata,
            pastas.localappdata,
            pastas.documentos,
            pastas.documentos_publicos.parent,
            pastas.programdata,
            *extras,
        ),
        proibidas=(
            pastas.appdata / "Microsoft",
            pastas.localappdata / "Microsoft",
            pastas.programdata / "Microsoft",
            pastas.documentos / "WindowsPowerShell",
            pastas.documentos / "PowerShell",
            casa / ".ssh",
            casa / ".local",  # o site-packages do usuário: o Python do app o lê ao abrir
            casa / ".config" / "git",  # o `core.fsmonitor` roda um programa
        ),
        casa=casa,
    )


EXTENSOES_PROIBIDAS = frozenset(
    {
        ".exe", ".dll", ".sys", ".drv", ".ocx", ".cpl", ".scr", ".com", ".pif", ".bat", ".cmd",
        ".ps1", ".psm1", ".psd1", ".vbs", ".vbe", ".js", ".jse", ".wsf", ".wsh", ".hta", ".msi",
        ".msp", ".lnk", ".url", ".reg", ".jar", ".py", ".pyw",
        # carregados por outro programa: complementos, módulos nativos, ajuda e atalhos
        ".asi", ".node", ".pyd", ".xll", ".xla", ".xlam", ".chm", ".msc", ".appref-ms",
        ".asar", ".scf", ".inf",
        # Python: o `.pth` roda a linha `import`; os compilados rodam sem o fonte
        ".pth", ".pyc", ".pyo", ".pyz", ".pyzw",
        # scripts e atalhos do Windows
        ".wsc", ".sct", ".settingcontent-ms", ".library-ms", ".searchconnector-ms",
        ".search-ms", ".ps1xml",
        # instaladores de aplicativo
        ".application", ".appinstaller", ".msix", ".msixbundle", ".appx", ".appxbundle",
    }
)

# Em minúsculas e com `/`: o registro do Windows não distingue maiúsculas.
CHAVES_PROIBIDAS = (
    "hkey_current_user/software/microsoft/",
    "hkey_current_user/software/classes/",
    "hkey_current_user/software/policies/",
    "hkey_current_user/software/wow6432node/microsoft/",
)
_CHAVES_PERMITIDAS = "hkey_current_user/software/"
_BARRAS = re.compile(r"[\\/]+")


def _resolvido(caminho: str | Path) -> Path:
    """O caminho como o Windows o enxerga: sem `..`, sem pontos e espaços no fim dos
    nomes, e com as junções, os links simbólicos e os nomes curtos (`MICROS~1`) trocados
    pelo que de fato são. O que ainda não existe fica como está."""
    return Path(os.path.realpath(os.path.abspath(caminho)))


def _arquivo_recusado(arquivo: str, reais: Raizes) -> bool:
    """`reais` são as raízes já resolvidas (`_resolvido`): o destino é comparado com elas
    pelo que é no disco, e não pelo texto."""
    # Pelo texto, antes de o disco ser consultado: olhar um caminho de rede já faria
    # o Windows conectar na máquina e mandar as credenciais do usuário.
    if arquivos.eh_caminho_de_rede(arquivo) or not Path(arquivo).is_absolute():
        return True
    # Fora o da unidade, `:` só aparece em fluxo alternativo do NTFS: `x.exe::$DATA`
    # cria `x.exe`, e `Microsoft::$INDEX_ALLOCATION` é a própria pasta `Microsoft`.
    if ":" in os.path.splitdrive(arquivo)[1]:
        return True
    caminho = _resolvido(arquivo)
    return (
        not any(dentro(caminho, raiz) for raiz in reais.permitidas)
        or any(dentro(caminho, raiz) for raiz in reais.proibidas)
        or caminho.parent == reais.casa
        or caminho.suffix.casefold() in EXTENSOES_PROIBIDAS
    )


def _chave_recusada(chave: str) -> bool:
    chave = _BARRAS.sub("/", chave).casefold()
    # Com a barra no fim, a própria chave proibida (sem subchave) também cai.
    return not chave.startswith(_CHAVES_PERMITIDAS) or (chave + "/").startswith(CHAVES_PROIBIDAS)


def recusado(previa: Previa, limites: Raizes) -> str | None:
    """O primeiro arquivo (e só depois a primeira chave de registro) da prévia que a
    restauração não pode tocar, ou `None` se todos podem. Pode ser `""`: compare com `None`."""
    reais = Raizes(
        tuple(map(_resolvido, limites.permitidas)),
        tuple(map(_resolvido, limites.proibidas)),
        _resolvido(limites.casa),
    )
    achado = next((a for a in previa.arquivos if _arquivo_recusado(a, reais)), None)
    if achado is None:
        achado = next((c for c in previa.chaves if _chave_recusada(c)), None)
    return achado
