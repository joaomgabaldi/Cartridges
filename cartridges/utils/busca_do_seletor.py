# busca_do_seletor.py
#
# Copyright 2026 joaomgabaldi
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O que os seletores com busca (logo, capa, papel de parede, Steam) fazem igual:
esperar a pessoa parar de digitar e mostrar a página vazia com o motivo.

Quem herda tem ``search_entry``, ``status_page``, ``stack`` (com a página
``"empty"``), ``search()`` e os atributos ``_debounce_id``, ``_last_query`` e
``_generation``. Vem antes de ``Adw.Dialog`` na lista de bases.
"""

from typing import Any, Optional

from gi.repository import GLib


class BuscaDoSeletor:
    # Quanto esperar depois da última tecla antes de buscar.
    atraso_da_busca_ms = 500

    def _on_search_changed(self, *_args: Any) -> None:
        if self._debounce_id:
            GLib.source_remove(self._debounce_id)
        self._debounce_id = GLib.timeout_add(self.atraso_da_busca_ms, self._debounce_fire)

    def _debounce_fire(self) -> bool:
        self._debounce_id = 0
        # GtkSearchEntry emite um search-changed atrasado para o set_text
        # programático do __init__, depois do connect: sem este guard, abrir o
        # diálogo buscava duas vezes a mesma coisa — API e downloads em dobro,
        # com a segunda passada varrendo os previews da primeira. Enter no
        # campo continua repetindo a busca (caminho do "activate", não daqui).
        if self.search_entry.get_text().strip() == self._last_query:
            return False
        self.search()
        return False

    def _show_empty(self, titulo: str, descricao: str = "", generation: Optional[int] = None) -> bool:
        if generation is not None and generation != self._generation:
            return False
        # Título e descrição juntos: com o título fixo, uma busca que falhou
        # dizia "Nenhum … encontrado".
        self.status_page.set_title(titulo)
        self.status_page.set_description(descricao)
        self.stack.set_visible_child_name("empty")
        return False
