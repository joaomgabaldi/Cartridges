# aplicacao.py
#
# Copyright 2026 joaomgabaldi
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

"""Aplicar o idioma e o nome do jogador aos .ini de um jogo. Toca o disco: rodar numa thread."""

import logging
from pathlib import Path
from typing import Iterable, Optional

from cartridges import shared
from cartridges.emuladores import busca, ini
from cartridges.emuladores.idiomas import IDIOMAS


def valores_para(jogo) -> tuple[Optional[str], Optional[str]]:
    """(nome, idioma) a gravar; `None` em cada um que não deve ser tocado."""
    nome = jogo.nome_proprio or shared.schema.get_string("nome-do-jogador")
    nome = nome if nome and ini.nome_valido(nome) else None
    idioma = jogo.idioma_proprio or shared.schema.get_string("idioma-do-jogador")
    if idioma not in IDIOMAS:
        idioma = None
    elif jogo.steam_appid and (jogo.idiomas_steam is None or idioma not in jogo.idiomas_steam):
        idioma = None  # a Steam não confirma que o jogo tem esse idioma
    return nome, idioma


def _modelo_com_marcador(caminho: Path) -> bool:
    """Modelo do language.changer cujo idioma é um marcador (`&LANG&`): só o nome pode mudar."""
    if caminho.name.casefold() in ini.FORMATOS:
        return False
    return "&" in (ini.ler(caminho, "steam_emu.ini").idioma or "")


def aplicar_no_jogo(jogo) -> bool:
    """`False` quando os .ini não foram procurados ou algum sumiu ("faltando"); nada é gravado nesse caso."""
    if jogo.inis is None:
        return False
    caminhos = [Path(c) for c in jogo.inis]
    if not all(c.exists() for c in caminhos):
        return False
    nome, idioma = valores_para(jogo)
    if nome is None and idioma is None:
        return True
    for caminho in caminhos:
        try:
            ini.aplicar(caminho, nome, None if _modelo_com_marcador(caminho) else idioma, busca.formato_de(caminho))
        except OSError as erro:  # somente leitura ou aberto pelo jogo: não derruba o play
            logging.warning("Não foi possível gravar `%s`: %s", caminho, erro)
    return True


def executaveis_dos_outros(jogo) -> list[str]:
    """Os executáveis dos outros jogos da biblioteca: a busca não entra em pasta que abriga mais de um jogo."""
    if shared.store is None:
        return []
    return [o.executable for o in shared.store if o.game_id != jogo.game_id and not o.removed and o.executable]


def atualizar_inis(jogo, executaveis_dos_outros: Iterable[str]) -> Optional[str]:
    """Procura de novo os .ini do jogo, grava `jogo.inis` e devolve o AppID que eles dizem (ou None)."""
    raiz = busca.raiz_do_jogo(jogo.executable, executaveis_dos_outros)
    achados = busca.procurar(raiz) if raiz else []
    jogo.inis = [str(c) for c in achados]
    return busca.appid_dos(achados)


def adotar_appid(jogo, appid: Optional[str]) -> bool:
    if not appid or jogo.appid_manual or appid == jogo.steam_appid:
        return False
    jogo.steam_appid = appid
    jogo.idiomas_steam = None  # eram os do AppID anterior
    jogo.ludusavi_nome = ""
    jogo.saves_local_desconhecido_avisado = False
    return True
