# sem_arrastar_texto.py
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

"""Impede que texto selecionado seja arrastado.

Campos de texto (GtkText, dentro de todo GtkEntry, GtkSearchEntry e
AdwEntryRow) e caixas de texto (GtkTextView) iniciam um arrastar-e-soltar
quando o clique cai dentro da seleção e o mouse se move. No Windows, o GTK não
remove a imagem do texto arrastado ao soltar: ela fica parada na tela, por
cima de tudo.

O arraste só começa se o clique cair dentro de uma seleção. Um gesto na fase
de captura roda antes do gesto do próprio campo e desfaz a seleção no clique;
o campo então começa uma seleção nova a partir dali, como em qualquer outro
ponto. O gesto vai na janela, em cada caixa de diálogo e em cada popover: o
clique num diálogo ou popover para nele e não chega à janela.
Duplo e triplo clique continuam selecionando palavra e linha, e o
Shift+clique fica intocado para estender a seleção.
"""

from gi.repository import Gdk, Gtk


_LIGADO = "_cartridges_sem_arrastar_texto"


def sem_arrastar_texto(raiz: Gtk.Widget) -> None:
    """Vale para todo campo de texto dentro de `raiz`, inclusive os criados depois."""
    # Uma caixa de diálogo volta a ser a visível sempre que outra aberta por
    # cima dela fecha, e um gesto basta.
    if getattr(raiz, _LIGADO, False):
        return
    setattr(raiz, _LIGADO, True)

    clique = Gtk.GestureClick(
        button=Gdk.BUTTON_PRIMARY, propagation_phase=Gtk.PropagationPhase.CAPTURE
    )
    clique.connect("pressed", _desfazer_selecao)
    raiz.add_controller(clique)


def _desfazer_selecao(
    clique: Gtk.GestureClick, _n_press: int, x: float, y: float
) -> None:
    if clique.get_current_event_state() & Gdk.ModifierType.SHIFT_MASK:
        return

    alvo = clique.get_widget().pick(x, y, Gtk.PickFlags.DEFAULT)
    while alvo is not None and not isinstance(alvo, (Gtk.Text, Gtk.TextView)):
        alvo = alvo.get_parent()

    if isinstance(alvo, Gtk.Text):
        posicao = alvo.get_position()
        alvo.select_region(posicao, posicao)
    elif isinstance(alvo, Gtk.TextView):
        buffer = alvo.get_buffer()
        buffer.place_cursor(buffer.get_iter_at_mark(buffer.get_insert()))
