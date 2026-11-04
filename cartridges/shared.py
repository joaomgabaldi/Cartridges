# shared.py
#
# Copyright 2022-2023 kramo
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

import json
import os
from pathlib import Path
from typing import Literal

from cartridges.configuracoes import Configuracoes


APP_ID = "io.github.joaomgabaldi.Cartridges"
VERSION = "2.0.0"
PREFIX = "/io/github/joaomgabaldi/Cartridges"
# Versão do spec do game_id.json.
SPEC_VERSION = 1.6

_INSTALACAO = Path(__file__).resolve().parent / "instalacao.json"


def canal() -> Literal["desenvolvimento", "final"]:
    try:
        texto = _INSTALACAO.read_text(encoding="utf-8")
    except FileNotFoundError:
        return "desenvolvimento"
    except (OSError, UnicodeDecodeError):
        texto = None
    try:
        valor = json.loads(texto)["canal"]
    except (TypeError, ValueError, KeyError):
        valor = None
    if valor not in ("final", "desenvolvimento"):
        raise SystemExit(
            "A instalação do Kyron está danificada. Reinstale o aplicativo."
        )
    return valor


_sufixo = "" if canal() == "final" else "-dev"

home = Path.home()

data_dir = Path(os.environ.get("LOCALAPPDATA") or home / "AppData" / "Local")

APP_DIR_NAME = APP_ID + _sufixo

app_dir = (
    Path(os.environ["CARTRIDGES_DADOS"])
    if os.environ.get("CARTRIDGES_DADOS")
    else data_dir / APP_DIR_NAME
)

chave_do_registro = os.environ.get("CARTRIDGES_REGISTRO") or (
    r"Software\GSettings\io\github\joaomgabaldi\Cartridges" + _sufixo
)

schema = Configuracoes(chave_do_registro, "@APP_ID@")
state_schema = Configuracoes(chave_do_registro + r"\State", "@APP_ID@.State")

games_dir = app_dir / "games"
covers_dir = app_dir / "covers"
logos_dir = app_dir / "logos"
wallpapers_dir = app_dir / "wallpapers"

fitas_dir = app_dir / "fitas"
fitas_arquivo = app_dir / "fitas.json"

# As conquistas desbloqueadas de cada jogo, uma por arquivo, com o nome do id (`conquistas/historico.py`).
conquistas_dir = app_dir / "conquistas"

conquistas_cache_dir = app_dir / "cache" / "conquistas"

# Cópias reduzidas das capas animadas, uma por tamanho de exibição (`utils/copias_animadas.py`).
capas_animadas_dir = app_dir / "cache" / "capas_animadas"

# Contas de lojas (Microsoft/Xbox, Epic e EA), com a chave de renovação cifrada pelo DPAPI: presa a este PC e a este
# usuário do Windows, então fica fora do backup (`utils/backup.py`).
contas_dir = app_dir / "contas"

# Conta de nuvem da Tuya do assistente das fitas, criptografada com o DPAPI (ver `utils/tuya_conta.py`).
tuya_conta_arquivo = app_dir / "tuya_conta.json"

# Deliberadamente NÃO `GLib.get_user_cache_dir()`: no Windows resolve para CSIDL_INTERNET_CACHE
# (`AppData\Local\Microsoft\Windows\INetCache`), pasta que a Limpeza de Disco e o Sensor de Armazenamento esvaziam,
# levando o log da execução que deu errado.
log_dir = app_dir / "logs"

image_size = (600, 900)

# Padrões sempre presentes.
scale_factor = 1
display_size = (200, 300)

details_size = (420, 630)

# pylint: disable=invalid-name
sessao = None
conquistas = None
# O `Aplicativo` do app Qt (importando, avisos); None nos testes que não o criam.
aplicativo = None
preferencias = None
edicao = None
importer = None
import_time = None
store = None
log_files = []
