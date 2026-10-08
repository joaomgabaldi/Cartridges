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

from gi.repository import Gtk

_MB = 1024 * 1024


def _tamanho(n: int) -> str:
    # MB de 1024², como os limites de download: o maior arquivo diz "200,0 MB".
    if n < _MB:
        return f"{n // 1024} KB"
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

    def zerar(self) -> None:
        self.barra.set_fraction(0.0)
        self.texto.set_label("")

    def atualizar(self, recebido: int, total: Optional[int]) -> bool:
        if total is None:
            self.barra.pulse()
        else:
            self.barra.set_fraction(min(recebido / total, 1.0))
        self.texto.set_label(tamanho_baixado(recebido, total))
        return False
