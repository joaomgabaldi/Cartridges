# test_caixa_redimensionavel.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A caixa do "Onde eu parei" muda de tamanho pelo puxador e lembra o tamanho."""

from gi.repository import Gtk

from cartridges import shared
from cartridges.utils import caixa_redimensionavel as caixa


_pais: list[Gtk.Box] = []


def _caixa_solta() -> Gtk.ScrolledWindow:
    rolagem = Gtk.ScrolledWindow(child=Gtk.TextView())
    pai = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    pai.append(rolagem)
    # Sem uma referência, o Python solta a caixa e a rolagem fica sem pai.
    _pais.append(pai)
    return rolagem


def test_arrastar_soma_o_deslocamento_dentro_dos_limites():
    maximo = (900, 600)
    assert caixa.novo_tamanho((320, 120), (100, 50), maximo) == (420, 170)
    # Nunca menor que o tamanho de sempre, nem maior que a janela deixa.
    assert caixa.novo_tamanho((320, 120), (-500, -500), maximo) == caixa.MINIMO
    assert caixa.novo_tamanho((320, 120), (5000, 5000), maximo) == maximo


def test_puxador_entra_no_canto_da_caixa(state_schema):
    rolagem = _caixa_solta()
    puxador = caixa.ligar(rolagem)

    assert rolagem.get_parent().get_last_child() is puxador
    assert puxador.has_css_class("puxador-de-tamanho")
    assert puxador.get_halign() == Gtk.Align.END


def test_tamanho_guardado_vale_para_as_duas_caixas(state_schema):
    """O balão da tela do jogo e o da tela de sessão são a mesma caixa: o
    tamanho deixado num vale para o outro ao abrir."""
    uma, outra = _caixa_solta(), _caixa_solta()
    caixa.ligar(uma)
    caixa.ligar(outra)

    caixa.aplicar_tamanho(uma, (500, 300))
    caixa.restaurar(outra)

    assert shared.state_schema.get_int("notas-largura") == 500
    assert shared.state_schema.get_int("notas-altura") == 300
    assert outra.get_size_request() == (500, 300)


def test_tamanho_guardado_menor_que_o_minimo_nao_vale(state_schema):
    """Um valor mexido à mão não pode encolher a caixa a nada."""
    shared.state_schema.set_int("notas-largura", 10)
    shared.state_schema.set_int("notas-altura", 10)
    rolagem = _caixa_solta()

    caixa.restaurar(rolagem)

    assert rolagem.get_size_request() == caixa.MINIMO


def test_as_duas_caixas_da_janela_tem_puxador(real_window):
    for vista in (real_window.details_view_notes_view, real_window.session_blocker_notes_view):
        assert vista.get_parent().get_parent().get_last_child().has_css_class(
            "puxador-de-tamanho"
        )


def test_tamanho_guardado_cabe_na_janela_ao_reabrir():
    """Um tamanho deixado com a janela grande não passa da janela pequena."""
    from gi.repository import GLib  # noqa: PLC0415

    rolagem = _caixa_solta()
    janela = Gtk.Window(default_width=800, default_height=600, child=rolagem.get_parent())
    janela.present()
    contexto = GLib.MainContext.default()
    while not janela.get_width():
        contexto.iteration(False)
    shared.state_schema.set_int("notas-largura", 5000)
    shared.state_schema.set_int("notas-altura", 5000)

    try:
        caixa.restaurar(rolagem)
        largura, altura = rolagem.get_size_request()
        assert largura <= round(janela.get_width() * caixa.FRACAO_MAXIMA[0])
        assert altura <= round(janela.get_height() * caixa.FRACAO_MAXIMA[1])
    finally:
        janela.destroy()


def test_arrasto_segue_o_ponteiro_ate_soltar(state_schema):
    """No Windows, o balão deixa de receber os movimentos assim que o ponteiro
    sai de cima dele (e para aumentar a caixa ele precisa sair): o arrasto lê a
    posição na janela enquanto o botão estiver apertado, e grava ao soltar."""
    rolagem = _caixa_solta()
    arrasto = caixa.Arrasto(rolagem, maximo=lambda: (900, 600))

    arrasto.comecar((100.0, 100.0), (320, 120))
    assert arrasto.passo((150.0, 130.0), apertado=True) is True
    # O balão é centralizado no botão: a largura cresce o dobro do que o
    # ponteiro andou, para o canto direito acompanhar o mouse.
    assert rolagem.get_size_request() == (420, 150)
    # Fora do balão, e muito além: o máximo segura.
    assert arrasto.passo((5000.0, 5000.0), apertado=True) is True
    assert rolagem.get_size_request() == (900, 600)
    assert shared.state_schema.get_int("notas-largura") == 320

    # Soltou: grava o tamanho de agora e para de ler.
    assert arrasto.passo((5000.0, 5000.0), apertado=False) is False
    assert shared.state_schema.get_int("notas-largura") == 900
    assert shared.state_schema.get_int("notas-altura") == 600
