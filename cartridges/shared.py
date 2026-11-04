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
# Versão do spec do game_id.json. Deliberadamente NÃO incrementada para os campos do HowLongToBeat: são adições
# anuláveis que uma versão antiga ignora, e um incremento faria `Store.add_game` rejeitar todo arquivo como "de uma
# versão mais nova" e esconder a biblioteca inteira num downgrade.
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
# Logos horizontais oficiais do cabeçalho dos detalhes. Separados das capas: o logo é decorativo e sempre pode ser
# baixado de novo, então apagar a pasta só custa um download.
logos_dir = app_dir / "logos"
# A arte dos monitores além do principal durante a sessão: a imagem de partida (uma por jogo) e o sidecar que diz se foi
# escolhida à mão e em que faixa cortá-la por orientação. Apagar a pasta devolve tudo à escolha automática.
wallpapers_dir = app_dir / "wallpapers"

# As fitas de LED da sessão: um sidecar por jogo com cor e brilho, e o arquivo das fitas configuradas, que carrega as
# chaves locais dos módulos (por isso não mora no GSettings).
fitas_dir = app_dir / "fitas"
fitas_arquivo = app_dir / "fitas.json"

# As conquistas desbloqueadas de cada jogo, uma por arquivo, com o nome do id
# (`conquistas/historico.py`). Entra no backup.
conquistas_dir = app_dir / "conquistas"

conquistas_cache_dir = app_dir / "cache" / "conquistas"

# Cópias reduzidas das capas animadas, uma por tamanho de exibição
# (`utils/copias_animadas.py`). Poderiam ser refeitas da capa, mas entram no
# backup: levá-las prontas sai mais barato do que regerá-las ao restaurar.
capas_animadas_dir = app_dir / "cache" / "capas_animadas"

# Contas de lojas (Microsoft/Xbox, Epic e EA), com a chave de
# renovação cifrada pelo DPAPI: presa a este PC e a este usuário do Windows,
# então fica fora do backup (`utils/backup.py`).
contas_dir = app_dir / "contas"

# Conta de nuvem da Tuya do assistente das fitas, criptografada com o DPAPI (ver `utils/tuya_conta.py`). Vai no backup,
# mas só decifra no mesmo PC e na mesma conta do Windows; em outro, o assistente pede os códigos de novo.
tuya_conta_arquivo = app_dir / "tuya_conta.json"

# Deliberadamente NÃO `GLib.get_user_cache_dir()`: no Windows resolve para CSIDL_INTERNET_CACHE
# (`AppData\Local\Microsoft\Windows\INetCache`), pasta que a Limpeza de Disco e o Sensor de Armazenamento esvaziam,
# levando o log da execução que deu errado. `AppData\Local\<app>` é o local convencional e mantém tudo sob uma raiz.
log_dir = app_dir / "logs"

# Os mestres das capas guardadas ficam sempre em alta resolução (600x900, o tamanho nativo do SteamGridDB/Steam); o
# tamanho de exibição deriva da escala do monitor.
image_size = (600, 900)

# Padrões sempre presentes. O `app.py` refaz `scale_factor`, `display_size` e
# `details_size` a partir dos monitores do Qt, depois de criar a QGuiApplication.
scale_factor = 1
display_size = (200, 300)

# A página de detalhes desenha a capa em 420x630, não nos 200x300 da grade, e uma textura decodificada em `display_size`
# ficaria esticada. Segundo número de propósito: elevar `display_size` dobraria o custo de memória e desenho da grade
# inteira para dar nitidez a uma imagem; só a capa na tela é decodificada neste tamanho (ver
# `GameCover.add_details_picture`).
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
