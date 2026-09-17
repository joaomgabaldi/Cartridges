# fita_wizard.py
#
# Copyright 2026 kramo
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

"""Onde as fitas de LED são configuradas, uma vez.

O módulo Tuya só aceita comandos de quem tem a chave local dele, e essa chave
não está no app Smart Life — ela sai da conta de desenvolvedor da Tuya, pela
nuvem. Este assistente faz essa viagem uma vez: pede as credenciais da conta,
lista os dispositivos e grava a chave dos que o usuário apontar como fitas.

A API Secret não é gravada. Ela vive nesta janela e morre com ela: depois da
busca, o que serve para acender uma fita é a chave local, e é só ela que fica.
"""

import logging
import threading
from typing import Any

from gi.repository import Adw, GLib, Gtk

from cartridges import shared
from cartridges.utils.session_fita import Fita, fitas, gravar_fitas

# As regiões que a Tuya oferece, na mesma ordem da lista do `.blp`. As duas
# listas precisam andar juntas: o índice escolhido na tela é o índice aqui.
REGIOES = ("us", "eu", "cn", "in")


def fitas_da_nuvem(resposta: Any) -> list[Fita]:
    """Converte a lista que a nuvem devolve em fitas.

    Dispositivo sem chave local fica de fora: sem ela não há conversa possível.
    Sem IP, entra com o campo vazio — a nuvem devolve o IP público do roteador,
    que não serve para nada aqui, e a descoberta por broadcast acha o IP da
    fita na hora de acender.

    Aceita qualquer coisa como entrada de propósito: quando a busca falha, a
    ``tinytuya`` devolve um dicionário de erro no lugar da lista, e isso não
    pode virar exceção dentro da thread.
    """
    if not isinstance(resposta, list):
        return []

    encontradas = []
    for item in resposta:
        if not isinstance(item, dict):
            continue
        chave = str(item.get("key") or "")
        identificador = str(item.get("id") or "")
        if not chave or not identificador:
            continue
        encontradas.append(
            Fita(
                str(item.get("name") or identificador),
                identificador,
                str(item.get("ip") or ""),
                chave,
                str(item.get("version") or "3.3"),
            )
        )
    return encontradas


@Gtk.Template(resource_path=shared.PREFIX + "/gtk/fita-wizard.ui")
class FitaWizard(Adw.Dialog):
    __gtype_name__ = "FitaWizard"

    stack: Adw.ViewStack = Gtk.Template.Child()
    api_key_row: Adw.EntryRow = Gtk.Template.Child()
    api_secret_row: Adw.PasswordEntryRow = Gtk.Template.Child()
    regiao_row: Adw.ComboRow = Gtk.Template.Child()
    buscar_button: Gtk.Button = Gtk.Template.Child()
    dispositivos_group: Adw.PreferencesGroup = Gtk.Template.Child()
    salvar_button: Gtk.Button = Gtk.Template.Child()

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._linhas: list[tuple[Adw.SwitchRow, Fita]] = []
        self.buscar_button.connect("clicked", self.buscar)
        self.salvar_button.connect("clicked", self.salvar)

    def buscar(self, *_args: Any) -> None:
        """Vai à nuvem numa thread; a Secret não sai desta chamada."""
        chave = self.api_key_row.get_text().strip()
        segredo = self.api_secret_row.get_text().strip()
        escolhida = self.regiao_row.get_selected()
        regiao = REGIOES[escolhida] if escolhida < len(REGIOES) else REGIOES[0]
        if not chave or not segredo:
            return

        self.stack.set_visible_child_name("buscando")
        threading.Thread(
            target=self._buscar_na_nuvem, args=(chave, segredo, regiao), daemon=True
        ).start()

    def _buscar_na_nuvem(self, chave: str, segredo: str, regiao: str) -> None:
        import tinytuya  # noqa: PLC0415

        try:
            nuvem = tinytuya.Cloud(apiRegion=regiao, apiKey=chave, apiSecret=segredo)
            encontrados = fitas_da_nuvem(nuvem.getdevices())
        except Exception as erro:  # a tinytuya levanta de tudo aqui também
            logging.warning("Busca na nuvem da Tuya falhou: %s", erro)
            encontrados = []
        GLib.idle_add(self._mostrar, encontrados)

    def _mostrar(self, encontrados: list[Fita]) -> None:
        for linha, _fita in self._linhas:
            self.dispositivos_group.remove(linha)
        self._linhas = []

        if not encontrados:
            self.dispositivos_group.set_description(
                _("Nada encontrado. Confira as credenciais e a região.")
            )
        else:
            self.dispositivos_group.set_description(None)

        ja_configuradas = {fita.id for fita in fitas()}
        for fita in encontrados:
            linha = Adw.SwitchRow(title=fita.nome, subtitle=fita.ip or fita.id)
            linha.set_active(fita.id in ja_configuradas)
            self.dispositivos_group.add(linha)
            self._linhas.append((linha, fita))

        self.stack.set_visible_child_name("dispositivos")

    def salvar(self, *_args: Any) -> None:
        gravar_fitas([fita for linha, fita in self._linhas if linha.get_active()])
        self.close()
