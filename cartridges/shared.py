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
# The version of the game_id.json spec. Deliberately NOT bumped for the
# HowLongToBeat fields: they are nullable additions that an older Cartridges
# ignores harmlessly, whereas a bump makes `Store.add_game` reject every file
# as "from a newer version" and hide the user's whole library on a downgrade.
SPEC_VERSION = 1.6

_INSTALACAO = Path(__file__).resolve().parent / "instalacao.json"


def canal() -> Literal["desenvolvimento", "final"]:
    """O canal desta instalação, gravado em `instalacao.json` só pelo `montar_app_qt.py`.

    Sem o arquivo é uma execução a partir do código-fonte: `desenvolvimento`, que usa
    pasta e chave de registro próprias (sufixo `-dev`) e nunca encosta nos dados reais.
    """
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

# Só calcula caminhos: pastas e chaves de registro são criadas por quem grava.
# `CARTRIDGES_DADOS` e `CARTRIDGES_REGISTRO` (os testes) valem em qualquer canal.
data_dir = Path(os.environ.get("LOCALAPPDATA") or home / "AppData" / "Local")

# Name of the app's own folder inside the data/config dirs.
APP_DIR_NAME = APP_ID + _sufixo

app_dir = (
    Path(os.environ["CARTRIDGES_DADOS"])
    if os.environ.get("CARTRIDGES_DADOS")
    else data_dir / APP_DIR_NAME
)

# Subchave sob HKCU onde ficam as preferências.
chave_do_registro = os.environ.get("CARTRIDGES_REGISTRO") or (
    r"Software\GSettings\io\github\joaomgabaldi\Cartridges" + _sufixo
)

# Preferências no registro; só leem ao pedir um valor, nada é tocado na importação.
schema = Configuracoes(chave_do_registro, "@APP_ID@")
state_schema = Configuracoes(chave_do_registro + r"\State", "@APP_ID@.State")

games_dir = app_dir / "games"
covers_dir = app_dir / "covers"
# Official horizontal logos used as the details page header. Kept apart from
# the covers: a cover is user-facing data (it can be picked by hand, exported,
# and must survive), a logo is a purely decorative asset we can always fetch
# again, so deleting this folder costs nothing but a re-download.
logos_dir = app_dir / "logos"
# A arte que veste os monitores além do principal durante a sessão: a imagem de
# partida (uma por jogo) mais o sidecar que diz se ela foi escolhida à mão e em
# que faixa cortá-la para cada orientação de monitor. Apagar a pasta devolve
# todo mundo à escolha automática.
wallpapers_dir = app_dir / "wallpapers"

# As fitas de LED que acompanham a sessão: um sidecar por jogo com a cor e o
# brilho escolhidos, e ao lado o arquivo com as fitas configuradas. O arquivo
# carrega as chaves locais dos módulos, que é o que permite falar com eles sem
# passar pela nuvem — por isso ele não mora no GSettings.
fitas_dir = app_dir / "fitas"
fitas_arquivo = app_dir / "fitas.json"

# As conquistas desbloqueadas de cada jogo, uma por arquivo, com o nome do id
# (`conquistas/historico.py`). Entra no backup.
conquistas_dir = app_dir / "conquistas"

# Catálogos e ícones das conquistas: refeitos da rede, fora do backup.
conquistas_cache_dir = app_dir / "cache" / "conquistas"

# Cópias reduzidas das capas animadas, uma por tamanho de exibição
# (`utils/copias_animadas.py`). Poderiam ser refeitas da capa, mas entram no
# backup: levá-las prontas sai mais barato do que regerá-las ao restaurar.
capas_animadas_dir = app_dir / "cache" / "capas_animadas"

# Contas de lojas (Microsoft/Xbox, Epic e EA), com a chave de
# renovação cifrada pelo DPAPI: presa a este PC e a este usuário do Windows,
# então fica fora do backup (`utils/backup.py`).
contas_dir = app_dir / "contas"

# A conta de nuvem da Tuya que o assistente das fitas usa para buscar
# dispositivos. Fica criptografada com o DPAPI do Windows (ver
# `utils/tuya_conta.py`), amarrada à conta do Windows de quem roda o app. Vai no
# backup com o resto da pasta, mas só decifra de volta no mesmo PC e na mesma
# conta; em outro, o assistente pede os códigos de novo.
tuya_conta_arquivo = app_dir / "tuya_conta.json"

# Deliberately NOT `GLib.get_user_cache_dir()`. On Windows that resolves to
# CSIDL_INTERNET_CACHE — `AppData\Local\Microsoft\Windows\INetCache`, the
# browser's temporary files folder, which Disk Cleanup and Storage Sense empty
# by default. The session logs used to be written there, and the log of the run
# that went wrong is exactly what a cleanup sweep takes away between the crash
# and somebody looking for it. `AppData\Local\<app>` is the conventional
# Windows location, and it keeps everything the app writes under one root.
log_dir = app_dir / "logs"

# Stored cover masters are always kept at high resolution (600x900, the native
# SteamGridDB/Steam size) so covers stay crisp. The on-screen render size is
# derived from the monitor scale to keep memory and drawing cost reasonable.
image_size = (600, 900)

# Padrões sempre presentes. O `app.py` refaz `scale_factor`, `display_size` e
# `details_size` a partir dos monitores do Qt, depois de criar a QGuiApplication.
scale_factor = 1
display_size = (200, 300)

# The details page draws its cover at 420x630, not the grid's 200x300, so a
# texture decoded at `display_size` would be stretched to fill it. This is the
# size the page draws and therefore the size it decodes; the cover files
# themselves are stored at 600x900, so this is still a reduction of the file.
# Deliberately a second number rather than a bigger `display_size`: that one is
# paid for once per game in the library, and raising it to this would double
# the memory and drawing cost of the whole grid to sharpen one picture. Only
# the cover on screen right now is decoded at this size — see
# `GameCover.add_details_picture`.
details_size = (420, 630)

# pylint: disable=invalid-name
sessao = None  # o ModeloDaSessao (plano 5)
conquistas = None  # o ConquistasDoJogo (plano 6)
# O `Aplicativo` do app Qt (importando, avisos); None nos testes que não o criam.
aplicativo = None
preferencias = None  # o Preferencias (plano 7)
edicao = None  # o ModeloDaEdicao (plano 8a)
importer = None
import_time = None
store = None
log_files = []
