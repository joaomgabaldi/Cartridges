# shortcuts_source.py
#
# Copyright 2024 kramo
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Fonte do Windows que importa atalhos de jogos (``.lnk`` / ``.url``).

Cobre ``.lnk`` clássicos (resolvidos ao executável), ``.url`` (launchers como ``steam://`` e ``com.epicgames.launcher://``)
e ``.lnk`` de apps UWP/Store (lançados por ``shell:AppsFolder``). Os ``.lnk`` são resolvidos em lote pelo PowerShell
(COM ``WScript.Shell``/``Shell.Application``), que lê o alvo e o AppUserModelID sem dependência Python.
"""

import configparser
import json
import logging
import os
import re
import subprocess
import tempfile
from hashlib import sha256
from pathlib import Path
from typing import Optional

from cartridges import shared
from cartridges.jogo import Jogo
from cartridges.importer.source import Source, SourceIterable, SourceScanError
from cartridges.utils.name_cleaner import clean_game_name

_STEAM_APPID_RE = re.compile(r"steam://(?:rungameid|run)/(\d+)", re.IGNORECASE)

# Nunca chegam a um argumento cmd.exe entre aspas: aspas fecham a citação e deixam metacaracteres injetar comandos; controle quebra comando; `%` expande variáveis até entre aspas (`%CMDCMDLINE:~-1%` é um `"`), por isso só passa a codificação percentual ASCII (`%3A`, `%20`, usada pelas URLs da Epic). `!` fica permitido: expansão tardia desligada e caminhos reais o usam ("Overcooked! 2").
_UNSAFE_CMD_CHARS_RE = re.compile(r'["\x00-\x1f]|%(?![2-7][0-9A-Fa-f])')

# O que o cmd.exe interpreta fora de aspas: encadeamento/agrupamento, redireção e escape (`^`); entre aspas é literal (ver `args_safe`).
_SHELL_METACHARS = frozenset("&|<>^()")

# Recusados em argumentos com ou sem aspas: controle (quebra de linha termina o comando), `%` (expande até dentro de aspas) e `!` (expansão tardia, a um valor de registro de ser ligada).
_ARGS_ALWAYS_UNSAFE_RE = re.compile(r"[\x00-\x1f%!]")

# Alvo em unidade ou compartilhamento UNC: é caminho de arquivo mesmo com o arquivo ausente (disco desconectado) e mantém identidade e comando de arquivo (ver `build_from_lnk`).
_ABSOLUTE_PATH_RE = re.compile(r"^(?:[A-Za-z]:[\\/]|[\\/]{2}[^\\/])")


def cmd_safe(value: str) -> bool:
    """Se ``value`` cabe num argumento cmd.exe entre aspas.

    Os comandos rodam com ``shell=True`` e atalhos são dados de terceiros: uma URL/alvo forjada não pode escapar da citação.
    """
    return not _UNSAFE_CMD_CHARS_RE.search(value)


def args_safe(value: str) -> bool:
    """Se ``value`` pode ser anexado *sem aspas* à linha de comando do cmd.exe.

    Os argumentos de um atalho não podem ser envolvidos em aspas (o jogo receberia um só argumento), então vão crus, e esta é a fronteira de segurança: fora de aspas `& | < > ^ ( )` viram comando do atacante. O texto é percorrido como o cmd.exe faz (cada ``"`` alterna a citação, sem escape) e um metacaractere só passa dentro de aspas abertas; as aspas precisam fechar, para a citação não vazar para o que vier depois. `%`, `!` e controle são recusados em todo lugar (``_ARGS_ALWAYS_UNSAFE_RE``). Isso aceita lançadores reais (GOG ``/path="D:\\GOG Games\\X"``, Battle.net ``--exec="launch Pro"``).
    """
    if _ARGS_ALWAYS_UNSAFE_RE.search(value):
        return False
    quoted = False
    for char in value:
        if char == '"':
            quoted = not quoted
        elif not quoted and char in _SHELL_METACHARS:
            return False
    return not quoted

# Nomes que claramente não são jogos. "Manual", "Support" e "Benchmark" só como última palavra: em qualquer posição levavam jogos reais ("Manual Samuel").
_SKIP_NAME_RE = re.compile(
    r"\b(uninstall|uninstaller|readme|read me|website|home\s*page)\b"
    r"|\b(manual|support|benchmark)\s*$",
    re.IGNORECASE,
)


def steam_appid_from_url(value: str) -> Optional[str]:
    """Appid simples da Steam de uma URL de lançamento, se houver; ids compostos de 64 bits (mods/atalhos não-Steam) são ignorados."""
    if not value:
        return None
    match = _STEAM_APPID_RE.search(value)
    if not match:
        return None
    appid = match.group(1)
    return appid if len(appid) <= 7 else None


def resolve_lnk_targets(paths: list[Path]) -> dict[str, dict]:
    """Resolve um lote de ``.lnk`` via PowerShell COM: ``str(path)`` -> dict com ``Target``, ``Arguments``, ``Icon``, ``WorkingDirectory`` e ``Aumid``."""
    if not paths:
        return {}

    list_file = Path(tempfile.gettempdir()) / f"cartridges_lnks_{os.getpid()}.txt"
    list_file.write_text("\n".join(str(path) for path in paths), encoding="utf-8")

    # Emitido pelo pipeline e coletado uma vez: o `$out += ...` anterior copia o array a cada item (O(n²)).
    # fmt: off
    script = (
        "[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
        "$ErrorActionPreference='SilentlyContinue';"
        "$wsh=New-Object -ComObject WScript.Shell;"
        "$shell=New-Object -ComObject Shell.Application;"
        f"$res=@(Get-Content -LiteralPath $env:CARTRIDGES_LNK_LIST -Encoding UTF8 | ForEach-Object {{"
        "  $p=[string]$_; if([string]::IsNullOrWhiteSpace($p)){return};"
        "  $sc=$wsh.CreateShortcut($p); $aumid='';"
        "  try{"
        # `.Replace`, não `-replace` (regex: a barra invertida no destino é escape). O parser de namespace do shell é mais estrito que as APIs de arquivo: um caminho com barras normais dá namespace nulo, sem AUMID, e atalhos Store/Game Pass seriam descartados e removidos por `remove_games`. A versão anterior (GTK, ucrt64) gravava esses caminhos. Corrigido no PowerShell para `File=$p` ecoar o caminho como escrito, a chave de `lnk_data`.
        "    $ns=$shell.Namespace(((Split-Path $p).Replace('/','\\')));"
        "    if($ns){$it=$ns.ParseName((Split-Path $p -Leaf));"
        "      if($it){$aumid=$it.ExtendedProperty('System.AppUserModel.ID')}}"
        "  }catch{};"
        "  [PSCustomObject]@{File=$p;Target=$sc.TargetPath;"
        "    Arguments=$sc.Arguments;Icon=$sc.IconLocation;"
        "    WorkingDirectory=$sc.WorkingDirectory;Aumid=$aumid}"
        "});"
        "$res | ConvertTo-Json -Compress"
    )
    # fmt: on

    # O caminho da lista vai por variável de ambiente, não embutido no script: aspas ou caracteres especiais não quebram nem injetam no PowerShell.
    env = {**os.environ, "CARTRIDGES_LNK_LIST": str(list_file)}

    try:
        proc = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
            ],
            capture_output=True,
            timeout=180,
            check=False,
            env=env,
            # Avoid flashing a console window when launched from the GUI
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        out = proc.stdout.decode("utf-8", "replace").strip()
    except (OSError, subprocess.SubprocessError) as error:
        logging.warning("Could not resolve .lnk shortcuts: %s", error)
        return {}
    finally:
        list_file.unlink(missing_ok=True)

    if not out:
        return {}

    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        logging.warning("Unexpected PowerShell output while resolving shortcuts")
        return {}

    if isinstance(data, dict):  # ConvertTo-Json unwraps single-element arrays
        data = [data]

    return {
        item["File"]: item
        for item in data
        if isinstance(item, dict) and item.get("File")
    }


def resolve_start_apps() -> list[tuple[str, str]]:
    """Pares ``(nome, AUMID de lançamento)`` de cada app do Menu Iniciar.

    O ``System.AppUserModel.ID`` dos ``.lnk`` Xbox/Store só agrupa na barra de tarefas e o ``shell:AppsFolder`` não o lança (só abre a pasta de apps); o id real vem do ``Get-StartApps``.
    """
    script = (
        "[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
        "Get-StartApps | Select-Object Name,AppID | ConvertTo-Json -Compress"
    )
    try:
        proc = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
            ],
            capture_output=True,
            timeout=60,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        out = proc.stdout.decode("utf-8", "replace").strip()
    except (OSError, subprocess.SubprocessError) as error:
        logging.warning("Could not list Start apps: %s", error)
        return []

    if not out:
        return []

    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return []

    if isinstance(data, dict):  # ConvertTo-Json unwraps single-element arrays
        data = [data]

    return [
        (item["Name"], item["AppID"])
        for item in data
        if isinstance(item, dict) and item.get("Name") and item.get("AppID")
    ]


def atalhos_da_pasta() -> list[Path]:
    """Os ``.lnk`` e ``.url`` da pasta de atalhos, com ou sem subpastas conforme a preferência (vazio se a pasta não existir).

    Compartilhada com a janela de pendências da restauração, que deve oferecer exatamente o que a importação enxerga.
    """
    location = shared.schema.get_string("shortcuts-location")
    if not location:
        return []
    root = Path(location).expanduser()
    if not root.is_dir():
        return []

    if shared.schema.get_boolean("shortcuts-recursive"):
        # os.walk, não rglob: o rglob entra em junções NTFS (criáveis sem admin) e uma que volte a um pai repetia cada atalho dezenas de vezes; as junções são podadas aqui, como em `install_size.folder_size`.
        entries: list[Path] = []
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [
                d for d in dirnames if not os.path.isjunction(os.path.join(dirpath, d))
            ]
            entries += (Path(dirpath, filename) for filename in filenames)
    else:
        entries = list(root.glob("*"))

    return [
        entry
        for entry in entries
        if entry.is_file() and entry.suffix.lower() in (".lnk", ".url")
    ]


class ShortcutsSourceIterable(SourceIterable):
    source: "ShortcutsSource"

    def __iter__(self):
        """Gera jogos dos atalhos. A existência da pasta já é checada em `is_available`; `atalhos_da_pasta` devolve vazio se ela sumir no meio."""

        url_files: list[Path] = []
        lnk_files: list[Path] = []
        for entry in atalhos_da_pasta():
            if entry.suffix.lower() == ".url":
                url_files.append(entry)
            else:
                lnk_files.append(entry)

        # Os `.url` primeiro, de propósito: são lidos aqui e não caem com as falhas do PowerShell abaixo, então uma varredura que desiste ainda conta o que viu.
        for entry in url_files:
            yield self.build_from_url(entry)

        lnk_data = resolve_lnk_targets(lnk_files)
        # Lote vazio para entrada não vazia é falha, não pasta sem atalhos (`resolve_lnk_targets` devolve {} para PowerShell ausente, política bloqueada ou timeout): tratado como "sem jogos" marcaria todo jogo .lnk como removido, para sempre. Os `.url` resolvem à parte, então checar só se a fonte produziu algo não pegaria isto.
        if lnk_files and not lnk_data:
            raise SourceScanError(
                _("Não foi possível ler os atalhos"),
                _(
                    "O Windows não conseguiu resolver os atalhos (.lnk) da pasta. "
                    "Verifique se o PowerShell está disponível e tente importar novamente."
                ),
            )

        # Mapeia os AUMIDs de agrupamento para os de lançamento (Xbox/Store). O Get-StartApps abre um PowerShell inteiro (1-3 s): só se algum atalho tiver AUMID.
        needs_start_apps = any(
            (item.get("Aumid") or "").strip() for item in lnk_data.values()
        )
        start_apps = resolve_start_apps() if needs_start_apps else []
        # Mesmo raciocínio, mais forte aqui: quem tem atalhos da Store sempre tem apps no Menu Iniciar, então lista vazia é consulta quebrada (timeout de 60 s). Seguir adiante gravaria, via `Store._refresh_derived_executable`, o comando degradado no lugar do AUMID de cada jogo Xbox/Game Pass, junto com a identidade do pacote que o tempo de jogo segue.
        if needs_start_apps and not start_apps:
            raise SourceScanError(
                _("Não foi possível ler os aplicativos do menu Iniciar"),
                _(
                    "O problema afeta jogos da Microsoft Store e do Game Pass. "
                    "Verifique se o PowerShell está disponível e tente importar "
                    "novamente."
                ),
            )
        self._aumid_by_name = {name.casefold(): appid for name, appid in start_apps}
        self._aumid_by_pkgkey = {}
        for _name, appid in start_apps:
            # "<pkgname>_<hash>!<app>" -> key "<pkgname>_<app>"
            if "!" in appid and "_" in (pfn := appid.split("!", 1)[0]):
                pkgname = pfn.rsplit("_", 1)[0]
                self._aumid_by_pkgkey[f"{pkgname}_{appid.split('!', 1)[1]}".casefold()] = (
                    appid
                )

        for entry in lnk_files:
            yield self.build_from_lnk(entry, lnk_data.get(str(entry)))

    def build_from_url(self, entry: Path):
        parser = configparser.ConfigParser(interpolation=None, strict=False)
        try:
            raw = entry.read_bytes()
            try:
                text = raw.decode("utf-8-sig")
            except UnicodeDecodeError:
                # O Windows grava .url na página de código ANSI, não UTF-8: um IconFile acentuado tornava o arquivo ilegível e o jogo da biblioteca era marcado removido.
                text = raw.decode("mbcs")
            parser.read_string(text)
        except (configparser.Error, OSError, UnicodeDecodeError) as error:
            logging.warning("Unreadable internet shortcut %s: %s", entry.name, error)
            return None

        if not parser.has_section("InternetShortcut"):
            return None

        url = parser.get("InternetShortcut", "URL", fallback="").strip()
        if not url or url.lower().startswith(("http://", "https://")):
            return None

        # Segurança: a URL entra num comando cmd.exe; recusa o que escape da citação (injeção por .url forjado).
        if not cmd_safe(url):
            logging.warning("Ignoring unsafe URL in shortcut %s", entry)
            return None

        name = clean_game_name(entry.stem)
        if _SKIP_NAME_RE.search(name):
            return None

        additional_data: dict = {}
        if appid := steam_appid_from_url(url):
            additional_data["steam_appid"] = appid
        # Como no ramo .lnk: o arquivo é o estável, a URL dentro dele não (um launcher que reemite o esquema, ou um atalho da Epic com catálogo novo, renomeia o jogo).
        additional_data["identity_anchor"] = str(entry)
        additional_data["alvo"] = url

        return (
            self._make_game(
                name, f'start "" "{url}"', url, self._mtime(entry), str(entry)
            ),
            additional_data,
        )

    def build_from_lnk(self, entry: Path, data: Optional[dict]):
        name = clean_game_name(entry.stem)
        if _SKIP_NAME_RE.search(name):
            return None

        if not data:
            logging.debug("Could not resolve shortcut %s", entry)
            return None

        target = (data.get("Target") or "").strip()
        arguments = (data.get("Arguments") or "").strip()
        workdir = (data.get("WorkingDirectory") or "").strip()
        aumid = (data.get("Aumid") or "").strip()

        additional_data: dict = {}

        # Segurança: alvo e pasta de trabalho entram em argumentos cmd.exe entre aspas; caminhos legítimos não têm aspas/controle, então o atalho é pulado. `arguments` também é checado e é o que importava: vai *sem aspas* (`Arguments = & calc.exe` virava `start "" "game.exe" & calc.exe` em `shell=True`). A regra mais estrita abaixo também recusa metacaracteres do shell fora de aspas.
        if not cmd_safe(target) or not cmd_safe(workdir):
            logging.warning("Ignoring shortcut with unsafe target: %s", entry)
            return None

        if arguments and not args_safe(arguments):
            logging.warning("Ignoring shortcut with unsafe arguments: %s", entry)
            return None

        # Alvo com cara de caminho de arquivo é arquivo mesmo ausente (USB desconectado): pelo ramo de URI o hash perderia `|arguments`, o id mudaria e a âncora trocaria o comando por um mais pobre. Só caminho ausente cai aqui; pasta existente e app empacotado (WindowsApps) seguem seus ramos.
        # UNC nunca é consultado no disco: o Windows conectaria à máquina e enviaria as credenciais da pessoa numa varredura que ninguém pediu para tocar a rede.
        is_path = target and Path(target).suffix.lower() != ".lnk"
        de_rede = target[:1] in ("\\", "/") and target[1:2] in ("\\", "/")
        if is_path and (
            (not de_rede and Path(target).is_file())
            or (
                not aumid
                and _ABSOLUTE_PATH_RE.match(target)
                and (de_rede or not Path(target).exists())
            )
        ):
            executable = 'start ""'
            if workdir:
                executable += f' /D "{workdir}"'
            executable += f' "{target}"'
            if arguments:
                executable += f" {arguments}"
            identity = f"{target}|{arguments}"
            additional_data["alvo"] = target
            if appid := (
                steam_appid_from_url(arguments) or steam_appid_from_url(target)
            ):
                additional_data["steam_appid"] = appid

        elif aumid:
            # App UWP / Microsoft Store: a identidade é o AUMID *como o atalho o traz*, nunca o resolvido (o Get-StartApps pode falhar, e um timeout mudava o id, fazendo `remove_games` levar tempo de jogo, capa e logo). O resolvido é detalhe de lançamento, recuperável porque `Store._refresh_derived_executable` readota o comando relido.
            launch_aumid = self._real_aumid(entry.stem, aumid)
            identity = f"uwp:{aumid}"
            # Segurança: o AUMID entra sem aspas no shell; os reais só usam caracteres de palavra mais ".", "!", "+" e "-" (forma PFN!AppId).
            if not re.fullmatch(r"[\w.!+\-]+", launch_aumid):
                logging.warning("Ignoring shortcut with unsafe AUMID: %s", entry)
                return None
            if "!" in launch_aumid:
                executable = f"explorer.exe shell:AppsFolder\\{launch_aumid}"
            elif cmd_safe(str(entry)):
                # Um id de agrupamento sem "!" não lança: o `shell:AppsFolder` só abre a pasta de apps. Lança-se o próprio atalho, e sem AUMID o jogo fica fora do rastreio de tempo de jogo empacotado.
                logging.info("No launchable AUMID for %s; using the shortcut", entry)
                executable = f'start "" "{entry}"'
            else:
                logging.warning("Ignoring shortcut with unsafe path: %s", entry)
                return None

        elif target:
            # URI de protocolo (steam://), caminho relativo ou pasta (`cmd_safe` já foi imposto em `target`).
            if target.lower().startswith(("http://", "https://")):
                return None
            executable = f'start "" "{target}"'
            identity = target
            additional_data["alvo"] = target
            if appid := steam_appid_from_url(target):
                additional_data["steam_appid"] = appid

        else:
            logging.debug("Shortcut %s has no usable target", entry)
            return None

        # A store casa pelo arquivo de atalho, para todo atalho: o clássico faz hash de `alvo|argumentos`, então editar o alvo (patch, launcher que muda o executável) renomeava o jogo e `remove_games` levava tempo de jogo, capa e logo. O arquivo é o que a pessoa cura; o alvo é detalhe de lançamento.
        # Atalho *renomeado* não precisa da âncora: o id não inclui o nome do arquivo e o ramo de duplicado segue o caminho novo.
        additional_data["identity_anchor"] = str(entry)

        return (
            self._make_game(
                name, executable, identity, self._mtime(entry), str(entry)
            ),
            additional_data,
        )

    def _real_aumid(self, name: str, aumid: str) -> str:
        """Resolve o AUMID de um atalho para um lançável via Start apps: prefere o app de mesmo nome e, senão, a identidade do pacote (ids de agrupamento não têm o ``!``); sem correspondência devolve o original."""
        if real := self._aumid_by_name.get(name.casefold()):
            return real

        if "!" not in aumid:  # looks like a non-launchable grouping id
            candidates = [aumid.casefold()]
            if "." in aumid:  # drop a leading vendor segment, e.g. "XboxGames."
                candidates.append(aumid.split(".", 1)[1].casefold())
            for candidate in candidates:
                if real := self._aumid_by_pkgkey.get(candidate):
                    return real

        return aumid

    def _game_id(self, identity: str) -> str:
        digest = sha256(identity.encode("utf-8")).hexdigest()[:16]
        return self.source.game_id_format.format(game_id=digest)

    @staticmethod
    def _mtime(entry: Path) -> int:
        try:
            return int(entry.stat().st_mtime)
        except OSError:
            return 0

    def _make_game(
        self,
        name: str,
        executable: str,
        identity: str,
        mtime: int = 0,
        shortcut_path: str = "",
    ) -> Jogo:
        # Roda na thread do import: o Jogo é um QObject sem interface, e quem
        # o desenha conecta os sinais dele à thread principal.
        return Jogo(
            {
                "source": self.source.source_id,
                "added": shared.import_time,
                "name": name,
                "game_id": self._game_id(identity),
                "executable": executable,
                "shortcut_mtime": mtime,
                "shortcut_path": shortcut_path,
            }
        )


class ShortcutsSource(Source):

    source_id = "shortcuts"
    name = _("Atalhos")
    iterable_class = ShortcutsSourceIterable

    @property
    def is_available(self) -> bool:
        """Só com a pasta de atalhos configurada existente: uma pasta ausente (disco desconectado) deve pular a varredura, senão um scan "vazio" marcaria tudo como removido."""
        if not super().is_available:
            return False
        location = shared.schema.get_string("shortcuts-location")
        return bool(location) and Path(location).expanduser().is_dir()
