# varredura.py
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

"""A varredura única dos .ini dos jogos já existentes e a reaplicação em massa do padrão. Ambas rodam numa thread."""

import logging
import threading
from typing import Iterable, Optional

from cartridges import shared
from cartridges.emuladores import aplicacao
from cartridges.jogo import Jogo
from cartridges.modelos import tarefas
from cartridges.utils.thread_principal import na_thread_principal

_cancelar_reaplicacao: Optional[threading.Event] = None


def _da_biblioteca(jogo: Jogo) -> bool:
    """Ainda é este exato jogo na store (uma exclusão ou reimportação durante a varredura faria o `save()` desfazê-la)."""
    return shared.store is not None and shared.store.get(jogo.game_id) is jogo


def _buscar_idiomas(jogo: Jogo) -> None:
    from cartridges.utils.zerado_manual import helper_da_steam  # noqa: PLC0415

    try:
        dados = helper_da_steam().get_api_data(str(jogo.steam_appid), skip_genre=True)
    except Exception as erro:  # noqa: BLE001  (rede, não encontrado: a próxima atualização tenta de novo)
        logging.debug("Idiomas da Steam indisponíveis para %s: %s", jogo.name, erro)
        return
    jogo.idiomas_steam = dados.get("idiomas_steam")


def _varrer_um(jogo: Jogo) -> bool:
    """Devolve se o AppID do jogo mudou."""
    antes = (jogo.inis, jogo.steam_appid, jogo.idiomas_steam)
    try:
        mudou = aplicacao.adotar_appid(jogo, aplicacao.atualizar_inis(jogo, aplicacao.executaveis_dos_outros(jogo)))
        if jogo.inis and jogo.steam_appid and jogo.idiomas_steam is None:
            _buscar_idiomas(jogo)
        aplicacao.aplicar_no_jogo(jogo)
    except OSError as erro:
        logging.warning("Falha ao varrer os .ini de %s: %s", jogo.name, erro)
        return False
    if (jogo.inis, jogo.steam_appid, jogo.idiomas_steam) != antes and _da_biblioteca(jogo):
        jogo.save()
    return mudou


def _rodar_varredura(jogos: list[Jogo]) -> None:
    tarefa = tarefas.comecar("Procurando os arquivos de configuração dos jogos", len(jogos))
    mudados: list[Jogo] = []
    try:
        for feitos, jogo in enumerate(jogos, 1):
            if _varrer_um(jogo):
                mudados.append(jogo)
            tarefa.atualizar(feitos)
    finally:
        tarefa.terminar()
        # Marcada mesmo com falha: tentar de novo a cada abertura prenderia o app numa varredura que não termina.
        shared.schema.set_boolean("inis-varridos", True)
    if mudados:
        from cartridges.metadata_refresh import get_metadata_refresh  # noqa: PLC0415
        from cartridges.utils import ligacao_zerado  # noqa: PLC0415

        # O Steam do refresh não veria mudança (o AppID já foi trocado): a ligação com o zerado é pedida aqui.
        for jogo in mudados:
            ligacao_zerado.agendar(jogo)
        na_thread_principal(get_metadata_refresh().start, mudados)


def _da_lista(jogos: Iterable[Jogo]) -> list[Jogo]:
    return [j for j in jogos if not (j.removed or j.blacklisted)]


def varrer(jogos: list[Jogo]) -> threading.Thread:
    """Procura os .ini de cada jogo da biblioteca, adota o AppID deles e aplica o padrão. Devolve a thread, já iniciada."""
    thread = threading.Thread(target=_rodar_varredura, args=(_da_lista(jogos),), name="varredura-dos-inis", daemon=True)
    thread.start()
    return thread


def _reaplicar_um(jogo: Jogo) -> None:
    try:
        aplicacao.aplicar_no_jogo(jogo)
    except OSError as erro:
        logging.warning("Falha ao gravar os .ini de %s: %s", jogo.name, erro)


def _rodar_reaplicacao(jogos: list[Jogo], cancelar: threading.Event) -> None:
    tarefa = tarefas.comecar("Aplicando o idioma e o nome do jogador", len(jogos))
    try:
        for feitos, jogo in enumerate(jogos, 1):
            if cancelar.is_set():
                return
            _reaplicar_um(jogo)
            tarefa.atualizar(feitos)
    finally:
        tarefa.terminar()


def reaplicar(jogos: Iterable[Jogo], campos: Iterable[str] = ("nome", "idioma")) -> threading.Thread:
    """Regrava o padrão nos jogos com .ini que não têm valor próprio em nenhum dos `campos` que mudaram.

    Uma nova chamada cancela a anterior em andamento. Só a thread principal chama (o cancelamento não tem trava).
    """
    global _cancelar_reaplicacao  # noqa: PLW0603
    propriedades = {"nome": "nome_proprio", "idioma": "idioma_proprio"}
    campos = [propriedades[c] for c in campos]
    alvos = [j for j in _da_lista(jogos) if j.inis and any(not getattr(j, c) for c in campos)]
    if _cancelar_reaplicacao is not None:
        _cancelar_reaplicacao.set()
    _cancelar_reaplicacao = cancelar = threading.Event()
    thread = threading.Thread(target=_rodar_reaplicacao, args=(alvos, cancelar), name="reaplicacao-dos-inis", daemon=True)
    thread.start()
    return thread


def _jogos_da_biblioteca() -> list[Jogo]:
    return list(shared.store) if shared.store is not None else []


def ligar_ao_app() -> None:
    """Chamada na thread principal depois da carga: a varredura única e a reaplicação quando o padrão muda."""
    from PySide6.QtCore import QTimer  # noqa: PLC0415

    mudados: set[str] = set()
    espera = QTimer()
    espera.setSingleShot(True)
    espera.setInterval(800)  # a linha de texto avisa a cada tecla

    def disparar() -> None:
        campos, _ = list(mudados), mudados.clear()
        reaplicar(_jogos_da_biblioteca(), campos)

    espera.timeout.connect(disparar)

    def mudou(campo: str) -> None:
        mudados.add(campo)
        espera.start()  # reinicia a contagem

    shared.schema.connect("changed::nome-do-jogador", lambda *_: mudou("nome"))
    shared.schema.connect("changed::idioma-do-jogador", lambda *_: mudou("idioma"))
    ligar_ao_app.espera = espera  # o QTimer vive enquanto o app
    if not shared.schema.get_boolean("inis-varridos"):
        varrer(_jogos_da_biblioteca())
