# botao_tarefas.py
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

"""O botão do canto inferior esquerdo que abre as tarefas em andamento.

Não fica na tela: entra deslizando quando uma tarefa começa, recua depois de
3 s e volta quando o mouse passa pelo canto. Escondido, o botão não recebe
nada do mouse: quem vigia o canto é um controlador no overlay da janela, que
enxerga o movimento sem ficar na frente das capas. Nunca aparece fora das duas
bibliotecas, com uma janela aberta por cima ou durante uma sessão de jogo.
"""

from typing import Any

from gi.repository import GLib, Gtk

from cartridges.tarefas_dialog import TarefasDialog
from cartridges.utils import tarefas

_ENTRADA_MS = 3000
_SAIDA_MS = 1000
_CANTO = 72  # lado, em px, do canto que faz o botão voltar


def pode_mostrar(win: Any) -> bool:
    return (
        tarefas.lista.get_n_items() > 0
        and win.navigation_view.get_visible_page()
        in (win.library_page, win.zerados_library_page)
        and win.get_visible_dialog() is None
        and win.session_game is None
    )


class BotaoTarefas(Gtk.Box):
    """O canto sensível ao mouse, com o botão dentro de um revealer."""

    def __init__(self, win: Any) -> None:
        super().__init__(halign=Gtk.Align.START, valign=Gtk.Align.END)
        self.win = win
        self._recolher_id = 0
        self._no_canto = False
        self.set_size_request(_CANTO, _CANTO)
        self.set_can_target(False)

        self.botao = Gtk.Button(
            icon_name="view-refresh-symbolic",
            tooltip_text=_("Tarefas em andamento"),
            valign=Gtk.Align.END,
            margin_start=12,
            margin_bottom=12,
        )
        self.botao.add_css_class("circular")
        self.botao.add_css_class("osd")
        self.botao.add_css_class("botao-tarefas")
        self.botao.connect("clicked", self._abrir)

        self.revealer = Gtk.Revealer(
            transition_type=Gtk.RevealerTransitionType.SLIDE_RIGHT,
            valign=Gtk.Align.END,
        )
        self.revealer.set_child(self.botao)
        # O alvo do mouse e o giro seguem o que está à vista, não o que se pediu.
        self.revealer.connect("notify::reveal-child", self.reavaliar)
        self.revealer.connect("notify::child-revealed", self.reavaliar)
        self.append(self.revealer)

        # No overlay, e não neste Box: um Box alvejável ali na frente tiraria
        # os cliques e a roda do mouse das capas que ficam debaixo do canto.
        movimento = Gtk.EventControllerMotion(
            propagation_phase=Gtk.PropagationPhase.CAPTURE
        )
        movimento.connect("motion", self._ao_mover)
        movimento.connect("leave", self._ao_deixar)
        win.session_overlay.add_controller(movimento)

        # O temporizador do GLib segura o botão (e, por ele, a janela) até
        # disparar: destruída a janela, o recuo agendado não deve sobreviver.
        win.connect("destroy", self._cancelar_recolher)

    # -- quando pode ----------------------------------------------------------

    def reavaliar(self, *_args: Any) -> None:
        pode = pode_mostrar(self.win)
        a_vista = self.revealer.get_reveal_child() or self.revealer.get_child_revealed()
        self.set_can_target(pode and a_vista)
        if not a_vista:
            self.botao.remove_css_class("girando")
        if not pode:
            # Na sessão o botão está acima do bloqueador: some sem deslizar.
            self._esconder(animado=self.win.session_game is None)

    def ao_mudar_lista(
        self, _lista: Any, _posicao: int, _removidos: int, adicionados: int
    ) -> None:
        self.reavaliar()
        if adicionados and pode_mostrar(self.win):
            self._mostrar()
            self._agendar_recolher(_ENTRADA_MS)

    # -- mouse ----------------------------------------------------------------

    def _ao_mover(self, _controlador: Any, x: float, y: float) -> None:
        altura = self.win.session_overlay.get_height()
        dentro = x < _CANTO and y > altura - _CANTO
        if dentro and not self._no_canto:
            self._no_canto = True
            self._ao_entrar()
        elif not dentro and self._no_canto:
            self._no_canto = False
            self._ao_sair()

    def _ao_deixar(self, *_args: Any) -> None:
        if self._no_canto:
            self._no_canto = False
            self._ao_sair()

    def _ao_entrar(self, *_args: Any) -> None:
        if pode_mostrar(self.win):
            self._mostrar()

    def _ao_sair(self, *_args: Any) -> None:
        self._agendar_recolher(_SAIDA_MS)

    # -- mostrar e esconder ---------------------------------------------------

    def _mostrar(self) -> None:
        self._cancelar_recolher()
        self.botao.add_css_class("girando")
        self.revealer.set_reveal_child(True)

    def _esconder(self, animado: bool = True) -> None:
        self._cancelar_recolher()
        if animado:
            self.revealer.set_reveal_child(False)
            return
        tipo = self.revealer.get_transition_type()
        self.revealer.set_transition_type(Gtk.RevealerTransitionType.NONE)
        self.revealer.set_reveal_child(False)
        self.revealer.set_transition_type(tipo)

    def _agendar_recolher(self, espera_ms: int) -> None:
        self._cancelar_recolher()
        self._recolher_id = GLib.timeout_add(espera_ms, self._recolher)

    def _recolher(self) -> bool:
        self._recolher_id = 0
        # Com o mouse no canto, a entrada automática não tira o botão de baixo
        # dele; sair do canto agenda a saída de novo.
        if not self._no_canto:
            self.revealer.set_reveal_child(False)
        return GLib.SOURCE_REMOVE

    def _cancelar_recolher(self, *_args: Any) -> None:
        if self._recolher_id:
            GLib.source_remove(self._recolher_id)
            self._recolher_id = 0

    def _abrir(self, *_args: Any) -> None:
        self._esconder()
        TarefasDialog().present(self.win)
