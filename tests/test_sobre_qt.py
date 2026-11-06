# test_sobre_qt.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O "Sobre o Cartridges": as funções puras, o `Sobre` e o `DialogoSobre.qml` no `Aplicativo.qml` inteiro.

Nada de verdade: os logs são arquivos do `tmp_path`, a área de transferência e o navegador são falsos, e o
`FileDialog` do "Salvar como…" nunca abre (o teste chama o `salvar(url)` direto).
"""

import lzma
from pathlib import Path

import pytest
from PySide6.QtCore import QMetaObject, QPointF, Qt, QUrl
from PySide6.QtTest import QTest

from kyron import shared
from kyron.modelos import sobre as modulo_sobre
from kyron.modelos.avisos import FilaDeAvisos
from kyron.modelos.sobre import Sobre, informacoes_de_depuracao, novidades_da_versao
from tests.apoio_janela_atualizacao import Janela, achar, avaliar, esperar

METAINFO = Path(__file__).resolve().parent.parent / "data" / "io.github.joaomgabaldi.Cartridges.metainfo.xml.in"
GPL = "https://www.gnu.org/licenses/gpl-3.0.html"
# Três grupos: Novidades; Solução de problemas; Aviso legal. Sem "Detalhes" (o gabarito não o mostra).
LINHAS = ("linhaNovidades", "linhaProblemas", "linhaLegal")


@pytest.fixture(autouse=True)
def _sem_navegador(monkeypatch):
    """`abrir_url` nunca abre o navegador de verdade: anota."""
    abertos = []
    monkeypatch.setattr(modulo_sobre, "abrir_url", abertos.append)
    return abertos


@pytest.fixture
def area(monkeypatch):
    """A área de transferência falsa: guarda o último texto."""

    class Area:
        texto = None

        def setText(self, texto):  # noqa: N802
            Area.texto = texto

    monkeypatch.setattr(modulo_sobre, "_area_de_transferencia", Area)
    Area.texto = None
    return Area


@pytest.fixture
def janela(app_qt, monkeypatch, tmp_path):  # noqa: ARG001
    log = tmp_path / "cartridges.log"
    log.write_text("linha do log & <b>x</b>\n", encoding="utf-8")
    monkeypatch.setattr(shared, "log_files", [log])
    monkeypatch.setattr(shared, "VERSION", "2026.10.26")
    j = Janela()
    yield j
    j.fechar()


def _clique(janela, nome):
    QMetaObject.invokeMethod(janela.achar(nome), "click", Qt.ConnectionType.DirectConnection)


def _no_sobre(janela, nome):
    """O objeto de dentro do diálogo (o X do cabeçalho existe em vários diálogos)."""
    objeto = achar(janela.achar("dialogoSobre"), nome)
    assert objeto is not None, f"sem objeto {nome!r} no Sobre"
    return objeto


def _clique_real(janela, nome):
    """O gesto de verdade: um clique do mouse no centro do item."""
    item = _no_sobre(janela, nome)
    centro = item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).toPoint()
    QTest.mouseClick(janela.janela, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, centro)


def _abrir(janela):
    janela.sobre.abrir()
    dialogo = janela.achar("dialogoSobre")
    assert esperar(lambda: dialogo.property("visible") is True)
    return dialogo


def test_informacoes_de_depuracao_juntam_os_logs_com_a_linha(tmp_path):
    a = tmp_path / "cartridges.log"
    a.write_text("atual\n", encoding="utf-8")
    b = tmp_path / "cartridges.log.1.xz"
    b.write_bytes(lzma.compress("anterior\n".encode()))
    assert informacoes_de_depuracao([a, b]) == "atual\n" + "─" * 37 + "\n" + "anterior\n"
    assert informacoes_de_depuracao([]) == ""


def test_log_ilegivel_nao_derruba_o_sobre(tmp_path):
    bom = tmp_path / "cartridges.log"
    bom.write_text("ok\n", encoding="utf-8")
    truncado = tmp_path / "cartridges.log.1.xz"
    truncado.write_bytes(lzma.compress(b"x" * 5000)[:-30])
    sumido = tmp_path / "cartridges.log.2"
    texto = informacoes_de_depuracao([bom, truncado, sumido])
    assert "[cartridges.log.1.xz: ilegível]\n" in texto
    assert "[cartridges.log.2: ilegível]\n" in texto
    assert texto.startswith("ok\n")


def test_novidades_da_versao_atual_da_metainfo():
    itens = novidades_da_versao(METAINFO, "2026.10.26")
    assert [i["tipo"] for i in itens] == ["li", "li", "li"]
    assert itens[2]["texto"] == "Foi realizada uma correção de segurança."
    assert itens[0]["texto"] == "Agora é possível arrastar atalhos de jogos para a janela do aplicativo para importá-los."
    assert itens[1]["texto"].startswith("Um jogo adicionado manualmente passa a ser reconhecido")


def test_sem_release_da_versao_nao_mostra_novidades(app_qt, monkeypatch, tmp_path):  # noqa: ARG001
    assert novidades_da_versao(METAINFO, "9.9.9") == []
    assert novidades_da_versao(tmp_path / "nao_existe.xml", "2026.10.26") == []
    monkeypatch.setattr(shared, "VERSION", "9.9.9")
    sobre = Sobre(None)
    sobre.abrir()
    assert sobre.temNovidades is False
    assert sobre.novidades == []
    assert sobre.versao == "9.9.9"


def test_novidades_da_2_0_0_aparecem_no_sobre(app_qt):  # noqa: ARG001
    # Sem trocar `shared.VERSION`: é a versão que o app realmente leva.
    sobre = Sobre(None)
    sobre.abrir()
    assert sobre.temNovidades is True
    assert len(sobre.novidades) >= 1
    # O texto exato é o da 2.0.0, lida pela versão (não pelo topo, que muda a cada subida).
    primeiro = novidades_da_versao(METAINFO, "2.0.0")[0]["texto"]
    assert primeiro == "O Cartridges agora se chama Kyron e tem um ícone novo."


def test_modelo_le_as_novidades_da_versao_ao_abrir(app_qt, monkeypatch):  # noqa: ARG001
    monkeypatch.setattr(shared, "VERSION", "2026.10.26")
    sobre = Sobre(None)
    assert sobre.pagina == "principal"
    assert sobre.aberto is False
    sobre.abrir()
    assert sobre.aberto is True
    assert sobre.temNovidades is True
    assert len(sobre.novidades) == 3


def test_textos_do_sobre_sao_os_da_main():
    """Os textos são os da versão anterior (GTK)."""
    assert modulo_sobre.TITULOS == {
        "principal": "Sobre",
        "novidades": "Novidades",
        "legal": "Aviso legal",
        "problemas": "Solução de problemas",
        "depuracao": "Informações de depuração",
    }
    assert modulo_sobre.COPYRIGHT == "© 2022-2024 kramo\n© 2023 Geoffrey Coulaud\n© 2026 joaomgabaldi"
    assert modulo_sobre.DESENVOLVEDOR == "joaomgabaldi"
    assert modulo_sobre.ABOUT_LICENSE == (
        "Este aplicativo é fornecido sem nenhuma garantia. Veja a "
        '<a href="https://www.gnu.org/licenses/gpl-3.0.html">Licença Pública '
        "Geral GNU, versão 3 ou posterior</a> para mais detalhes."
    )
    assert modulo_sobre.TEXTO_DE_SUPORTE == (
        "As informações de depuração abaixo ajudam a diagnosticar problemas. Inclua-as ao solicitar suporte."
    )
    assert modulo_sobre.NOME_DO_LOG == "cartridges.log"


def test_navegacao_so_aceita_as_cinco_paginas(app_qt):  # noqa: ARG001
    sobre = Sobre(None)
    sobre.abrir()
    sobre.irPara("legal")
    assert sobre.pagina == "legal"
    sobre.irPara("qualquer-coisa")
    assert sobre.pagina == "legal"
    sobre.voltar()
    assert sobre.pagina == "principal"
    sobre.irPara("problemas")
    sobre.irPara("depuracao")
    sobre.voltar()  # o log volta à "Solução de problemas"
    assert sobre.pagina == "problemas"
    sobre.irPara("legal")
    sobre.fechar()
    assert sobre.aberto is False
    sobre.abrir()
    assert sobre.pagina == "principal"


def test_depuracao_e_lida_ao_abrir_a_pagina_de_problemas(app_qt, monkeypatch, tmp_path):  # noqa: ARG001
    log = tmp_path / "cartridges.log"
    log.write_text("um\n", encoding="utf-8")
    monkeypatch.setattr(shared, "log_files", [log])
    sobre = Sobre(None)
    sobre.abrir()
    assert sobre.depuracao == ""
    sobre.irPara("problemas")
    assert sobre.depuracao == ""  # a página de problemas só tem o texto e a linha
    sobre.irPara("depuracao")
    assert sobre.depuracao == "um\n"
    log.write_text("dois\n", encoding="utf-8")
    sobre.irPara("principal")
    sobre.irPara("depuracao")
    assert sobre.depuracao == "dois\n"


def test_link_da_licenca_so_abre_o_endereco_da_gpl(app_qt, _sem_navegador):  # noqa: ARG001
    sobre = Sobre(None)
    sobre.abrirLicenca("https://exemplo.com/outra")
    sobre.abrirLicenca("file:///C:/Windows/notepad.exe")
    sobre.abrirLicenca("")
    assert _sem_navegador == []
    sobre.abrirLicenca(GPL)
    assert _sem_navegador == [GPL]


def test_salvar_como_grava_o_texto(app_qt, tmp_path, monkeypatch):  # noqa: ARG001
    log = tmp_path / "cartridges.log"
    log.write_text("conteúdo ✓\n", encoding="utf-8")
    monkeypatch.setattr(shared, "log_files", [log])
    sobre = Sobre(None)
    sobre.abrir()
    sobre.irPara("depuracao")
    destino = tmp_path / "salvo.log"
    sobre.salvar(QUrl.fromLocalFile(str(destino)))
    assert destino.read_text(encoding="utf-8") == "conteúdo ✓\n"


def test_salvar_sem_url_nao_faz_nada(app_qt, tmp_path):  # noqa: ARG001
    fila = FilaDeAvisos()
    sobre = Sobre(fila)
    sobre.salvar(QUrl())
    assert not (tmp_path / "cartridges.log").exists()
    assert fila.visivel is False


def test_salvar_que_falha_avisa(app_qt, tmp_path):  # noqa: ARG001
    fila = FilaDeAvisos()
    sobre = Sobre(fila)
    sobre.salvar(QUrl.fromLocalFile(str(tmp_path / "pasta" / "inexistente" / "x.log")))
    assert fila.visivel is True
    assert fila.texto == "Não foi possível salvar o arquivo"


def test_copiar_texto_vai_para_a_area_de_transferencia(app_qt, area, tmp_path, monkeypatch):  # noqa: ARG001
    log = tmp_path / "cartridges.log"
    log.write_text("abc\n", encoding="utf-8")
    monkeypatch.setattr(shared, "log_files", [log])
    sobre = Sobre(None)
    sobre.abrir()
    sobre.irPara("depuracao")
    sobre.copiar()
    assert area.texto == "abc\n"


def test_copiar_a_versao_copia_o_numero_e_avisa(app_qt, area, monkeypatch):  # noqa: ARG001
    """O botão da versão copia o número; copiar avisa (em pt-BR)."""
    monkeypatch.setattr(shared, "VERSION", "2026.10.26")
    fila = FilaDeAvisos()
    sobre = Sobre(fila)
    sobre.abrir()
    sobre.copiarVersao()
    assert area.texto == "2026.10.26"
    assert fila.texto == "Copiado para a área de transferência"


def test_item_sobre_no_menu_principal_depois_de_preferencias(janela):
    nomes = avaliar(
        janela.achar("menuPrincipal"),
        "(function() { var r = []; for (var i = 0; i < count; ++i) r.push(itemAt(i).objectName); return r })()",
    ).toVariant()
    assert nomes.index("itemSobre") == nomes.index("itemPreferencias") + 1
    assert janela.achar("itemSobre").property("text") == "Sobre o Kyron"
    _clique(janela, "itemSobre")
    assert janela.sobre.aberto is True
    assert esperar(lambda: janela.achar("dialogoSobre").property("visible") is True)


def test_pagina_principal_mostra_nome_versao_e_linhas(janela):
    _abrir(janela)
    assert janela.achar("nomeDoApp").property("text") == "Kyron"
    assert janela.achar("desenvolvedorDoApp").property("text") == "joaomgabaldi"
    assert janela.achar("versaoDoApp").property("text") == "2026.10.26"
    assert all(janela.achar(n).property("visible") is True for n in LINHAS)
    assert [janela.achar(n).property("titulo") for n in LINHAS] == [
        "Novidades", "Solução de problemas", "Aviso legal",
    ]  # fmt: skip
    # Sem título na principal; "Kyron" só aparece ao rolar (opacidade 0).
    assert janela.achar("tituloDaPaginaDoSobre").property("opacity") == 0


def test_foco_na_ultima_linha_rola_ate_ela_sem_passar_do_fim(janela):
    """A rolagem até o foco para no fim do conteúdo, sem deixar uma faixa vazia embaixo."""
    janela.janela.resize(900, 420)
    esperar(limite=0.3)
    _abrir(janela)
    rolagem = _no_sobre(janela, "rolagemDoSobre")
    assert esperar(lambda: rolagem.property("contentHeight") > rolagem.property("height") + 20)
    avaliar(janela.achar("linhaLegal"), "botaoDaLinha.forceActiveFocus(Qt.TabFocusReason)")
    assert esperar(lambda: rolagem.property("contentY") > 0)
    assert rolagem.property("contentY") <= rolagem.property("contentHeight") - rolagem.property("height") + 0.5


def test_sem_release_da_versao_a_linha_novidades_some(janela, monkeypatch):
    monkeypatch.setattr(shared, "VERSION", "9.9.9")
    _abrir(janela)
    assert janela.achar("linhaNovidades").property("visible") is False
    assert janela.achar("versaoDoApp").property("text") == "9.9.9"


def test_pagina_de_novidades_tem_titulo_versao_e_itens(janela):
    _abrir(janela)
    _clique(janela, "linhaNovidades")
    assert esperar(lambda: janela.sobre.pagina == "novidades")
    assert janela.achar("tituloDaPaginaDoSobre").property("text") == "Novidades"
    assert janela.achar("cabecalhoDaVersao").property("text") == "Versão 2026.10.26"
    assert janela.achar("itemDeNovidade-0").property("text").startswith("Agora é possível arrastar atalhos")
    assert janela.achar("itemDeNovidade-1") is not None


def test_licenca_com_um_unico_link_e_so_ele_abre(janela, _sem_navegador):
    _abrir(janela)
    _clique(janela, "linhaLegal")
    assert esperar(lambda: janela.sobre.pagina == "legal")
    licenca = janela.achar("licencaDoApp")
    # Copyright e licença num único rótulo.
    assert licenca.property("text") == "© 2022-2024 kramo<br>© 2023 Geoffrey Coulaud<br>© 2026 joaomgabaldi<br><br>" + modulo_sobre.ABOUT_LICENSE
    assert avaliar(licenca, "textFormat === Text.StyledText") is True
    avaliar(licenca, 'linkActivated("' + GPL + '")')  # o sinal do Text liga ao `abrirLicenca`
    assert _sem_navegador == [GPL]


def test_link_da_licenca_recebe_foco_pelo_teclado_e_enter_abre(janela, _sem_navegador):
    """O link entra na ordem do Tab, tem borda de foco e o Enter abre só a GPL."""
    _abrir(janela)
    _clique(janela, "linhaLegal")
    assert esperar(lambda: janela.sobre.pagina == "legal")
    licenca = janela.achar("licencaDoApp")
    assert esperar(lambda: janela.achar("botaoVoltarDoSobre").property("activeFocus") is True)
    for _ in range(4):
        if licenca.property("activeFocus") is True:
            break
        QTest.keyClick(janela.janela, Qt.Key.Key_Tab)
    assert licenca.property("activeFocus") is True
    assert esperar(lambda: janela.achar("focoDaLicenca").property("visible") is True)  # o anel entra em 200 ms
    QTest.keyClick(janela.janela, Qt.Key.Key_Return)
    assert _sem_navegador == [GPL]
    # ↑/↓ (o controle) sem outro controle na página: rolam a página (aqui ela cabe) e o foco não é perdido.
    QTest.keyClick(janela.janela, Qt.Key.Key_Down)
    assert licenca.property("activeFocus") is True


def test_paginas_longas_rolam_pelo_teclado(janela):
    """Setas e PageUp/PageDown rolam as páginas fora da principal; Tab e Esc seguem."""
    janela.janela.setHeight(260)
    _abrir(janela)
    _clique(janela, "linhaNovidades")
    assert esperar(lambda: janela.sobre.pagina == "novidades")
    assert esperar(lambda: janela.achar("botaoVoltarDoSobre").property("activeFocus") is True)
    rolagem = janela.achar("rolagemDoSobre")
    assert rolagem.property("contentHeight") > rolagem.property("height")

    QTest.keyClick(janela.janela, Qt.Key.Key_Down)
    assert rolagem.property("contentY") == 40
    QTest.keyClick(janela.janela, Qt.Key.Key_PageDown)
    assert rolagem.property("contentY") > 40
    QTest.keyClick(janela.janela, Qt.Key.Key_PageUp)
    QTest.keyClick(janela.janela, Qt.Key.Key_PageUp)
    assert rolagem.property("contentY") == 0
    QTest.keyClick(janela.janela, Qt.Key.Key_Up)  # não passa do topo
    assert rolagem.property("contentY") == 0
    # Na principal as setas não rolam nada e o Esc continua voltando.
    QTest.keyClick(janela.janela, Qt.Key.Key_Escape)
    assert esperar(lambda: janela.sobre.pagina == "principal")


def test_problemas_mostra_o_log_em_texto_puro_e_os_botoes(janela, area):
    _abrir(janela)
    _clique(janela, "linhaProblemas")
    assert esperar(lambda: janela.sobre.pagina == "problemas")
    assert janela.achar("textoDeSuporte").property("text") == modulo_sobre.TEXTO_DE_SUPORTE
    # O log fica numa página própria, com a barra de baixo.
    assert janela.achar("barraDeAcoesDoSobre").property("visible") is False
    _clique(janela, "linhaDepuracao")
    assert esperar(lambda: janela.sobre.pagina == "depuracao")
    assert janela.achar("tituloDaPaginaDoSobre").property("text") == "Informações de depuração"
    assert janela.achar("barraDeAcoesDoSobre").property("visible") is True
    texto = janela.achar("textoDaDepuracao")
    assert texto.property("text") == "linha do log & <b>x</b>\n"
    assert avaliar(texto, "textFormat === TextEdit.PlainText") is True
    assert janela.achar("textoDaDepuracao").property("readOnly") is True
    assert janela.achar("botaoCopiarTexto").property("text") == "Copiar texto"
    assert janela.achar("botaoSalvarComo").property("text") == "Salvar como…"
    _clique(janela, "botaoCopiarTexto")
    assert area.texto == "linha do log & <b>x</b>\n"
    QTest.keyClick(janela.janela, Qt.Key.Key_Escape)  # o log volta aos problemas, e não à principal
    assert esperar(lambda: janela.sobre.pagina == "problemas")


def test_esc_volta_e_depois_fecha_e_o_foco_volta_a_grade(janela):
    grade = janela.achar("grade")
    grade.forceActiveFocus(Qt.FocusReason.TabFocusReason)
    assert esperar(lambda: grade.property("activeFocus") is True)

    janela.sobre.abrir()
    dialogo = janela.achar("dialogoSobre")
    assert esperar(lambda: dialogo.property("visible") is True)
    assert esperar(lambda: janela.achar("linhaNovidadesBotao").property("activeFocus") is True)  # foco inicial por callLater

    _clique(janela, "linhaLegal")
    assert esperar(lambda: janela.sobre.pagina == "legal")
    assert esperar(lambda: janela.achar("botaoVoltarDoSobre").property("activeFocus") is True)

    QTest.keyClick(janela.janela, Qt.Key.Key_Escape)
    assert esperar(lambda: janela.sobre.pagina == "principal")
    assert janela.sobre.aberto is True

    QTest.keyClick(janela.janela, Qt.Key.Key_Escape)
    assert esperar(lambda: dialogo.property("visible") is False)
    assert janela.sobre.aberto is False
    assert esperar(lambda: grade.property("activeFocus") is True)


def test_tab_circula_dentro_do_sobre(janela):
    _abrir(janela)
    linhas = [janela.achar(n + "Botao") for n in LINHAS]
    assert esperar(lambda: linhas[0].property("activeFocus") is True)
    # Depois da última linha, a ordem da árvore recomeça: o X do cabeçalho, o botão da versão e a primeira linha.
    for esperado in (*linhas[1:], _no_sobre(janela, "fecharDoCabecalho"), _no_sobre(janela, "botaoDaVersao"), linhas[0]):
        QTest.keyClick(janela.janela, Qt.Key.Key_Tab)
        assert esperar(lambda esperado=esperado: esperado.property("activeFocus") is True)
    QTest.keyClick(janela.janela, Qt.Key.Key_Backtab)
    assert _no_sobre(janela, "botaoDaVersao").property("activeFocus") is True


def test_fundo_fica_apagado_com_o_sobre(janela):
    _abrir(janela)
    for nome in ("pagina", "alvoDeSoltar", "botaoMenu", "botaoAdicionar", "botaoBusca", "botaoZerados", "pilha"):
        assert janela.achar(nome).property("enabled") is False, nome
    assert janela.janela.property("popupAberto") is True
    janela.sobre.fechar()
    assert esperar(lambda: janela.achar("pagina").property("enabled") is True)
    assert janela.achar("botaoMenu").property("enabled") is True


def test_o_x_fecha_o_sobre(janela):
    dialogo = _abrir(janela)
    _clique_real(janela, "fecharDoCabecalho")
    assert esperar(lambda: dialogo.property("visible") is False)
    assert janela.sobre.aberto is False


def test_sem_sobre_no_contexto_nao_ha_item_nem_dialogo(app_qt):  # noqa: ARG001
    j = Janela(com_sobre=False)
    try:
        assert j.achar("itemSobre").property("visible") is False
        assert j.janela.property("popupAberto") is False
        assert j.achar("pagina").property("enabled") is True
    finally:
        j.fechar()


def test_anel_de_foco_so_aparece_com_o_teclado_ao_trocar_de_pagina(janela):
    """Entrar numa página pelo mouse não mostra o anel no botão de voltar; pelo teclado, sim."""
    _abrir(janela)
    janela.achar("linhaLegalBotao").forceActiveFocus(Qt.FocusReason.MouseFocusReason)
    _clique(janela, "linhaLegal")
    voltar = janela.achar("botaoVoltarDoSobre")
    assert esperar(lambda: voltar.property("activeFocus") is True)
    assert voltar.property("visualFocus") is False
    QTest.keyClick(janela.janela, Qt.Key.Key_Escape)
    assert esperar(lambda: janela.sobre.pagina == "principal")
    linha = janela.achar("linhaLegalBotao")
    assert esperar(lambda: linha.property("activeFocus") is True)
    _no_sobre(janela, "botaoDaVersao").forceActiveFocus(Qt.FocusReason.TabFocusReason)
    linha.forceActiveFocus(Qt.FocusReason.TabFocusReason)  # o foco veio do teclado: com anel
    QTest.keyClick(janela.janela, Qt.Key.Key_Return)
    assert esperar(lambda: janela.sobre.pagina == "legal")
    assert esperar(lambda: voltar.property("visualFocus") is True)


def test_clique_real_no_botao_da_versao_copia_o_numero_e_avisa(janela, area):
    """O gesto de verdade, o clique do mouse no botão da versão."""
    _abrir(janela)
    _clique_real(janela, "botaoDaVersao")
    assert area.texto == "2026.10.26"
    assert janela.ponte.fila.texto == "Copiado para a área de transferência"


def test_alt_mais_letra_abre_as_linhas_e_aciona_os_botoes(janela, area):
    """Os mnemônicos (N, S, A; I no log; C e S na barra do log), pelo teclado."""
    alt = Qt.KeyboardModifier.AltModifier
    for tecla, pagina in ((Qt.Key.Key_N, "novidades"), (Qt.Key.Key_S, "problemas"), (Qt.Key.Key_A, "legal")):
        _abrir(janela)
        QTest.keyClick(janela.janela, tecla, alt)
        assert esperar(lambda pagina=pagina: janela.sobre.pagina == pagina), pagina
        janela.sobre.fechar()
        assert esperar(lambda: janela.achar("dialogoSobre").property("visible") is False)
    _abrir(janela)
    QTest.keyClick(janela.janela, Qt.Key.Key_S, alt)
    assert esperar(lambda: janela.sobre.pagina == "problemas")
    QTest.keyClick(janela.janela, Qt.Key.Key_I, alt)  # "Informações de depuração": a primeira letra
    assert esperar(lambda: janela.sobre.pagina == "depuracao")
    QTest.keyClick(janela.janela, Qt.Key.Key_C, alt)  # "Copiar texto"
    assert area.texto == "linha do log & <b>x</b>\n"


def test_alt_seguro_sublinha_o_mnemonico(janela):
    """Enquanto o Alt está seguro, a primeira letra dos rótulos aparece sublinhada."""
    _abrir(janela)
    rotulo = achar(janela.achar("dialogoSobre"), "linhaNovidadesRotulo")
    assert rotulo.property("text") == "Novidades"
    QTest.keyPress(janela.janela, Qt.Key.Key_Alt)
    assert esperar(lambda: rotulo.property("text") == "<u>N</u>ovidades")
    QTest.keyRelease(janela.janela, Qt.Key.Key_Alt)
    assert esperar(lambda: rotulo.property("text") == "Novidades")
    _clique(janela, "linhaProblemas")
    _clique(janela, "linhaDepuracao")
    assert esperar(lambda: janela.sobre.pagina == "depuracao")
    QTest.keyPress(janela.janela, Qt.Key.Key_Alt)
    assert esperar(lambda: janela.achar("botaoCopiarTexto").property("sublinharPrimeira") is True)
    QTest.keyRelease(janela.janela, Qt.Key.Key_Alt)


def test_setas_andam_pelas_linhas_da_principal(janela):
    """↓ e ↑ (o direcional do controle) levam o foco de linha em linha, sem rolar nem dar a volta."""
    _abrir(janela)
    linhas = [janela.achar(n + "Botao") for n in LINHAS]
    versao = _no_sobre(janela, "botaoDaVersao")
    versao.forceActiveFocus(Qt.FocusReason.TabFocusReason)
    for esperado in linhas:
        QTest.keyClick(janela.janela, Qt.Key.Key_Down)
        assert esperar(lambda esperado=esperado: esperado.property("activeFocus") is True)
    for esperado in (*reversed(linhas[:-1]), versao):
        QTest.keyClick(janela.janela, Qt.Key.Key_Up)
        assert esperar(lambda esperado=esperado: esperado.property("activeFocus") is True)


def test_seta_para_baixo_chega_a_linha_do_log_e_ao_link_da_licenca(janela):
    """Nas subpáginas, ↓ do "Voltar" alcança o que a página tem (a linha do log, o link da licença)."""
    _abrir(janela)
    _clique(janela, "linhaProblemas")
    assert esperar(lambda: janela.achar("botaoVoltarDoSobre").property("activeFocus") is True)
    QTest.keyClick(janela.janela, Qt.Key.Key_Down)
    assert esperar(lambda: janela.achar("linhaDepuracaoBotao").property("activeFocus") is True)
    QTest.keyClick(janela.janela, Qt.Key.Key_Return)
    assert esperar(lambda: janela.sobre.pagina == "depuracao")
    QTest.keyClick(janela.janela, Qt.Key.Key_Escape)
    assert esperar(lambda: janela.sobre.pagina == "problemas")
    QTest.keyClick(janela.janela, Qt.Key.Key_Escape)
    assert esperar(lambda: janela.sobre.pagina == "principal")
    _clique(janela, "linhaLegal")
    assert esperar(lambda: janela.achar("botaoVoltarDoSobre").property("activeFocus") is True)
    QTest.keyClick(janela.janela, Qt.Key.Key_Down)
    assert esperar(lambda: janela.achar("licencaDoApp").property("activeFocus") is True)


def test_o_cartao_nao_encolhe_nas_subpaginas_e_a_capsula_tem_30_px(janela):
    """A altura do cartão é a da principal em toda página; a cápsula da versão é `padding 3` sobre `min-height 24`."""
    _abrir(janela)
    cartao = achar(janela.achar("dialogoSobre"), "cartaoDoDialogo")
    assert esperar(lambda: cartao.property("height") > 300)
    altura = cartao.property("height")
    assert _no_sobre(janela, "botaoDaVersao").property("height") == 30
    for destino in ("linhaLegal", "linhaProblemas"):
        _clique(janela, destino)
        assert esperar(lambda: janela.sobre.pagina != "principal")
        QTest.qWait(50)
        assert cartao.property("height") == altura
        QTest.keyClick(janela.janela, Qt.Key.Key_Escape)
        assert esperar(lambda: janela.sobre.pagina == "principal")


def test_alt_seta_esquerda_volta_com_o_foco_na_linha_e_o_anel(janela):
    _abrir(janela)
    voltar = janela.achar("botaoVoltarDoSobre")
    assert voltar.property("estilo") == "plano"
    _clique(janela, "linhaLegal")
    assert esperar(lambda: janela.sobre.pagina == "legal")
    assert esperar(lambda: voltar.property("activeFocus") is True)
    QTest.keyClick(janela.janela, Qt.Key.Key_Left, Qt.KeyboardModifier.AltModifier)
    assert esperar(lambda: janela.sobre.pagina == "principal")
    linha = janela.achar("linhaLegalBotao")
    assert esperar(lambda: linha.property("activeFocus") is True)
    assert linha.property("visualFocus") is True
    # Na principal o atalho não faz nada.
    QTest.keyClick(janela.janela, Qt.Key.Key_Left, Qt.KeyboardModifier.AltModifier)
    assert janela.sobre.pagina == "principal"
