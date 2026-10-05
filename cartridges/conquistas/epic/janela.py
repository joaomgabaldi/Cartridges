"""A janela de login da Epic: a página da Epic abre no navegador, e o usuário
cola aqui o código que ela mostra.

É um `Adw.Dialog` próprio (não `Adw.AlertDialog`, que fecha a cada resposta):
código recusado mantém a janela aberta, com o motivo, para colar outro. A troca
do código vai à rede numa thread; o resultado volta na thread principal e é
descartado se a janela já fechou. O texto colado nunca vai para o log.
"""

import logging
import os
import threading
from typing import Any, Callable

from gi.repository import Adw, GLib, Gtk

from cartridges.conquistas.epic import conta


def _abrir_navegador(url: str) -> None:
    os.startfile(url)  # type: ignore[attr-defined]  # pylint: disable=no-member


def _em_thread(trabalho: Callable[[], Any], entregar: Callable[[Any], None]) -> None:
    def devolver(resultado: Any) -> bool:
        entregar(resultado)
        return False

    def rodar() -> None:
        resultado = trabalho()
        GLib.idle_add(devolver, resultado)

    threading.Thread(target=rodar, daemon=True).start()


_OK, _RECUSADO, _FALHOU = "ok", "recusado", "falhou"


class JanelaDeLogin(Adw.Dialog):
    def __init__(
        self,
        ao_conectar: Callable[[], None],
        abrir: Callable[[str], None] = _abrir_navegador,
        em_thread: Callable[..., None] = _em_thread,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._ao_conectar = ao_conectar
        self._abrir = abrir
        self._em_thread = em_thread
        self._fechada = False
        self.set_title(_("Entrar na conta Epic"))
        self.set_content_width(460)

        passos = Gtk.Label(
            label="\n".join(
                (
                    _("1. Entre na sua conta na página que foi aberta no navegador."),
                    _('2. Copie o código exibido em "authorizationCode".'),
                    _("3. Cole o código abaixo."),
                )
            ),
            wrap=True,
            xalign=0,
        )
        self.campo = Adw.EntryRow(title=_("Código de autorização"))
        grupo = Adw.PreferencesGroup()
        grupo.add(self.campo)
        self.erro = Gtk.Label(wrap=True, xalign=0, visible=False)
        self.erro.add_css_class("error")

        self.botao_abrir = Gtk.Button(label=_("Abrir a página novamente"))
        self.botao_cancelar = Gtk.Button(label=_("Cancelar"))
        self.botao_conectar = Gtk.Button(label=_("Conectar"), sensitive=False)
        self.botao_conectar.add_css_class("suggested-action")
        self._girando = Adw.Spinner(visible=False)
        botoes = Gtk.Box(spacing=12, halign=Gtk.Align.END)
        for widget in (self._girando, self.botao_abrir, self.botao_cancelar, self.botao_conectar):
            botoes.append(widget)

        corpo = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=18,
            margin_top=12,
            margin_bottom=24,
            margin_start=24,
            margin_end=24,
        )
        for widget in (passos, grupo, self.erro, botoes):
            corpo.append(widget)
        vista = Adw.ToolbarView(content=corpo)
        vista.add_top_bar(Adw.HeaderBar())
        self.set_child(vista)

        self.campo.connect("changed", self._ao_mudar)
        self.campo.connect("entry-activated", self._ao_conectar_clicado)
        self.botao_abrir.connect("clicked", lambda *_a: self._abrir_pagina())
        self.botao_cancelar.connect("clicked", lambda *_a: self.close())
        self.botao_conectar.connect("clicked", self._ao_conectar_clicado)
        self.connect("closed", self._ao_fechar)

    def mostrar(self, pai: Any) -> None:
        self.present(pai)
        self._abrir_pagina()

    def _abrir_pagina(self) -> None:
        try:
            self._abrir(conta.PAGINA_DE_LOGIN)
        except Exception as erro:  # pylint: disable=broad-exception-caught
            logging.warning("Falha ao abrir a página de login da Epic: %s", type(erro).__name__)

    def _ao_fechar(self, *_args: Any) -> None:
        self._fechada = True

    def _ao_mudar(self, *_args: Any) -> None:
        self.botao_conectar.set_sensitive(conta.extrair_codigo(self.campo.get_text()) is not None)

    def _ocupada(self, ocupada: bool) -> None:
        for widget in (self.campo, self.botao_abrir, self.botao_conectar):
            widget.set_sensitive(not ocupada)
        self._girando.set_visible(ocupada)
        if not ocupada:
            self._ao_mudar()

    def _ao_conectar_clicado(self, *_args: Any) -> None:
        codigo = conta.extrair_codigo(self.campo.get_text())
        if codigo is None or not self.botao_conectar.get_sensitive():
            return
        self.erro.set_visible(False)
        self._ocupada(True)

        def trabalho() -> str:
            try:
                conta.conectar(codigo)
                return _OK
            except conta.CodigoRecusado:
                return _RECUSADO
            except Exception as erro:  # pylint: disable=broad-exception-caught
                logging.info("Conta Epic: o login falhou (%s)", type(erro).__name__)
                return _FALHOU

        try:
            self._em_thread(trabalho, self._receber)
        except Exception as erro:  # pylint: disable=broad-exception-caught
            logging.warning("Falha ao iniciar o login da Epic: %s", type(erro).__name__)
            self._receber(_FALHOU)

    def _receber(self, resultado: str) -> None:
        if self._fechada:
            return
        try:
            self._ocupada(False)
            if resultado == _OK:
                self.close()
                self._ao_conectar()
                return
            if resultado == _RECUSADO:
                self.campo.set_text("")
                texto = _("O código não foi aceito. Gere um novo código na página da Epic e tente novamente.")
            else:
                texto = _("Não foi possível entrar na conta Epic.")
            self.erro.set_label(texto)
            self.erro.set_visible(True)
        except Exception:  # pylint: disable=broad-exception-caught
            logging.warning("Falha ao mostrar o resultado do login da Epic", exc_info=True)
