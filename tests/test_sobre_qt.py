# test_sobre_qt.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O "Sobre o Cartridges" (D84): as funções puras, o `Sobre` e o `DialogoSobre.qml` no `Aplicativo.qml` inteiro.

Nada de verdade: os logs são arquivos do `tmp_path`, a área de transferência e o navegador são falsos, e o
`FileDialog` do "Salvar como…" nunca abre (o teste chama o `salvar(url)` direto).
"""

import lzma
from pathlib import Path

import pytest
from PySide6.QtCore import QMetaObject, Qt, QUrl
from PySide6.QtTest import QTest

from cartridges import shared
from cartridges.modelos import sobre as modulo_sobre
from cartridges.modelos.avisos import FilaDeAvisos
from cartridges.modelos.sobre import Sobre, descricao_do_app, informacoes_de_depuracao, novidades_da_versao
from tests.apoio_janela_atualizacao import Janela, avaliar, esperar

METAINFO = Path(__file__).resolve().parent.parent / "data" / "io.github.joaomgabaldi.Cartridges.metainfo.xml.in"
GPL = "https://www.gnu.org/licenses/gpl-3.0.html"
LINHAS = ("linhaNovidades", "linhaDetalhes", "linhaCreditos", "linhaLegal", "linhaProblemas")


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
    assert [i["tipo"] for i in itens] == ["li", "li"]
    assert itens[0]["texto"] == "Agora é possível arrastar atalhos de jogos para a janela do aplicativo para importá-los."
    assert itens[1]["texto"].startswith("Um jogo adicionado manualmente passa a ser reconhecido")


def test_sem_release_da_versao_nao_mostra_novidades(app_qt, monkeypatch, tmp_path):  # noqa: ARG001
    assert novidades_da_versao(METAINFO, "2.0.0") == []
    assert novidades_da_versao(tmp_path / "nao_existe.xml", "2026.10.26") == []
    monkeypatch.setattr(shared, "VERSION", "2.0.0")
    sobre = Sobre(None)
    sobre.abrir()
    assert sobre.temNovidades is False
    assert sobre.novidades == []
    assert sobre.versao == "2.0.0"


def test_modelo_le_as_novidades_da_versao_ao_abrir(app_qt, monkeypatch):  # noqa: ARG001
    monkeypatch.setattr(shared, "VERSION", "2026.10.26")
    sobre = Sobre(None)
    assert sobre.pagina == "principal"
    assert sobre.aberto is False
    sobre.abrir()
    assert sobre.aberto is True
    assert sobre.temNovidades is True
    assert len(sobre.novidades) == 2


def test_detalhes_sao_a_descricao_da_metainfo(app_qt):  # noqa: ARG001
    paragrafos = descricao_do_app(METAINFO)
    assert len(paragrafos) == 1
    assert paragrafos[0].startswith("O Cartridges é um lançador simples para todos os seus jogos.")
    assert Sobre(None).detalhes == paragrafos


def test_textos_do_sobre_sao_os_da_main():
    """Conferidos contra `git show main:cartridges/main.py` (ABOUT_*, on_about_action, ABOUT_DIALOG_STRINGS)."""
    assert modulo_sobre.TITULOS == {
        "principal": "Sobre",
        "novidades": "Novidades",
        "detalhes": "Detalhes",
        "creditos": "Créditos",
        "legal": "Aviso legal",
        "problemas": "Solução de problemas",
    }
    assert modulo_sobre.ABOUT_THANKS_TITLE == "O autor original agradece às pessoas abaixo pelas suas contribuições:"
    assert modulo_sobre.COPYRIGHT == "© 2022-2024 kramo\n© 2026 joaomgabaldi"
    assert modulo_sobre.DESENVOLVEDOR == "joaomgabaldi"
    assert modulo_sobre.ABOUT_LICENSE == (
        "Este aplicativo é fornecido sem nenhuma garantia. Veja a "
        '<a href="https://www.gnu.org/licenses/gpl-3.0.html">Licença Pública '
        "Geral GNU, versão 3 ou posterior</a> para mais detalhes."
    )
    assert modulo_sobre.CREDITOS == [
        {"titulo": "", "nomes": ["Copyright (C) 2022-2024 kramo", "Copyright (C) 2026 joaomgabaldi"]},
        {
            "titulo": modulo_sobre.ABOUT_THANKS_TITLE,
            "nomes": [
                "Geoffrey Coulaud", "Rilic", "Arcitec", "Paweł Lidwin", "Domenico", "Rafael Mardojai CM",
                "Clara Hobbs", "Sabri Ünal",
            ],
        },
    ]  # fmt: skip
    assert modulo_sobre.TEXTO_DE_SUPORTE == (
        "As informações de depuração abaixo ajudam a diagnosticar problemas. Inclua-as ao solicitar suporte."
    )
    assert modulo_sobre.NOME_DO_LOG == "cartridges.log"


def test_navegacao_so_aceita_as_seis_paginas(app_qt):  # noqa: ARG001
    sobre = Sobre(None)
    sobre.abrir()
    sobre.irPara("creditos")
    assert sobre.pagina == "creditos"
    sobre.irPara("qualquer-coisa")
    assert sobre.pagina == "creditos"
    sobre.voltar()
    assert sobre.pagina == "principal"
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
    assert sobre.depuracao == "um\n"
    log.write_text("dois\n", encoding="utf-8")
    sobre.irPara("principal")
    sobre.irPara("problemas")
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
    sobre.irPara("problemas")
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
    sobre.irPara("problemas")
    sobre.copiar()
    assert area.texto == "abc\n"


def test_item_sobre_no_menu_principal_depois_de_preferencias(janela):
    nomes = avaliar(
        janela.achar("menuPrincipal"),
        "(function() { var r = []; for (var i = 0; i < count; ++i) r.push(itemAt(i).objectName); return r })()",
    ).toVariant()
    assert nomes.index("itemSobre") == nomes.index("itemPreferencias") + 1
    assert janela.achar("itemSobre").property("text") == "Sobre o Cartridges"
    _clique(janela, "itemSobre")
    assert janela.sobre.aberto is True
    assert esperar(lambda: janela.achar("dialogoSobre").property("visible") is True)


def test_pagina_principal_mostra_nome_versao_e_linhas(janela):
    _abrir(janela)
    assert janela.achar("nomeDoApp").property("text") == "Cartridges"
    assert janela.achar("desenvolvedorDoApp").property("text") == "joaomgabaldi"
    assert janela.achar("versaoDoApp").property("text") == "2026.10.26"
    assert all(janela.achar(n).property("visible") is True for n in LINHAS)
    assert [janela.achar(n).property("text") for n in LINHAS] == [
        "Novidades", "Detalhes", "Créditos", "Aviso legal", "Solução de problemas",
    ]  # fmt: skip


def test_sem_release_da_versao_a_linha_novidades_some(janela, monkeypatch):
    monkeypatch.setattr(shared, "VERSION", "2.0.0")
    _abrir(janela)
    assert janela.achar("linhaNovidades").property("visible") is False
    assert janela.achar("versaoDoApp").property("text") == "2.0.0"


def test_pagina_de_novidades_tem_titulo_versao_e_itens(janela):
    _abrir(janela)
    _clique(janela, "linhaNovidades")
    assert esperar(lambda: janela.sobre.pagina == "novidades")
    assert janela.achar("tituloDaPaginaDoSobre").property("text") == "Novidades"
    assert janela.achar("cabecalhoDaVersao").property("text") == "Versão 2026.10.26"
    assert janela.achar("itemDeNovidade-0").property("text").startswith("Agora é possível arrastar atalhos")
    assert janela.achar("itemDeNovidade-1") is not None


def test_creditos_em_texto_puro_e_com_os_oito_nomes(janela):
    _abrir(janela)
    _clique(janela, "linhaCreditos")
    assert esperar(lambda: janela.sobre.pagina == "creditos")
    assert janela.achar("tituloDaPaginaDoSobre").property("text") == "Créditos"
    agradecimento = janela.achar("tituloDosAgradecimentos")
    assert agradecimento.property("text") == modulo_sobre.ABOUT_THANKS_TITLE
    assert avaliar(agradecimento, "wrapMode !== Text.NoWrap") is True  # quebra linha, sem "…"
    assert avaliar(agradecimento, "elide === Text.ElideNone") is True
    assert janela.achar("nomeDoCredito-Sabri Ünal") is not None


def test_licenca_com_um_unico_link_e_so_ele_abre(janela, _sem_navegador):
    _abrir(janela)
    _clique(janela, "linhaLegal")
    assert esperar(lambda: janela.sobre.pagina == "legal")
    assert janela.achar("copyrightDoApp").property("text") == "© 2022-2024 kramo\n© 2026 joaomgabaldi"
    licenca = janela.achar("licencaDoApp")
    assert licenca.property("text") == modulo_sobre.ABOUT_LICENSE
    assert avaliar(licenca, "textFormat === Text.StyledText") is True
    avaliar(licenca, 'linkActivated("' + GPL + '")')  # o sinal do Text liga ao `abrirLicenca`
    assert _sem_navegador == [GPL]


def test_problemas_mostra_o_log_em_texto_puro_e_os_botoes(janela, area):
    _abrir(janela)
    _clique(janela, "linhaProblemas")
    assert esperar(lambda: janela.sobre.pagina == "problemas")
    assert janela.achar("textoDeSuporte").property("text") == modulo_sobre.TEXTO_DE_SUPORTE
    texto = janela.achar("textoDaDepuracao")
    assert texto.property("text") == "linha do log & <b>x</b>\n"
    assert avaliar(texto, "textFormat === Text.PlainText") is True
    assert janela.achar("botaoCopiarTexto").property("text") == "Copiar texto"
    assert janela.achar("botaoSalvarComo").property("text") == "Salvar como…"
    _clique(janela, "botaoCopiarTexto")
    assert area.texto == "linha do log & <b>x</b>\n"


def test_esc_volta_e_depois_fecha_e_o_foco_volta_a_grade(janela):
    grade = janela.achar("grade")
    grade.forceActiveFocus(Qt.FocusReason.TabFocusReason)
    assert esperar(lambda: grade.property("activeFocus") is True)

    janela.sobre.abrir()
    dialogo = janela.achar("dialogoSobre")
    assert esperar(lambda: dialogo.property("visible") is True)
    assert esperar(lambda: janela.achar("linhaNovidades").property("activeFocus") is True)  # foco inicial por callLater

    _clique(janela, "linhaCreditos")
    assert esperar(lambda: janela.sobre.pagina == "creditos")
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
    linhas = [janela.achar(n) for n in LINHAS]
    assert esperar(lambda: linhas[0].property("activeFocus") is True)
    for esperado in (*linhas[1:], janela.achar("botaoFecharDoSobre"), linhas[0]):
        QTest.keyClick(janela.janela, Qt.Key.Key_Tab)
        assert esperar(lambda esperado=esperado: esperado.property("activeFocus") is True)
    QTest.keyClick(janela.janela, Qt.Key.Key_Backtab)
    assert janela.achar("botaoFecharDoSobre").property("activeFocus") is True


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
    _clique(janela, "botaoFecharDoSobre")
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
