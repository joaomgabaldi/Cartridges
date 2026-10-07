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
AdwEntryRow), caixas de texto (GtkTextView) e rótulos selecionáveis (GtkLabel,
como os do Aviso legal no Sobre) iniciam um arrastar-e-soltar quando o clique
cai dentro da seleção e o mouse se move. No Windows, o GTK não remove a imagem
do texto arrastado ao soltar: ela fica parada na tela, por cima de tudo. Os
três começam o arraste por conta própria; o que usa GtkDragSource (amostras de
cor, botão de link) encerra o arraste direito e não deixa nada na tela.

O arraste só começa se o clique cair dentro de uma seleção. Um gesto na fase
de captura roda antes do gesto do próprio campo e desfaz a seleção no clique;
o campo então começa uma seleção nova a partir dali, como em qualquer outro
ponto. O gesto vai na janela, em cada caixa de diálogo e em cada popover
dentro delas (o das anotações, o seletor de cor com o campo da cor em
hexadecimal): o clique num diálogo ou popover para nele e não chega à janela.
Duplo e triplo clique continuam selecionando palavra e linha, e o
Shift+clique fica intocado para estender a seleção.
"""

from gi.repository import Gdk, Gtk


_LIGADO = "_cartridges_sem_arrastar_texto"


def sem_arrastar_texto(raiz: Gtk.Widget) -> None:
    """Vale para todo campo de texto dentro de `raiz` e dos popovers nela.

    Campos criados depois também valem; popovers criados depois, não.
    """
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
    _popovers_dentro(raiz)


def _popovers_dentro(widget: Gtk.Widget) -> None:
    # O popover de um botão é filho dele na árvore de widgets.
    filho = widget.get_first_child()
    while filho is not None:
        if isinstance(filho, Gtk.Popover):
            sem_arrastar_texto(filho)
        else:
            _popovers_dentro(filho)
        filho = filho.get_next_sibling()


def _desfazer_selecao(
    clique: Gtk.GestureClick, _n_press: int, x: float, y: float
) -> None:
    if clique.get_current_event_state() & Gdk.ModifierType.SHIFT_MASK:
        return

    alvo = clique.get_widget().pick(x, y, Gtk.PickFlags.DEFAULT)
    while alvo is not None and not (
        isinstance(alvo, (Gtk.Text, Gtk.TextView))
        or (isinstance(alvo, Gtk.Label) and alvo.get_selectable())
    ):
        alvo = alvo.get_parent()

    if isinstance(alvo, Gtk.Label):
        alvo.select_region(0, 0)
    elif isinstance(alvo, Gtk.Text):
        posicao = alvo.get_position()
        alvo.select_region(posicao, posicao)
    elif isinstance(alvo, Gtk.TextView):
        buffer = alvo.get_buffer()
        buffer.place_cursor(buffer.get_iter_at_mark(buffer.get_insert()))
