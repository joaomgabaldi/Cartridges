# test_estilo_css.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A folha de estilo do app carrega sem erro no GTK."""

from pathlib import Path

from gi.repository import Gtk

ESTILO = Path(__file__).parent.parent / "data" / "gtk" / "style.css"


def test_style_css_nao_tem_erro_de_sintaxe():
    """Uma regra que o GTK não conhece é descartada em silêncio na tela e só
    aparece como aviso no terminal (o ``overflow`` dos ícones de conquista)."""
    erros = []
    provedor = Gtk.CssProvider()
    provedor.connect(
        "parsing-error",
        lambda _p, secao, erro: erros.append(f"{secao.to_string()}: {erro.message}"),
    )
    provedor.load_from_path(str(ESTILO))
    assert erros == []
