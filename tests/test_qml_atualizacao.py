# test_qml_atualizacao.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A pergunta da versão nova e o "Baixando atualização…" na camada dos avisos (D82), no `Aplicativo.qml` inteiro.

Nada de verdade: o `download_installer` é falso (espera o Cancelar), o `_abrir_instalador` é o guarda
`sem_instalador_de_verdade` e a pergunta é feita direto no atualizador (sem rede, sem checagem).
"""

import pytest
from PySide6.QtCore import QMetaObject, Qt
from PySide6.QtTest import QTest

from cartridges import shared
from cartridges.utils import app_updater
from cartridges.utils.app_updater import AppUpdater, DownloadCancelled, Release
from tests.apoio_janela_atualizacao import Janela, avaliar, esperar
from tests.apoio_qml_biblioteca import _achar

_NOTAS = "## Novidades\n- **a** & <b>x</b>\n- `b`"
_RELEASE = Release("2026.09.30", _NOTAS, "https://x/setup.exe", 10, "ab")


@pytest.fixture
def janela(app_qt, monkeypatch, sem_instalador_de_verdade):  # noqa: ARG001
    j = Janela()
    monkeypatch.setattr(shared, "aplicativo", j.aplicativo, raising=False)
    monkeypatch.setattr(AppUpdater, "_ocupado", staticmethod(lambda: False))
    yield j
    j.atualizador.stop()
    j.fechar()


@pytest.fixture
def download_falso(monkeypatch):
    """O download espera o Cancelar (ou o `stop()`); nunca fala com a rede nem grava nada."""
    chamadas = []

    def falso(release, target, progress, cancelled):  # noqa: ARG001
        chamadas.append(release)
        while not cancelled.wait(0.01):
            pass
        raise DownloadCancelled

    monkeypatch.setattr(app_updater, "download_installer", falso)
    return chamadas


def _perguntar(janela):
    janela.atualizador._ask(_RELEASE)  # noqa: SLF001
    dialogo = janela.achar("dialogoDaAtualizacao")
    assert esperar(lambda: dialogo.property("visible") is True)
    return dialogo


def _clique(janela, nome):
    QMetaObject.invokeMethod(janela.achar(nome), "click", Qt.ConnectionType.DirectConnection)


def test_pergunta_mostra_versao_corpo_e_notas(janela):
    dialogo = _perguntar(janela)
    assert janela.achar("tituloDaAtualizacao").property("text") == "Nova versão disponível: 2026.09.30"
    assert janela.achar("corpoDaAtualizacao").property("text") == (
        "Deseja baixar e instalar a atualização agora? O aplicativo será fechado durante a instalação."
    )
    notas = janela.achar("notasDaAtualizacao")
    # O que veio da release (`&`, `<b>`) chega escapado; as tags que sobram são só as do `notes_to_markup`.
    assert notas.property("text") == "<b>Novidades</b><br>• <b>a</b> &amp; &lt;b&gt;x&lt;/b&gt;<br>• <tt>b</tt>"
    assert avaliar(notas, "textFormat === Text.RichText") is True
    assert janela.achar("botaoAgoraNao").property("text") == "Agora não"
    assert janela.achar("botaoAtualizar").property("text") == "Atualizar"
    assert _achar(dialogo, "botaoCancelarAtualizacao") is None  # na pergunta, esse botão não existe
    assert janela.achar("barraDaAtualizacao").property("visible") is False
    # Entra na conta do diálogo aberto: o fundo não aceita atalhos arrastados nem a barra, cliques.
    assert janela.achar("camadaDeAvisos").property("dialogoAberto") is True
    assert janela.achar("alvoDeSoltar").property("enabled") is False
    assert dialogo.property("baixando") is False


def test_foco_inicial_em_agora_nao_e_tab_circula(janela):
    _perguntar(janela)
    assert esperar(lambda: janela.achar("botaoAgoraNao").property("activeFocus") is True)
    QTest.keyClick(janela.janela, Qt.Key.Key_Tab)
    assert janela.achar("botaoAtualizar").property("activeFocus") is True
    QTest.keyClick(janela.janela, Qt.Key.Key_Tab)
    assert janela.achar("botaoAgoraNao").property("activeFocus") is True
    QTest.keyClick(janela.janela, Qt.Key.Key_Backtab)
    assert janela.achar("botaoAtualizar").property("activeFocus") is True


def test_enter_na_pergunta_nao_comeca_o_download(janela, download_falso):
    """Review Focus 1: a caixa aparece sem ser pedida; um Enter perdido nunca começa o download."""
    dialogo = _perguntar(janela)
    # Com o foco inicial (em "Agora não"), Enter só fecha a pergunta.
    assert esperar(lambda: janela.achar("botaoAgoraNao").property("activeFocus") is True)
    QTest.keyClick(janela.janela, Qt.Key.Key_Return)
    assert esperar(lambda: dialogo.property("visible") is False)
    assert janela.atualizador.baixando is False
    assert download_falso == []


def test_esc_na_pergunta_e_agora_nao(janela, download_falso):
    dialogo = _perguntar(janela)
    QTest.keyClick(janela.janela, Qt.Key.Key_Escape)
    assert esperar(lambda: dialogo.property("visible") is False)
    assert janela.atualizador.pergunta == {}
    assert download_falso == []
    # "Agora não" não grava nada: a próxima checagem pode perguntar de novo.
    janela.atualizador._ask(_RELEASE)  # noqa: SLF001
    assert esperar(lambda: dialogo.property("visible") is True)


def test_atualizar_mostra_a_barra_e_cancelar_fecha(janela, download_falso):
    dialogo = _perguntar(janela)
    _clique(janela, "botaoAtualizar")
    assert esperar(lambda: dialogo.property("baixando") is True)
    assert dialogo.property("visible") is True
    assert janela.achar("tituloDaAtualizacao").property("text") == "Baixando atualização…"
    assert janela.achar("barraDaAtualizacao").property("visible") is True
    assert _achar(dialogo, "botaoAtualizar") is None  # no download, só "Cancelar"
    assert janela.achar("porcentagemDaAtualizacao").property("text") == "0%"
    assert esperar(lambda: janela.achar("botaoCancelarAtualizacao").property("activeFocus") is True)
    assert download_falso == [_RELEASE]

    janela.atualizador._atualizar_progresso(0.5, janela.atualizador._cancel)  # noqa: SLF001
    assert janela.achar("porcentagemDaAtualizacao").property("text") == "50%"
    assert janela.achar("barraDaAtualizacao").property("value") == 0.5

    _clique(janela, "botaoCancelarAtualizacao")
    assert esperar(lambda: dialogo.property("visible") is False)
    assert janela.atualizador.baixando is False
    assert janela.atualizador._cancel.is_set()  # noqa: SLF001


def test_esc_no_download_e_cancelar(janela, download_falso):  # noqa: ARG001
    dialogo = _perguntar(janela)
    _clique(janela, "botaoAtualizar")
    assert esperar(lambda: dialogo.property("baixando") is True)
    QTest.keyClick(janela.janela, Qt.Key.Key_Escape)
    assert esperar(lambda: dialogo.property("visible") is False)
    assert janela.atualizador._cancel.is_set()  # noqa: SLF001


def test_pergunta_fica_por_cima_das_preferencias(janela):
    assert janela.preferencias.abrir("general")
    prefs = janela.achar("dialogoDePreferencias")
    assert esperar(lambda: prefs.property("visible") is True)

    dialogo = _perguntar(janela)
    assert prefs.property("visible") is True and dialogo.property("visible") is True
    # Só o de cima recebe o teclado: Tab circula dentro da pergunta e Esc fecha só ela.
    assert esperar(lambda: janela.foco_dentro_de("dialogoDaAtualizacao"))
    for _ in range(3):
        QTest.keyClick(janela.janela, Qt.Key.Key_Tab)
        assert janela.foco_dentro_de("dialogoDaAtualizacao")
    QTest.keyClick(janela.janela, Qt.Key.Key_Escape)
    assert esperar(lambda: dialogo.property("visible") is False)
    assert janela.preferencias.aberto is True
    assert prefs.property("visible") is True


def test_confirmacao_que_chega_com_a_pergunta_na_tela_fica_por_cima_e_leva_o_teclado(janela):
    """R5: pilha. A pergunta fica por baixo, à vista; Esc e Enter são da confirmação, e depois o foco volta a "Agora não"."""
    respostas = []
    dialogo = _perguntar(janela)
    assert esperar(lambda: janela.achar("botaoAgoraNao").property("activeFocus") is True)

    janela.aplicativo.pedir_confirmacao("Restaurar?", "Corpo", "Restaurar", respostas.append)
    confirmacao = janela.achar("confirmacaoDoApp")
    assert esperar(lambda: confirmacao.property("visible") is True)
    assert dialogo.property("visible") is True
    assert confirmacao.property("z") > dialogo.property("z")
    assert esperar(lambda: janela.foco_dentro_de("confirmacaoDoApp"))
    # A pergunta continua pendente; Esc responde "não" à confirmação, não a ela.
    assert janela.atualizador.pergunta != {}
    QTest.keyClick(janela.janela, Qt.Key.Key_Escape)
    assert esperar(lambda: confirmacao.property("visible") is False)
    assert respostas == [False]

    assert esperar(lambda: janela.achar("botaoAgoraNao").property("activeFocus") is True)
    assert janela.atualizador.pergunta != {} and janela.atualizador.baixando is False


def test_a_pergunta_abre_por_cima_de_outro_dialogo(janela):
    """B04: como o `dialog.present` da `main`, nada de esperar o outro fechar."""
    janela.aplicativo.pedir_confirmacao("Restaurar?", "Corpo", "Restaurar", lambda _ok: None)
    confirmacao = janela.achar("confirmacaoDoApp")
    assert esperar(lambda: confirmacao.property("visible") is True)
    dialogo = _perguntar(janela)
    assert dialogo.property("z") > confirmacao.property("z")
    assert esperar(lambda: janela.achar("botaoAgoraNao").property("activeFocus") is True)


def test_dialogo_de_erros_que_chega_durante_o_download_nao_cancela_nada(janela, download_falso):  # noqa: ARG001
    dialogo = _perguntar(janela)
    _clique(janela, "botaoAtualizar")
    assert esperar(lambda: dialogo.property("baixando") is True)
    fechados = []
    janela.aplicativo.pedir_dialogo("Aviso", "Corpo", [], lambda: fechados.append(1))
    erros = janela.achar("dialogoDeErros")
    assert esperar(lambda: erros.property("visible") is True)
    assert erros.property("z") > dialogo.property("z")
    assert esperar(lambda: janela.foco_dentro_de("dialogoDeErros"))
    QTest.keyClick(janela.janela, Qt.Key.Key_Escape)  # fecha o diálogo de erros, não cancela o download
    assert esperar(lambda: erros.property("visible") is False)
    assert fechados == [1]
    assert janela.atualizador.baixando is True and not janela.atualizador._cancel.is_set()  # noqa: SLF001
    assert dialogo.property("visible") is True


def test_o_dialogo_nao_aparece_sem_atualizador_no_contexto(app_qt):  # noqa: ARG001
    j = Janela(com_atualizador=False)
    try:
        assert j.achar("dialogoDaAtualizacao").property("visible") is False
    finally:
        j.fechar()


@pytest.mark.parametrize("tecla", [None, Qt.Key.Key_Escape])
def test_ao_fechar_a_pergunta_o_foco_volta_a_grade(janela, tecla):
    """Review final, M1: o foco volta à grade (não à janela) depois de "Agora não" e do Esc."""
    grade = janela.achar("grade")
    # Sem nada focado (a janela aberta e parada): o retorno capturado é o conteúdo da janela, não a grade.
    grade.forceActiveFocus(Qt.FocusReason.TabFocusReason)
    avaliar(janela.janela, "activeFocusItem.focus = false; contentItem.forceActiveFocus(); 1")
    assert grade.property("activeFocus") is False
    dialogo = _perguntar(janela)
    assert esperar(lambda: janela.achar("botaoAgoraNao").property("activeFocus") is True)
    if tecla is None:
        _clique(janela, "botaoAgoraNao")
    else:
        QTest.keyClick(janela.janela, tecla)
    assert esperar(lambda: dialogo.property("visible") is False)
    assert esperar(lambda: grade.property("activeFocus") is True)


def test_pergunta_respondida_com_outro_dialogo_aberto_nao_devolve_o_foco(janela):
    """A pergunta coberta por uma confirmação, respondida de fora: o foco segue na confirmação, não volta a quem a abriu."""
    dialogo = _perguntar(janela)
    assert dialogo.property("retorno") is not None
    janela.aplicativo.pedir_confirmacao("Restaurar?", "Corpo", "Restaurar", lambda _ok: None)
    confirmacao = janela.achar("confirmacaoDoApp")
    assert esperar(lambda: confirmacao.property("visible") is True)
    assert esperar(lambda: janela.foco_dentro_de("confirmacaoDoApp"))
    janela.atualizador.responder(False)
    assert esperar(lambda: janela.atualizador.pergunta == {})
    assert janela.foco_dentro_de("confirmacaoDoApp")
