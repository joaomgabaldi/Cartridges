# tela_de_download.py
#
# Copyright 2026 joaomgabaldi
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A tela "Baixando…" dos seletores de capa, logo e papel de parede.

Com capas animadas de até 200 MB, o spinner não dizia se o download andava ou
tinha travado. Esta tela mostra a barra e quanto já chegou do total.
"""

from typing import Optional

from gi.repository import Gdk, Gtk

_MB = 1024 * 1024


# Um pulso da barra a cada 0,1 s enquanto o primeiro dado não chega, em
# microssegundos (a unidade do frame clock).
_INTERVALO_DO_PULSO = 100_000


def _tamanho(n: int) -> str:
    # MB de 1024², como os limites de download: o maior arquivo diz "200,0 MB".
    # Para cima, como o Explorador de Arquivos: 300 bytes já são "1 KB",
    # nunca "0 KB" com algo baixado. O que arredonda para 1024 KB já é MB.
    kb = -(-n // 1024)
    if kb < 1024:
        return f"{kb} KB"
    return f"{n / _MB:.1f} MB".replace(".", ",")


def tamanho_baixado(recebido: int, total: Optional[int]) -> str:
    """ "4,4 MB de 21,0 MB", ou só "4,4 MB" quando o total não é conhecido."""
    if total is None:
        return _tamanho(recebido)
    return _("{recebido} de {total}").format(
        recebido=_tamanho(recebido), total=_tamanho(total)
    )


class TelaDeDownload(Gtk.Box):
    """Título, barra e tamanho, centrados na página do seletor."""

    def __init__(self) -> None:
        super().__init__(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=12,
            halign=Gtk.Align.CENTER,
            valign=Gtk.Align.CENTER,
            width_request=280,
        )
        titulo = Gtk.Label(label=_("Baixando…"))
        titulo.add_css_class("title-3")
        self.barra = Gtk.ProgressBar()
        self.texto = Gtk.Label()
        self.texto.add_css_class("dim-label")
        self.texto.add_css_class("numeric")
        self.append(titulo)
        self.append(self.barra)
        self.append(self.texto)

        # Entre o clique e o primeiro dado (DNS, TLS, um servidor lento), a
        # barra pulsa: parada e vazia, parecia travada.
        self._esperando = False
        self._ultimo_pulso: Optional[int] = None
        self._tique_ligado = False

    def _ao_tique(self, relogio: Gdk.FrameClock) -> bool:
        # Recebe o widget como `self` e não captura nada: uma lambda com
        # `self` dentro, guardada pelo GTK, prendia a tela na memória depois
        # de o seletor fechar.
        return self._tique(relogio.get_frame_time())

    def _tique(self, agora: int) -> bool:
        # O tick roda enquanto o widget existe, escondido ou não, e mantém o
        # relógio de quadros ligado: desliga no primeiro dado ou quando a
        # página de erro toma o lugar da tela.
        if not self._esperando or not self.get_mapped():
            self._tique_ligado = False
            if self._esperando:
                # Sai do modo de atividade da barra, que tem animação própria.
                self.barra.set_fraction(0.0)
            return False
        if (
            self._ultimo_pulso is None
            or agora - self._ultimo_pulso >= _INTERVALO_DO_PULSO
        ):
            self._ultimo_pulso = agora
            self.barra.pulse()
        return True

    def zerar(self) -> None:
        self.barra.set_fraction(0.0)
        self.texto.set_label("")
        self._esperando = True
        self._ultimo_pulso = None
        if not self._tique_ligado:
            self._tique_ligado = True
            self.add_tick_callback(TelaDeDownload._ao_tique)

    def atualizar(self, recebido: int, total: Optional[int]) -> bool:
        self._esperando = False
        # Chegou mais do que o servidor informou: o total real não é conhecido,
        # e "30,0 MB de 20,0 MB" pareceria erro do aplicativo.
        if total is not None and recebido > total:
            total = None
        if total is None:
            self.barra.pulse()
        else:
            self.barra.set_fraction(recebido / total)
        self.texto.set_label(tamanho_baixado(recebido, total))
        return False
