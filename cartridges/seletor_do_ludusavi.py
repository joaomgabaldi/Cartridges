# seletor_do_ludusavi.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Escolher, na lista de jogos do Ludusavi, o jogo cujos saves entram no backup.

O nome certo só quem conhece o jogo sabe dizer; o app apenas oferece a lista do
`manifest.yaml` (dezenas de milhares de nomes), lida fora da thread da tela e
filtrada enquanto se digita.
"""

import logging
import threading
from typing import Any, Callable

from gi.repository import Adw, Gtk, Pango

from cartridges.saves import ludusavi
from cartridges.saves.backup_de_saves import _pasta_config
from cartridges.utils.na_tela import entregar_na_tela


class SeletorDoLudusavi(Adw.Dialog):
    __gtype_name__ = "SeletorDoLudusavi"

    def __init__(self, atual: str, ao_escolher: Callable[[str], None]) -> None:
        super().__init__(title=_("Jogo no Ludusavi"), content_width=480, content_height=560)
        self.atual = atual
        self.ao_escolher = ao_escolher
        self._fechada = False

        self.campo_busca = Gtk.SearchEntry(
            placeholder_text=_("Buscar jogo"), margin_start=12, margin_end=12, margin_top=6, margin_bottom=6
        )

        self.linha_nenhum = Adw.ActionRow(title=_("Nenhum (desliga o backup)"), activatable=True)
        self.caixa_nenhum = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, margin_start=12, margin_end=12)
        self.caixa_nenhum.add_css_class("boxed-list")
        self.caixa_nenhum.append(self.linha_nenhum)
        self.caixa_nenhum.connect("row-activated", lambda *_: self._escolher(""))

        self.nomes = Gtk.StringList()
        self.filtro = Gtk.StringFilter(
            ignore_case=True,
            match_mode=Gtk.StringFilterMatchMode.SUBSTRING,
            expression=Gtk.PropertyExpression.new(Gtk.StringObject, None, "string"),
        )
        self.filtrado = Gtk.FilterListModel(model=self.nomes, filter=self.filtro)
        self.selecao = Gtk.SingleSelection(model=self.filtrado, autoselect=False, can_unselect=True)
        fabrica = Gtk.SignalListItemFactory()
        fabrica.connect("setup", self._montar_item)
        fabrica.connect("bind", self._ligar_item)
        self.lista = Gtk.ListView(model=self.selecao, factory=fabrica, single_click_activate=True)
        self.lista.connect("activate", self._ao_ativar)
        rolagem = Gtk.ScrolledWindow(child=self.lista, vexpand=True)

        self.pagina_erro = Adw.StatusPage(icon_name="dialog-warning-symbolic")
        self.pilha = Gtk.Stack()
        self.pilha.add_named(Adw.Spinner(halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER), "carregando")
        self.pilha.add_named(rolagem, "lista")
        self.pilha.add_named(self.pagina_erro, "erro")

        caixa = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        caixa.append(self.campo_busca)
        caixa.append(self.caixa_nenhum)
        caixa.append(self.pilha)
        vista = Adw.ToolbarView(content=caixa)
        vista.add_top_bar(Adw.HeaderBar())
        self.set_child(vista)

        self.campo_busca.connect("search-changed", self._ao_buscar)
        self.connect("closed", self._ao_fechar)
        self.pilha.set_visible_child_name("carregando")
        threading.Thread(target=self._ler, args=(_pasta_config(),), daemon=True).start()

    @staticmethod
    def _montar_item(_fabrica: Any, item: Gtk.ListItem) -> None:
        item.set_child(
            Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END, margin_top=8, margin_bottom=8, margin_start=12, margin_end=12)
        )

    @staticmethod
    def _ligar_item(_fabrica: Any, item: Gtk.ListItem) -> None:
        item.get_child().set_label(item.get_item().get_string())

    def _ler(self, pasta: Any) -> None:
        try:
            nomes = ludusavi.nomes_do_manifesto(pasta)
        except (OSError, ValueError) as erro:
            logging.warning("Não foi possível ler a lista de jogos do Ludusavi: %s", erro)
            entregar_na_tela(self._mostrar_erro)
            return
        entregar_na_tela(self._mostrar, nomes)

    def _mostrar_erro(self) -> bool:
        if not self._fechada:
            self.pagina_erro.set_title(_("Não foi possível ler a lista de jogos do Ludusavi."))
            self.pilha.set_visible_child_name("erro")
        return False

    def _mostrar(self, nomes: list[str]) -> bool:
        if self._fechada:
            return False
        self.nomes.splice(0, 0, nomes)
        self.pilha.set_visible_child_name("lista")
        if self.atual in nomes:
            posicao = nomes.index(self.atual)
            self.selecao.set_selected(posicao)
            self.lista.scroll_to(posicao, Gtk.ListScrollFlags.NONE, None)
        return False

    def _ao_buscar(self, *_args: Any) -> None:
        self.filtro.set_search(self.campo_busca.get_text().strip())

    def _ao_ativar(self, _lista: Gtk.ListView, posicao: int) -> None:
        if (item := self.filtrado.get_item(posicao)) is not None:
            self._escolher(item.get_string())

    def _escolher(self, nome: str) -> None:
        if self._fechada:
            return
        self.ao_escolher(nome)
        self.close()

    def _ao_fechar(self, *_args: Any) -> None:
        self._fechada = True
