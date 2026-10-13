"""A janela que aparece na abertura enquanto um backup agendado é restaurado."""

from cartridges.janela_restaurando import JanelaRestaurando


def test_textos():
    janela = JanelaRestaurando()
    assert janela.get_title() == "Cartridges"
    assert janela.titulo.get_label() == "Restaurando o backup"
    assert janela.texto.get_label() == "O aplicativo será aberto quando a restauração terminar."
    assert janela.barra.get_text() == "0%"
    assert not janela.get_deletable() and not janela.get_resizable()
    janela.terminar()


def test_avancar_mostra_a_porcentagem():
    janela = JanelaRestaurando()
    janela.avancar(0.425)
    assert janela.barra.get_text() == "42%"
    assert abs(janela.barra.get_fraction() - 0.42) < 1e-9
    janela.terminar()


def test_nao_fecha_antes_de_terminar():
    janela = JanelaRestaurando()
    assert janela.emit("close-request") is True
    janela.terminar()


def test_tem_barra_de_titulo_so_com_minimizar():
    janela = JanelaRestaurando()
    assert janela.cabecalho.get_decoration_layout() == ":minimize"
    janela.terminar()
