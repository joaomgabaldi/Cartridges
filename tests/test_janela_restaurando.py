"""A janela que aparece na abertura enquanto um backup agendado é restaurado."""

from cartridges.janela_restaurando import JanelaRestaurando


def test_textos():
    janela = JanelaRestaurando()
    assert janela.get_title() == "Cartridges"
    assert janela.titulo.get_label() == "Restaurando o backup"
    assert janela.texto.get_label() == "O aplicativo será aberto quando a restauração terminar."
    assert janela.porcentagem.get_label() == "0%"
    assert janela.barra.get_show_text() is False  # o texto colado na barra ficava feio
    assert not janela.get_deletable() and not janela.get_resizable()
    janela.terminar()


def test_avancar_mostra_a_porcentagem():
    janela = JanelaRestaurando()
    janela.avancar(0.425)
    assert janela.porcentagem.get_label() == "42%"
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


def test_so_entrega_quando_a_porcentagem_inteira_muda():
    from cartridges.janela_restaurando import entregar_so_ao_mudar

    entregas = []
    avancar = entregar_so_ao_mudar(lambda fracao: entregas.append(fracao))
    for i in range(1, 100_001):  # milhares de pedaços minúsculos
        avancar(i / 100_000)
    assert len(entregas) <= 101
    assert entregas[-1] == 1.0
