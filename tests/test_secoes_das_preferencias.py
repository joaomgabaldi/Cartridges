# test_secoes_das_preferencias.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A distribuição das opções pelas dez seções das Preferências (tabela do desenho de 05/11/2026)."""

from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest

from cartridges import shared
from cartridges.saves import backup_de_saves
from tests.apoio_qml_biblioteca import _achar, _esperar
from tests.apoio_qml_detalhes import _foco_dentro_de
from tests.apoio_qml_preferencias import _abrir, _avaliar, _clique, app  # noqa: F401

# seção -> títulos das linhas buscáveis, na ordem da tela (ordem do código dentro de cada grupo)
DISTRIBUICAO = {
    "geral": [
        "Minimizar ao iniciar um jogo",
        "Contar horas de jogo", "Tempo de espera ao fechar o jogo",
        "Nome do jogador", "Idioma dos jogos",
        "Mostrar o botão Novidades", "Reproduzir capas animadas automaticamente",
    ],
    "controle": [
        "Usar controle Xbox", "Vibração",
        "Abrir o Big Picture ao usar um controle", "Som ao trocar de capa",
    ],
    "monitores": [
        "Mover para outro monitor", "Monitor", "Identificar monitores",
        "Trocar o papel de parede dos outros monitores", "Chave da API do wallhaven (opcional)",
    ],
    "iluminacao": [
        "Brilho máximo por dispositivo", "Calibrar as cores", "Configurar a iluminação inteligente", "Testar",
        "Mudar a cor da iluminação inteligente", "Brilho (%)", "Cor acompanha a tela do jogo", "Cor do app",
    ],
    "importacao": ["Importar jogos automaticamente", "Remover jogos desinstalados", "Atalhos"],
    "metadados": [
        "Buscar metadados da Steam", "Buscar tempos do HowLongToBeat",
        "Atualizar metadados",
        "Chave da API", "Usar o SteamGridDB", "Priorizar o SteamGridDB às imagens oficiais", "Preferir imagens animadas",
        "Atualizar capas",
    ],
    "conquistas": [
        "Chave da API",
        "Mostrar descrição das conquistas ocultas",
        "Mostrar aviso durante o jogo", "Tocar som com o aviso", "Volume do som (%)", "Posição do aviso",
        "Mostrar um aviso de exemplo",
        "Piscar a iluminação inteligente", "Cor do alerta", "Estilo do alerta", "Testar o alerta",
    ],
    "contas": ["Conta Microsoft", "Conta Epic", "Conta EA"],
    "backup": [
        "Exportar para arquivo", "Importar de arquivo",
        "Pasta dos saves", "Restaurar saves de todos os jogos",
    ],
    "aplicativo": ["Buscar atualizações", "Redefinir Kyron"],
}


def test_cada_opcao_esta_em_exatamente_uma_secao(app, monkeypatch):  # noqa: F811
    # Com os saves disponíveis, "Pasta dos saves" e "Restaurar saves" aparecem.
    monkeypatch.setattr(backup_de_saves, "disponivel", lambda: True)
    _abrir(app)
    vistas = set()
    for secao, esperados in DISTRIBUICAO.items():
        titulos = _avaliar(
            app.achar("dialogoDePreferencias"), f"linhasBuscaveis('{secao}').map(l => l.titulo)"
        )
        assert titulos == esperados, secao
        vistas.update((secao, t) for t in titulos)
    # o par (seção, título) é único: "Chave da API" existe em Metadados e em Conquistas
    assert len(vistas) == sum(len(ts) for ts in DISTRIBUICAO.values())


def _dialogo(app):
    return app.achar("dialogoDePreferencias")


def _visivel(app, nome):
    return app.achar(nome).property("visible") is True


def test_lista_mostra_as_10_secoes_na_ordem(app):  # noqa: F811
    _abrir(app)
    secoes = _avaliar(_dialogo(app), "secoes")
    assert [s["id"] for s in secoes] == list(DISTRIBUICAO)
    assert [s["icone"] for s in secoes] == [
        "preferences-system", "input-gaming", "video-joined-displays", "display-brightness", "folder-download",
        "image-x-generic", "trofeu", "avatar-default", "drive-harddisk", "software-update-available",
    ]
    assert all(s["subtitulo"] for s in secoes)
    assert _achar(app.janela, "abas") is None and _achar(app.janela, "botaoDeBuscaDasPreferencias") is None
    # O campo de busca fica sempre à vista, logo abaixo do título da lista.
    assert _visivel(app, "campoDeBuscaDasPreferencias")


def test_clicar_num_item_troca_a_secao_e_o_cabecalho(app):  # noqa: F811
    _abrir(app)
    _clique(app, "secao-iluminacao")
    assert _esperar(lambda: app.achar("tituloDaSecao").property("text") == "Iluminação")
    assert app.achar("subtituloDaSecao").property("text") == "Iluminação inteligente da Tuya"
    assert _visivel(app, "paginaDaIluminacao") and not _visivel(app, "paginaGeral")


def test_foco_no_item_ja_troca_a_secao(app):  # noqa: F811
    _abrir(app)
    app.achar("secao-geral").forceActiveFocus(Qt.FocusReason.TabFocusReason)
    QTest.keyClick(app.janela, Qt.Key.Key_Down)
    assert _dialogo(app).property("secao") == "controle"
    assert _foco_dentro_de(app, "secao-controle")
    QTest.keyClick(app.janela, Qt.Key.Key_Up)
    QTest.keyClick(app.janela, Qt.Key.Key_Up)  # na ponta, fica
    assert _dialogo(app).property("secao") == "geral"
    assert _foco_dentro_de(app, "secao-geral")


def test_enter_no_item_escolhe_a_secao(app):  # noqa: F811
    _abrir(app)
    app.achar("secao-importacao").forceActiveFocus(Qt.FocusReason.TabFocusReason)
    QTest.keyClick(app.janela, Qt.Key.Key_Return)
    assert _esperar(lambda: _visivel(app, "paginaDeImportacao"))


def test_direcional_do_controle_anda_pela_lista_e_sai_para_as_linhas(app):  # noqa: F811
    _abrir(app, "geral")
    app.achar("secao-geral").forceActiveFocus(Qt.FocusReason.TabFocusReason)
    assert _esperar(lambda: _foco_dentro_de(app, "secao-geral"))
    app.controle.mover.emit(0, 1)
    assert _dialogo(app).property("secao") == "controle"
    assert _foco_dentro_de(app, "secao-controle")
    app.controle.mover.emit(0, -1)
    assert _dialogo(app).property("secao") == "geral"
    app.controle.mover.emit(1, 0)
    assert _foco_dentro_de(app, "paginaGeral")
    assert _dialogo(app).property("secao") == "geral"


def test_contador_bate_com_as_linhas_e_acompanha_saves(app, monkeypatch):  # noqa: F811
    monkeypatch.setattr(backup_de_saves, "disponivel", lambda: False)
    _abrir(app)
    assert app.achar("contadorDaSecao-importacao").property("text") == "3"
    assert app.achar("contadorDaSecao-geral").property("text") == "7"
    assert app.achar("contadorDaSecao-backup").property("text") == "2"
    # Sem reabrir: os saves aparecem e o contador do Backup sobe.
    monkeypatch.setattr(backup_de_saves, "disponivel", lambda: True)
    app.preferencias._backup.reler()  # noqa: SLF001
    app.preferencias._reler()  # noqa: SLF001
    assert _esperar(lambda: app.achar("contadorDaSecao-backup").property("text") == "4")
    monkeypatch.setattr(backup_de_saves, "disponivel", lambda: False)
    app.preferencias._backup.reler()  # noqa: SLF001
    app.preferencias._reler()  # noqa: SLF001
    assert _esperar(lambda: app.achar("contadorDaSecao-backup").property("text") == "2")


def test_cartao_largo_tem_a_lista_de_210_e_os_contadores(app):  # noqa: F811
    _abrir(app)
    assert app.achar("cartaoDasPreferencias").property("width") == 860
    assert app.achar("listaDeSecoes").property("width") == 210
    assert _visivel(app, "contadorDaSecao-geral")


def test_cartao_estreito_encolhe_a_lista_e_esconde_os_contadores(app):  # noqa: F811
    app.janela.setWidth(600)
    _abrir(app)
    assert app.achar("listaDeSecoes").property("width") == 160
    assert not _visivel(app, "contadorDaSecao-geral")


def test_busca_abre_a_secao_do_resultado_mesmo_com_o_grupo_apagado(app):  # noqa: F811
    shared.schema.set_boolean("playtime-tracking", False)  # sem contar horas, o grupo dos monitores fica apagado
    _abrir(app)
    _dialogo(app).setProperty("filtro", "monitor")
    assert _esperar(lambda: _visivel(app, "resultadosDaBuscaDasPreferencias"))
    resultados = _avaliar(_dialogo(app), "resultados.map(r => [r.titulo, r.local, r.secao])")
    alvo = next(i for i, r in enumerate(resultados) if r[1] == "Monitores → Ao iniciar um jogo")
    _clique(app, f"resultadoDaBusca-{alvo}Botao")
    assert _esperar(lambda: _dialogo(app).property("secao") == "monitores")
    assert _esperar(lambda: _visivel(app, "paginaDosMonitores"))
    assert app.achar("campoDeBuscaDasPreferencias").property("text") == ""
    # Com o grupo apagado a página não tem linha para focar: o foco cai no item da seção, não em algo escondido.
    assert _esperar(lambda: _foco_dentro_de(app, "secao-monitores"))
    assert app.achar("campoDeBuscaDasPreferencias").property("activeFocus") is not True


def test_primeiro_tab_do_x_vai_a_primeira_linha_da_secao(app):  # noqa: F811
    _abrir(app, "importacao")
    assert _foco_dentro_de(app, "fecharDoCabecalho")
    QTest.keyClick(app.janela, Qt.Key.Key_Tab)
    assert _foco_dentro_de(app, "paginaDeImportacao")


def test_shift_tab_das_linhas_chega_a_lista_e_a_busca(app):  # noqa: F811
    _abrir(app, "importacao")
    QTest.keyClick(app.janela, Qt.Key.Key_Tab)
    assert _foco_dentro_de(app, "paginaDeImportacao")
    QTest.keyClick(app.janela, Qt.Key.Key_Backtab)  # o X
    assert _foco_dentro_de(app, "fecharDoCabecalho")
    QTest.keyClick(app.janela, Qt.Key.Key_Backtab)  # a lista: só a seção atual é parada de Tab
    assert _foco_dentro_de(app, "secao-importacao")
    QTest.keyClick(app.janela, Qt.Key.Key_Backtab)
    assert _foco_dentro_de(app, "campoDeBuscaDasPreferencias")


def _na_vista(app, nome):
    """O item da lista está inteiro dentro da área visível da rolagem da lista."""
    rolagem, item = app.achar("rolagemDaLista"), app.achar(nome)
    y = item.mapToItem(rolagem.property("contentItem"), QPointF(0, 0)).y()
    topo = rolagem.property("contentY")
    return y >= topo - 0.5 and y + item.height() <= topo + rolagem.property("height") + 0.5


def test_lista_rola_para_acompanhar_o_foco_em_janela_baixa(app):  # noqa: F811
    app.janela.setHeight(420)
    _abrir(app)
    rolagem = app.achar("rolagemDaLista")
    assert rolagem.property("contentHeight") > rolagem.property("height")  # a lista não cabe
    app.achar("secao-geral").forceActiveFocus(Qt.FocusReason.TabFocusReason)
    for _ in range(9):
        QTest.keyClick(app.janela, Qt.Key.Key_Down)
    assert _dialogo(app).property("secao") == "aplicativo"
    assert rolagem.property("contentY") > 0
    assert _na_vista(app, "secao-aplicativo")
    for _ in range(9):
        QTest.keyClick(app.janela, Qt.Key.Key_Up)
    assert _dialogo(app).property("secao") == "geral"
    assert _na_vista(app, "secao-geral")


def test_clicar_numa_secao_durante_a_busca_mostra_a_secao(app):  # noqa: F811
    _abrir(app)
    _dialogo(app).setProperty("filtro", "brilho")
    assert _esperar(lambda: _visivel(app, "resultadosDaBuscaDasPreferencias"))
    _clique(app, "secao-controle")
    assert _esperar(lambda: _visivel(app, "paginaDoControle"))
    assert app.achar("campoDeBuscaDasPreferencias").property("text") == ""
    assert not _visivel(app, "resultadosDaBuscaDasPreferencias")


def test_enter_numa_secao_durante_a_busca_mostra_a_secao(app):  # noqa: F811
    _abrir(app)
    _dialogo(app).setProperty("filtro", "brilho")
    assert _esperar(lambda: _visivel(app, "resultadosDaBuscaDasPreferencias"))
    app.achar("secao-controle").forceActiveFocus(Qt.FocusReason.TabFocusReason)
    QTest.keyClick(app.janela, Qt.Key.Key_Return)
    assert _esperar(lambda: _visivel(app, "paginaDoControle"))
    assert app.achar("campoDeBuscaDasPreferencias").property("text") == ""


def test_tab_do_campo_aos_resultados_nao_apaga_a_busca(app):  # noqa: F811
    _abrir(app)
    campo = app.achar("campoDeBuscaDasPreferencias")
    _dialogo(app).setProperty("filtro", "brilho")
    assert _esperar(lambda: _visivel(app, "resultadosDaBuscaDasPreferencias"))
    campo.forceActiveFocus(Qt.FocusReason.TabFocusReason)
    for _ in range(6):
        QTest.keyClick(app.janela, Qt.Key.Key_Tab)
        if _foco_dentro_de(app, "resultadoDaBusca-0"):
            break
    assert _foco_dentro_de(app, "resultadoDaBusca-0")
    assert campo.property("text") == "brilho"
    assert _visivel(app, "resultadosDaBuscaDasPreferencias")


def test_direcional_para_a_direita_durante_a_busca_vai_ao_primeiro_resultado(app):  # noqa: F811
    _abrir(app)
    _dialogo(app).setProperty("filtro", "brilho")
    assert _esperar(lambda: _visivel(app, "resultadosDaBuscaDasPreferencias"))
    app.achar("secao-geral").forceActiveFocus(Qt.FocusReason.TabFocusReason)
    app.controle.mover.emit(1, 0)
    assert _esperar(lambda: _foco_dentro_de(app, "resultadoDaBusca-0"))
    assert app.achar("campoDeBuscaDasPreferencias").property("text") == "brilho"


def test_direcional_para_a_direita_sem_linha_focavel_fica_na_lista(app):  # noqa: F811
    shared.schema.set_boolean("playtime-tracking", False)
    _abrir(app, "monitores")
    app.achar("secao-monitores").forceActiveFocus(Qt.FocusReason.TabFocusReason)
    app.controle.mover.emit(1, 0)
    assert _foco_dentro_de(app, "secao-monitores")


def test_trocar_de_secao_volta_a_rolagem_ao_topo(app):  # noqa: F811
    app.janela.setHeight(420)
    _abrir(app, "conquistas")
    rolagem = app.achar("rolagemDasPreferencias")
    assert rolagem.property("contentHeight") > rolagem.property("height")
    rolagem.setProperty("contentY", 80)
    assert rolagem.property("contentY") > 0
    _clique(app, "secao-geral")
    assert _esperar(lambda: _visivel(app, "paginaGeral"))
    assert rolagem.property("contentY") == 0


def test_resultado_no_fim_da_pagina_termina_com_a_linha_a_vista(app):  # noqa: F811
    app.janela.setHeight(420)
    _abrir(app, "aplicativo")
    _dialogo(app).setProperty("filtro", "a")
    assert _esperar(lambda: _visivel(app, "resultadosDaBuscaDasPreferencias"))
    resultados = _avaliar(_dialogo(app), "resultados.map(r => r.secao)")
    alvo = max(i for i, sec in enumerate(resultados) if sec == "geral")
    _clique(app, f"resultadoDaBusca-{alvo}Botao")
    assert _esperar(lambda: _visivel(app, "paginaGeral"))
    rolagem = app.achar("rolagemDasPreferencias")

    def a_vista():
        foco = app.janela.activeFocusItem()
        if foco is None or not _foco_dentro_de(app, "paginaGeral"):
            return False
        y = foco.mapToItem(rolagem, QPointF(0, 0)).y()
        return y >= -0.5 and y + foco.height() <= rolagem.property("height") + 0.5

    assert _esperar(a_vista)
    assert rolagem.property("contentY") > 0
