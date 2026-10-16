"""A janela de login da EA: a página da EA abre no navegador, e o usuário cola
aqui o pedido que copiou ("Copiar como cURL").

É um `Adw.Dialog` próprio (não `Adw.AlertDialog`, que fecha a cada resposta):
login recusado mantém a janela aberta, com o motivo, para colar outro. A troca
vai à rede numa thread; o resultado volta na thread principal. Com a janela
já fechada, só a conta conectada conta (o aviso ainda é dado); o resto é descartado.
O texto colado (traz cookies) nunca vai para o log.
"""

import logging
import os
from typing import Any, Callable, Optional

from gi.repository import Adw, Gtk

from cartridges.conquistas.ea import conta
from cartridges.conquistas.vigia_da_conta import _em_thread


def _abrir_navegador(url: str) -> None:
    os.startfile(url)  # type: ignore[attr-defined]  # pylint: disable=no-member


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
        self.set_title(_("Entrar na conta EA"))
        self.set_content_width(460)

        passos = Gtk.Label(
            label="\n".join(
                (
                    _("1. Entre na sua conta EA na página que foi aberta no navegador."),
                    _("2. No navegador, pressione F12 e abra a aba Rede."),
                    _("3. Clique em Abrir a página da conta, abaixo."),
                    _(
                        '4. Na aba Rede, clique com o botão direito no pedido que começa com "auth?client_id" '
                        "e escolha Copiar › Copiar como cURL."
                    ),
                    _("5. Cole o texto abaixo."),
                )
            ),
            wrap=True,
            xalign=0,
        )
        self.texto = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR, top_margin=6, bottom_margin=6, left_margin=6, right_margin=6)
        rolagem = Gtk.ScrolledWindow(child=self.texto, min_content_height=160, has_frame=True)
        self.erro = Gtk.Label(wrap=True, xalign=0, visible=False)
        self.erro.add_css_class("error")

        self.botao_pagina = Gtk.Button(label=_("Abrir a página da conta"))
        self.botao_cancelar = Gtk.Button(label=_("Cancelar"))
        self.botao_conectar = Gtk.Button(label=_("Conectar"), sensitive=False)
        self.botao_conectar.add_css_class("suggested-action")
        self._girando = Adw.Spinner(visible=False)
        botoes = Gtk.Box(spacing=12, halign=Gtk.Align.END)
        for widget in (self._girando, self.botao_pagina, self.botao_cancelar, self.botao_conectar):
            botoes.append(widget)

        corpo = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=12,
            margin_top=12,
            margin_bottom=24,
            margin_start=24,
            margin_end=24,
        )
        rotulo = Gtk.Label(label=_("Texto copiado do navegador"), xalign=0)
        rotulo.add_css_class("heading")
        for widget in (passos, rotulo, rolagem, self.erro, botoes):
            corpo.append(widget)
        vista = Adw.ToolbarView(content=corpo)
        vista.add_top_bar(Adw.HeaderBar())
        self.set_child(vista)

        self.texto.get_buffer().connect("changed", self._ao_mudar)
        self.botao_pagina.connect("clicked", lambda *_a: self._abrir_url(conta.TOKEN))
        self.botao_cancelar.connect("clicked", lambda *_a: self.close())
        self.botao_conectar.connect("clicked", self._ao_conectar_clicado)
        self.connect("closed", self._ao_fechar)

    def mostrar(self, pai: Any) -> None:
        self.present(pai)
        self._abrir_url(conta.PAGINA_DE_LOGIN)

    def _abrir_url(self, url: str) -> None:
        aviso = _("Não foi possível abrir o navegador. Acesse ea.com/login manualmente.")
        try:
            self._abrir(url)
        except Exception as erro:  # pylint: disable=broad-exception-caught
            logging.warning("Falha ao abrir a página da EA: %s", type(erro).__name__)
            self.erro.set_label(aviso)
            self.erro.set_visible(True)
        else:
            # Só o aviso do navegador some; um erro de login anterior continua.
            if self.erro.get_label() == aviso:
                self.erro.set_visible(False)

    def _ler(self) -> str:
        buffer = self.texto.get_buffer()
        return buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False)

    def _ao_fechar(self, *_args: Any) -> None:
        self._fechada = True

    def _ao_mudar(self, *_args: Any) -> None:
        self.botao_conectar.set_sensitive(conta.extrair(self._ler()) is not None)

    def _ocupada(self, ocupada: bool) -> None:
        for widget in (self.texto, self.botao_pagina, self.botao_conectar):
            widget.set_sensitive(not ocupada)
        self._girando.set_visible(ocupada)
        if not ocupada:
            self._ao_mudar()

    def _ao_conectar_clicado(self, *_args: Any) -> None:
        texto = self._ler()
        if conta.extrair(texto) is None or not self.botao_conectar.get_sensitive():
            return
        self.erro.set_visible(False)
        self._ocupada(True)

        def trabalho() -> str:
            try:
                conta.conectar(texto)
                return _OK
            except conta.LoginRecusado:
                return _RECUSADO
            except Exception as erro:  # pylint: disable=broad-exception-caught
                logging.info("Conta EA: o login falhou (%s)", type(erro).__name__)
                return _FALHOU

        try:
            self._em_thread(trabalho, self._receber)
        except Exception as erro:  # pylint: disable=broad-exception-caught
            logging.warning("Falha ao iniciar o login da EA: %s", type(erro).__name__)
            self._receber(_FALHOU)

    def _receber(self, resultado: Optional[str]) -> None:
        # None só chega se o trabalho levantar fora de `Exception`; cai na falha genérica.
        if resultado == _OK:
            # A conta já conectou, com a janela aberta ou não: a leitura dos jogos tem de acontecer.
            if not self._fechada:
                try:
                    self._ocupada(False)
                    self.close()
                except Exception:  # pylint: disable=broad-exception-caught
                    logging.warning("Falha ao fechar a janela de login da EA", exc_info=True)
            try:
                self._ao_conectar()
            except Exception:  # pylint: disable=broad-exception-caught
                logging.warning("Falha ao avisar que a conta EA conectou", exc_info=True)
            return
        if self._fechada:
            return
        try:
            self._ocupada(False)
            if resultado == _RECUSADO:
                self.texto.get_buffer().set_text("")
                texto = _("A EA não reconheceu o login. Entre novamente em ea.com e copie o pedido outra vez.")
            else:
                texto = _("Não foi possível entrar na conta EA. Verifique a conexão e tente novamente.")
            self.erro.set_label(texto)
            self.erro.set_visible(True)
        except Exception:  # pylint: disable=broad-exception-caught
            logging.warning("Falha ao mostrar o resultado do login da EA", exc_info=True)
