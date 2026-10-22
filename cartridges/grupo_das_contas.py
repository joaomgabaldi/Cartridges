# grupo_das_contas.py
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

"""O grupo com as contas Microsoft, Epic e EA, usado nas Preferências e no
assistente de primeira abertura.

Sem template: as três linhas são montadas aqui. O grupo cuida do próprio
ciclo de vida: quem o hospeda chama ``fechar()`` ao fechar a tela, para o
login pendente, as janelas de login e os ouvintes das contas morrerem junto.
"""

import logging
from typing import Any

from gi.repository import Adw, Gtk

from cartridges import shared
from cartridges.conquistas import fontes
from cartridges.conquistas.ea import conta as ea_conta
from cartridges.conquistas.ea import janela as ea_janela
from cartridges.conquistas.epic import conta as epic_conta
from cartridges.conquistas.epic import janela as epic_janela
from cartridges.conquistas.xbox import conta, login


class GrupoDasContas(Adw.PreferencesGroup):
    __gtype_name__ = "GrupoDasContas"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.set_title(_("Contas"))
        self.set_description(
            _(
                "Entre com as contas das lojas para acompanhar as conquistas dos jogos do Xbox, do Game Pass, da Epic Games Store e do EA app."
            )
        )
        self.conquistas_conta_row, self.conquistas_conta_botao = self._linha(_("Conta Microsoft"))
        self.conquistas_epic_row, self.conquistas_epic_botao = self._linha(_("Conta Epic"))
        self.conquistas_ea_row, self.conquistas_ea_botao = self._linha(_("Conta EA"))

        # Conta Microsoft: o ouvinte da conta e o login pendente morrem em fechar().
        self._pedido_de_login = None
        self.conquistas_conta_botao.connect("clicked", self._on_conta_clicked)
        self._remover_ouvinte_da_conta = conta.ao_mudar(self._atualizar_conta)
        self._atualizar_conta()

        # Conta Epic: a janela de login e o ouvinte da conta morrem em fechar().
        self._janela_epic = None
        self.conquistas_epic_botao.connect("clicked", self._on_conta_epic_clicked)
        self._remover_ouvinte_da_epic = epic_conta.ao_mudar(self._atualizar_conta_epic)
        self._atualizar_conta_epic()

        # Conta EA: igual à Epic.
        self._janela_ea = None
        self.conquistas_ea_botao.connect("clicked", self._on_conta_ea_clicked)
        self._remover_ouvinte_da_ea = ea_conta.ao_mudar(self._atualizar_conta_ea)
        self._atualizar_conta_ea()

    def _linha(self, titulo: str) -> tuple[Adw.ActionRow, Gtk.Button]:
        linha = Adw.ActionRow(title=titulo, subtitle=_("Não conectada"))
        botao = Gtk.Button(label=_("Entrar"), valign=Gtk.Align.CENTER)
        linha.add_suffix(botao)
        self.add(linha)
        return linha, botao

    def _avisar(self, texto: str) -> None:
        """Toast no diálogo ou na janela que hospeda o grupo."""
        for tipo in (Adw.PreferencesDialog, Adw.ToastOverlay):
            hospedeiro = self.get_ancestor(tipo)
            if hospedeiro is not None:
                toast = Adw.Toast.new(texto)
                toast.set_use_markup(False)
                hospedeiro.add_toast(toast)
                return
        logging.warning("Aviso sem onde mostrar: %s", texto)

    def fechar(self) -> None:
        """Cancela o login pendente, fecha as janelas de login e solta os
        ouvintes das contas. Pode ser chamado mais de uma vez."""
        self._ao_fechar_conta()
        self._ao_fechar_conta_epic()
        self._ao_fechar_conta_ea()

    def _atualizar_conta(self) -> None:
        if self._pedido_de_login is not None:
            subtitulo, rotulo = _("Aguardando o login no navegador…"), _("Cancelar")
        elif conta.conectada():
            subtitulo, rotulo = conta.gamertag() or _("Conta Microsoft"), _("Sair")
        else:
            subtitulo, rotulo = _("Não conectada"), _("Entrar")
        self.conquistas_conta_row.set_subtitle(subtitulo)
        self.conquistas_conta_botao.set_label(rotulo)

    def _on_conta_clicked(self, *_args: Any) -> None:
        if self._pedido_de_login is not None:
            self._pedido_de_login.cancelar()
            return
        if conta.conectada():
            conta.sair()
            self._atualizar_conta()
            return
        try:
            self._pedido_de_login = login.entrar(self._ao_entrar)
        except Exception as erro:  # pylint: disable=broad-exception-caught
            # Porta local bloqueada, limite de handles, falha ao criar a thread:
            # o handler de GTK não levanta e o usuário vê o aviso.
            logging.warning("Falha ao iniciar o login da conta Microsoft: %s", type(erro).__name__)
            self._ao_entrar(login.Resultado.FALHOU)
            return
        self._atualizar_conta()

    def _ao_entrar(self, resultado: "login.Resultado") -> None:
        self._pedido_de_login = None
        self._atualizar_conta()
        # Cancelar durante a troca de código pode deixar a conta conectada: o
        # que vale é o estado da conta, não o resultado que chegou.
        if resultado is login.Resultado.CANCELADO and conta.conectada():
            resultado = login.Resultado.OK
        textos = {
            login.Resultado.SEM_PERFIL_XBOX: _(
                "Esta conta Microsoft não tem um perfil Xbox."
            ),
            login.Resultado.CONTA_INFANTIL: _(
                "Esta conta precisa de permissão de um responsável para usar o Xbox."
            ),
            login.Resultado.FALHOU: _("Não foi possível entrar na conta Microsoft."),
            login.Resultado.SEM_NAVEGADOR: _(
                "Não foi possível abrir o navegador. Verifique o navegador padrão do Windows."
            ),
            login.Resultado.PRAZO_ESGOTADO: _(
                "O login da conta Microsoft expirou. Tente novamente."
            ),
        }
        if resultado in textos:
            self._avisar(textos[resultado])
            return
        if resultado is login.Resultado.OK:
            self._varrer_jogos_do_xbox()

    def _varrer_jogos_do_xbox(self) -> None:
        """Lê na hora as conquistas dos jogos do Xbox, sem esperar a próxima abertura."""
        self._varrer_jogos_da_loja(fontes.eh_do_xbox, "Xbox")

    @staticmethod
    def _varrer_jogos_da_loja(filtro: Any, loja: str) -> None:
        """Depois do login: lê as conquistas dos jogos da loja, sem aviso de novas."""
        try:
            app = shared.win.get_application() if shared.win is not None else None
            varredura = getattr(app, "varredura_conquistas", None)
            if varredura is not None:
                # O filtro lê o disco do jogo: quem o aplica é a thread da varredura.
                varredura.varrer_jogos(list(shared.store), filtro=filtro)
        except Exception:  # pylint: disable=broad-exception-caught
            logging.warning("Falha ao ler as conquistas da conta %s depois do login", loja, exc_info=True)

    def _ao_fechar_conta(self, *_args: Any) -> None:
        login.cancelar_pendente()
        self._remover_ouvinte_da_conta()

    def _atualizar_conta_epic(self) -> None:
        if epic_conta.conectada():
            subtitulo, rotulo = epic_conta.nome() or _("Conta Epic"), _("Sair")
        else:
            subtitulo, rotulo = _("Não conectada"), _("Entrar")
        self.conquistas_epic_row.set_subtitle(subtitulo)
        self.conquistas_epic_botao.set_label(rotulo)

    def _on_conta_epic_clicked(self, *_args: Any) -> None:
        if epic_conta.conectada():
            try:
                epic_conta.sair()
            except Exception as erro:  # pylint: disable=broad-exception-caught
                logging.warning("Falha ao sair da conta Epic: %s", type(erro).__name__)
                self._avisar(_("Não foi possível sair da conta Epic."))
            self._atualizar_conta_epic()
            return
        if self._janela_epic is not None:
            return
        try:
            janela = epic_janela.JanelaDeLogin(self._varrer_jogos_da_epic)
            janela.connect("closed", self._ao_fechar_janela_epic)
            self._janela_epic = janela
            janela.mostrar(self)
        except Exception as erro:  # pylint: disable=broad-exception-caught
            # O handler de GTK não levanta. Sem soltar a janela, "Entrar" ficaria morto.
            self._janela_epic = None
            logging.warning(
                "Falha ao abrir o login da conta Epic: %s", type(erro).__name__
            )
            self._avisar(_("Não foi possível abrir a janela de login da Epic."))

    def _ao_fechar_janela_epic(self, *_args: Any) -> None:
        self._janela_epic = None
        self._atualizar_conta_epic()

    def _varrer_jogos_da_epic(self) -> None:
        """Lê na hora as conquistas dos jogos da Epic, sem aviso de novas."""
        self._varrer_jogos_da_loja(fontes.eh_da_epic, "Epic")

    def _ao_fechar_conta_epic(self, *_args: Any) -> None:
        janela, self._janela_epic = self._janela_epic, None
        if janela is not None:
            try:
                janela.force_close()
            except Exception:  # pylint: disable=broad-exception-caught
                logging.warning(
                    "Falha ao fechar a janela de login da Epic", exc_info=True
                )
        self._remover_ouvinte_da_epic()

    def _atualizar_conta_ea(self) -> None:
        if ea_conta.conectada():
            subtitulo, rotulo = ea_conta.nome() or _("Conta EA"), _("Sair")
        else:
            subtitulo, rotulo = _("Não conectada"), _("Entrar")
        self.conquistas_ea_row.set_subtitle(subtitulo)
        self.conquistas_ea_botao.set_label(rotulo)

    def _on_conta_ea_clicked(self, *_args: Any) -> None:
        if ea_conta.conectada():
            try:
                ea_conta.sair()
            except Exception as erro:  # pylint: disable=broad-exception-caught
                logging.warning("Falha ao sair da conta EA: %s", type(erro).__name__)
                self._avisar(_("Não foi possível sair da conta EA."))
            self._atualizar_conta_ea()
            return
        if self._janela_ea is not None:
            return
        try:
            janela = ea_janela.JanelaDeLogin(self._varrer_jogos_da_ea)
            janela.connect("closed", self._ao_fechar_janela_ea)
            self._janela_ea = janela
            janela.mostrar(self)
        except Exception as erro:  # pylint: disable=broad-exception-caught
            self._janela_ea = None
            logging.warning("Falha ao abrir o login da conta EA: %s", type(erro).__name__)
            self._avisar(_("Não foi possível abrir a janela de login da EA."))

    def _ao_fechar_janela_ea(self, *_args: Any) -> None:
        self._janela_ea = None
        self._atualizar_conta_ea()

    def _varrer_jogos_da_ea(self) -> None:
        """Lê na hora as conquistas dos jogos da EA, sem aviso de novas."""
        self._varrer_jogos_da_loja(fontes.eh_da_ea, "EA")

    def _ao_fechar_conta_ea(self, *_args: Any) -> None:
        janela, self._janela_ea = self._janela_ea, None
        if janela is not None:
            try:
                janela.force_close()
            except Exception:  # pylint: disable=broad-exception-caught
                logging.warning("Falha ao fechar a janela de login da EA", exc_info=True)
        self._remover_ouvinte_da_ea()
