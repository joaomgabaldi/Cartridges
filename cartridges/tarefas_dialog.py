# tarefas_dialog.py
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

"""A janela "Tarefas em andamento": um bloco por tarefa, ao vivo.

Só lê o quadro (`utils/tarefas.py`). Fica aberta quando a última tarefa
termina, com o aviso de que não há nada rodando: fechar sozinha poderia
sumir com ela debaixo do clique do usuário.
"""

from typing import Any

from gi.repository import Adw, Gtk

from cartridges.utils import tarefas


class TarefasDialog(Adw.Dialog):
    def __init__(self) -> None:
        super().__init__(title=_("Tarefas em andamento"), content_width=360)

        self.caixa = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        self.vazio = Gtk.Label(label=_("Nenhuma tarefa em andamento"))
        self.vazio.add_css_class("dim-label")

        conteudo = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            margin_top=12,
            margin_bottom=24,
            margin_start=24,
            margin_end=24,
        )
        conteudo.append(self.caixa)
        conteudo.append(self.vazio)

        barra = Adw.ToolbarView()
        barra.add_top_bar(Adw.HeaderBar())
        barra.set_content(conteudo)
        self.set_child(barra)

        # (objeto, id) de cada ligação: o quadro e as tarefas vivem mais que a
        # janela, e uma ligação esquecida seguraria os widgets depois de fechada.
        self._ligacoes: list[tuple[Any, int]] = []
        self._id_lista = tarefas.lista.connect("items-changed", self._redesenhar)
        self.connect("closed", self._desligar)
        self._redesenhar()

    def _redesenhar(self, *_args: Any) -> None:
        self._desligar_tarefas()
        while (filho := self.caixa.get_first_child()) is not None:
            self.caixa.remove(filho)

        for posicao in range(tarefas.lista.get_n_items()):
            self.caixa.append(self._bloco(tarefas.lista.get_item(posicao)))
        self.vazio.set_visible(tarefas.lista.get_n_items() == 0)

    def _bloco(self, tarefa: tarefas.Tarefa) -> Gtk.Widget:
        bloco = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        nome = Gtk.Label(label=tarefa.nome, xalign=0)
        nome.add_css_class("heading")
        contagem = Gtk.Label(xalign=0)
        contagem.add_css_class("dim-label")
        barra = Gtk.ProgressBar()
        bloco.append(nome)
        bloco.append(contagem)
        bloco.append(barra)

        def mostrar(*_args: Any) -> None:
            # As variáveis são quantos itens foram feitos e quantos há no total
            contagem.set_label(_("{} de {}").format(tarefa.feitos, tarefa.total))
            barra.set_fraction(tarefa.feitos / tarefa.total if tarefa.total else 0)

        for sinal in ("notify::feitos", "notify::total"):
            self._ligacoes.append((tarefa, tarefa.connect(sinal, mostrar)))
        mostrar()
        return bloco

    def _desligar_tarefas(self) -> None:
        for objeto, id_ in self._ligacoes:
            objeto.disconnect(id_)
        self._ligacoes.clear()

    def _desligar(self, *_args: Any) -> None:
        self._desligar_tarefas()
        tarefas.lista.disconnect(self._id_lista)
