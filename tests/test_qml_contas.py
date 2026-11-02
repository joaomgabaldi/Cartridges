# test_qml_contas.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O grupo das contas e a janela de login numa janela de teste (QML offscreen, D61).

Nenhuma delas tem lugar no app até o plano 7 (Preferências); aqui as duas ficam numa janela só, com um
`ContasDasLojas` de verdade e o `abrir` do navegador sempre falso.
"""

from pathlib import Path

import pytest
from PySide6.QtCore import QMetaObject, Qt, QUrl
from PySide6.QtQml import QQmlComponent, QQmlEngine, QQmlExpression
from PySide6.QtQuick import QQuickWindow
from PySide6.QtTest import QTest

from cartridges.conquistas.ea import conta as ea_conta
from cartridges.conquistas.epic import conta as epic_conta
from cartridges.conquistas.xbox import conta as xbox_conta
from cartridges.modelos.contas import ContasDasLojas
from tests.apoio_qml_biblioteca import _achar, _esperar

QML = Path(__file__).resolve().parent.parent / "cartridges" / "qml"
_COD = "0123456789abcdef0123456789abcdef"
_CURL = "curl 'https://accounts.ea.com/connect/auth' -H 'cookie: remid=AAA; _nx_mpcid=BBB'"

# O arquivo é fictício: serve só para a janela de teste herdar os tipos e o `Tema` do diretório.
_FONTE = b"""
import QtQuick
import QtQuick.Window

Window {
    width: 720; height: 760; visible: true
    color: Tema.fundo
    Item {
        anchors.fill: parent
        GrupoDasContas { objectName: "grupo"; contas: contasDeTeste; x: 24; y: 24; width: parent.width - 48 }
        JanelaDeLogin { objectName: "janelaEpic"; login: contasDeTeste.loginEpic }
        JanelaDeLogin { objectName: "janelaEa"; login: contasDeTeste.loginEa }
    }
}
"""


def _sincrono(trabalho, entregar):
    entregar(trabalho())


class _Tela:
    def __init__(self, avisos, abrir=lambda _url: None, em_thread=_sincrono):
        self.contas = ContasDasLojas(avisos, em_thread=em_thread, abrir=abrir)
        self.motor = QQmlEngine()
        from cartridges.modelos.provedor_de_icones import ProvedorDeIcones  # noqa: PLC0415
        self.motor.addImageProvider("icone", ProvedorDeIcones())
        self.motor.rootContext().setContextProperty("contasDeTeste", self.contas)
        componente = QQmlComponent(self.motor)
        componente.setData(_FONTE, QUrl.fromLocalFile(str(QML / "_contas.qml")))
        self.janela = componente.create()
        assert self.janela is not None, componente.errorString()
        self.componente = componente
        self.janela.requestActivate()
        _esperar()

    def achar(self, nome, dentro=None):
        objeto = _achar(dentro or self.janela, nome)
        assert objeto is not None, f"sem objeto {nome!r}"
        return objeto

    def clicar(self, nome):
        QMetaObject.invokeMethod(self.achar(nome), "click", Qt.ConnectionType.DirectConnection)
        _esperar()

    def fechar(self):
        self.contas.fechar()
        self.janela.close()
        self.janela.deleteLater()


@pytest.fixture
def desconectadas(monkeypatch):
    for modulo in (xbox_conta, epic_conta, ea_conta):
        monkeypatch.setattr(modulo, "conectada", lambda: False)


@pytest.fixture
def tela(desconectadas, avisos):  # noqa: ARG001
    t = _Tela(avisos)
    yield t
    t.fechar()


def _valor(objeto, expressao):
    return QQmlExpression(QQmlEngine.contextForObject(objeto), objeto, expressao).evaluate()[0]


def test_grupo_tem_os_textos_da_main(tela):
    assert tela.achar("tituloDoGrupoDasContas").property("text") == "Contas"
    assert tela.achar("descricaoDoGrupoDasContas").property("text") == (
        "Entre com as contas das lojas para acompanhar as conquistas dos jogos do Xbox, "
        "do Game Pass, da Epic Games Store e do EA app."
    )
    for chave, titulo in (("microsoft", "Conta Microsoft"), ("epic", "Conta Epic"), ("ea", "Conta EA")):
        assert tela.achar(f"tituloDaConta_{chave}").property("text") == titulo
        assert tela.achar(f"subtituloDaConta_{chave}").property("text") == "Não conectada"
        assert tela.achar(f"botaoDaConta_{chave}").property("text") == "Entrar"


def test_as_tres_linhas_estao_na_ordem_e_o_botao_a_direita(tela):
    topos = [tela.achar(f"botaoDaConta_{c}").mapToScene(tela.achar(f"botaoDaConta_{c}").boundingRect().center()) for c in ("microsoft", "epic", "ea")]
    assert topos[0].y() < topos[1].y() < topos[2].y()
    grupo = tela.achar("grupo")
    assert topos[0].x() > grupo.x() + grupo.width() / 2


def test_nome_da_conta_em_texto_puro(monkeypatch, desconectadas, avisos):
    monkeypatch.setattr(epic_conta, "conectada", lambda: True)
    monkeypatch.setattr(epic_conta, "nome", lambda: "A & B <i>")
    t = _Tela(avisos)
    try:
        subtitulo = t.achar("subtituloDaConta_epic")
        assert subtitulo.property("text") == "A & B <i>"
        assert _valor(subtitulo, "textFormat") == 0  # Text.PlainText
        assert t.achar("botaoDaConta_epic").property("text") == "Sair"
    finally:
        t.fechar()


def test_entrar_da_epic_abre_a_janela_com_o_campo_de_uma_linha(tela):
    janela = tela.achar("janelaEpic")
    assert janela.property("visible") is False
    tela.clicar("botaoDaConta_epic")
    assert _esperar(lambda: janela.property("visible") is True)
    assert tela.achar("tituloDoLogin", janela).property("text") == "Entrar na conta Epic"
    assert tela.achar("passosDoLogin", janela).property("text") == "\n".join(
        (
            "1. Entre na sua conta na página que foi aberta no navegador.",
            '2. Copie o código exibido em "authorizationCode".',
            "3. Cole o código abaixo.",
        )
    )
    assert tela.achar("rotuloDoCampoDoLogin", janela).property("text") == "Código de autorização"
    assert tela.achar("campoDeUmaLinha", janela).property("visible") is True
    assert tela.achar("campoDeVariasLinhas", janela).property("visible") is False
    assert tela.achar("botaoDaPaginaDoLogin", janela).property("text") == "Abrir a página novamente"
    assert tela.achar("botaoCancelarLogin", janela).property("text") == "Cancelar"
    assert tela.achar("botaoConectarLogin", janela).property("text") == "Conectar"
    assert tela.achar("janelaEa").property("visible") is False


def test_janela_aberta_e_modal_para_o_mouse(tela):
    """O fundo escurece e o resto da janela não recebe clique: o botão de trás, sob a janela, não faz nada."""
    tela.clicar("botaoDaConta_epic")
    janela = tela.achar("janelaEpic")
    assert _esperar(lambda: janela.property("visible") is True)
    atras = tela.achar("botaoDaConta_ea")
    ponto = atras.mapToScene(atras.boundingRect().center()).toPoint()
    QTest.mouseClick(tela.janela, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, ponto)
    _esperar()
    assert tela.contas.loginEa is None
    assert tela.contas.loginEpic is not None


def _luminancia(cor):
    def canal(i):
        c = int(cor[1 + 2 * i : 3 + 2 * i], 16) / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    return 0.2126 * canal(0) + 0.7152 * canal(1) + 0.0722 * canal(2)


def _contraste(a, b):
    claro, escuro = sorted((_luminancia(a), _luminancia(b)), reverse=True)
    return (claro + 0.05) / (escuro + 0.05)


def test_erro_do_tema_tem_contraste_nos_dois_temas():
    """O texto de erro da janela de login passa de 4,5:1 sobre o fundo, no escuro e no claro."""
    import re  # noqa: PLC0415

    tema = (QML / "Tema.qml").read_text(encoding="utf-8")
    erro = re.search(r'property color erro: escuro \? "(#\w{6})" : "(#\w{6})"', tema)
    fundo = re.search(r'property color fundo: escuro \? "(#\w{6})" : "(#\w{6})"', tema)
    assert erro and fundo
    assert _contraste(erro.group(1), fundo.group(1)) >= 4.5
    assert _contraste(erro.group(2), fundo.group(2)) >= 4.5
    assert "color: Tema.erro" in (QML / "JanelaDeLogin.qml").read_text(encoding="utf-8")


def test_janela_da_ea_tem_varias_linhas(tela):
    tela.clicar("botaoDaConta_ea")
    janela = tela.achar("janelaEa")
    assert _esperar(lambda: janela.property("visible") is True)
    assert tela.achar("tituloDoLogin", janela).property("text") == "Entrar na conta EA"
    assert tela.achar("rotuloDoCampoDoLogin", janela).property("text") == "Texto copiado do navegador"
    area = tela.achar("rolagemDoLogin", janela)
    assert tela.achar("campoDeVariasLinhas", janela).property("visible") is True
    assert tela.achar("campoDeUmaLinha", janela).property("visible") is False
    assert area.property("height") >= 160
    assert tela.achar("botaoDaPaginaDoLogin", janela).property("text") == "Abrir a página da conta"
    assert tela.achar("enderecoDoLogin", janela).property("visible") is False


def test_conectar_apagado_sem_texto_valido(tela):
    tela.clicar("botaoDaConta_epic")
    janela = tela.achar("janelaEpic")
    botao = tela.achar("botaoConectarLogin", janela)
    assert botao.property("enabled") is False
    tela.achar("campoDeUmaLinha", janela).setProperty("text", "lixo")
    assert tela.contas.loginEpic.texto == "lixo"  # o que se digita vai ao modelo
    assert botao.property("enabled") is False
    tela.achar("campoDeUmaLinha", janela).setProperty("text", _COD)
    assert _esperar(lambda: botao.property("enabled") is True)


def test_texto_do_modelo_aparece_no_campo(tela):
    """Recusa limpa o texto no modelo: o campo acompanha."""
    tela.clicar("botaoDaConta_ea")
    janela = tela.achar("janelaEa")
    tela.contas.loginEa.texto = _CURL
    assert _esperar(lambda: tela.achar("campoDeVariasLinhas", janela).property("text") == _CURL)
    tela.contas.loginEa.texto = ""
    assert _esperar(lambda: tela.achar("campoDeVariasLinhas", janela).property("text") == "")


def test_colar_curl_longo_nao_e_cortado(tela):
    """O campo de uma linha escondido tem limite de 32767 caracteres: não pode devolver ao modelo o texto cortado."""
    tela.clicar("botaoDaConta_ea")
    janela = tela.achar("janelaEa")
    longo = "a" * 40000
    tela.achar("campoDeVariasLinhas", janela).setProperty("text", longo)
    assert _esperar(lambda: tela.contas.loginEa.texto == longo)
    QTest.qWait(50)
    assert len(tela.contas.loginEa.texto) == 40000
    assert len(tela.achar("campoDeVariasLinhas", janela).property("text")) == 40000


def test_enter_conecta_na_epic(tela, monkeypatch):
    recebidos = []
    monkeypatch.setattr(epic_conta, "conectar", recebidos.append)
    tela.clicar("botaoDaConta_epic")
    janela = tela.achar("janelaEpic")
    campo = tela.achar("campoDeUmaLinha", janela)
    assert _esperar(lambda: campo.property("activeFocus") is True)
    campo.setProperty("text", _COD)

    QTest.keyClick(tela.janela, Qt.Key.Key_Return)

    assert _esperar(lambda: recebidos == [_COD])
    assert _esperar(lambda: janela.property("visible") is False)  # conectou: a janela se fechou


def test_enter_com_texto_invalido_nao_conecta(tela, monkeypatch):
    recebidos = []
    monkeypatch.setattr(epic_conta, "conectar", recebidos.append)
    tela.clicar("botaoDaConta_epic")
    campo = tela.achar("campoDeUmaLinha", tela.achar("janelaEpic"))
    assert _esperar(lambda: campo.property("activeFocus") is True)
    campo.setProperty("text", "lixo")
    QTest.keyClick(tela.janela, Qt.Key.Key_Return)
    _esperar()
    assert recebidos == []


def test_esc_fecha_a_janela(tela):
    tela.clicar("botaoDaConta_epic")
    janela = tela.achar("janelaEpic")
    assert _esperar(lambda: janela.property("visible") is True)

    QTest.keyClick(tela.janela, Qt.Key.Key_Escape)

    assert _esperar(lambda: janela.property("visible") is False)
    assert tela.contas.loginEpic is None


def test_cancelar_fecha_a_janela(tela):
    tela.clicar("botaoDaConta_ea")
    janela = tela.achar("janelaEa")
    QMetaObject.invokeMethod(tela.achar("botaoCancelarLogin", janela), "click", Qt.ConnectionType.DirectConnection)
    assert _esperar(lambda: janela.property("visible") is False)


def test_conectar_recusado_mostra_o_erro_em_vermelho_e_limpa(tela, monkeypatch):
    def recusa(_codigo):
        raise epic_conta.CodigoRecusado()

    monkeypatch.setattr(epic_conta, "conectar", recusa)
    tela.clicar("botaoDaConta_epic")
    janela = tela.achar("janelaEpic")
    campo = tela.achar("campoDeUmaLinha", janela)
    campo.setProperty("text", _COD)
    QMetaObject.invokeMethod(tela.achar("botaoConectarLogin", janela), "click", Qt.ConnectionType.DirectConnection)
    erro = tela.achar("erroDoLogin", janela)
    assert _esperar(lambda: erro.property("visible") is True)
    assert erro.property("text") == "O código não foi aceito. Gere um novo código na página da Epic e tente novamente."
    assert _valor(erro, "textFormat") == 0
    assert _esperar(lambda: campo.property("text") == "")
    assert janela.property("visible") is True


def test_erro_e_endereco_aparecem_sem_navegador(desconectadas, avisos):
    def sem_navegador(_url):
        raise OSError("sem navegador")

    t = _Tela(avisos, abrir=sem_navegador)
    try:
        t.clicar("botaoDaConta_epic")
        janela = t.achar("janelaEpic")
        erro = t.achar("erroDoLogin", janela)
        endereco = t.achar("enderecoDoLogin", janela)
        assert _esperar(lambda: erro.property("visible") is True)
        assert erro.property("text") == "Não foi possível abrir o navegador. Copie o endereço abaixo e abra-o no navegador."
        assert endereco.property("visible") is True
        assert endereco.property("text") == epic_conta.PAGINA_DE_LOGIN
        assert endereco.property("readOnly") is True and endereco.property("selectByMouse") is True
        assert _valor(endereco, "textFormat") == 0
    finally:
        t.fechar()


def test_erro_sem_navegador_da_ea_nao_mostra_endereco(desconectadas, avisos):
    def sem_navegador(_url):
        raise OSError("sem navegador")

    t = _Tela(avisos, abrir=sem_navegador)
    try:
        t.clicar("botaoDaConta_ea")
        janela = t.achar("janelaEa")
        erro = t.achar("erroDoLogin", janela)
        assert _esperar(lambda: erro.property("visible") is True)
        assert erro.property("text") == "Não foi possível abrir o navegador. Acesse ea.com/login manualmente."
        assert t.achar("enderecoDoLogin", janela).property("visible") is False
    finally:
        t.fechar()


def test_ocupada_mostra_o_indicador_e_apaga_o_campo(desconectadas, avisos, monkeypatch):
    monkeypatch.setattr(epic_conta, "conectar", lambda _c: None)
    pendente = []  # a troca fica na rede: o `em_thread` do teste só anota
    t = _Tela(avisos, em_thread=lambda trabalho, entregar: pendente.append((trabalho, entregar)))
    try:
        t.clicar("botaoDaConta_epic")
        janela = t.achar("janelaEpic")
        t.achar("campoDeUmaLinha", janela).setProperty("text", _COD)
        QMetaObject.invokeMethod(t.achar("botaoConectarLogin", janela), "click", Qt.ConnectionType.DirectConnection)
        indicador = t.achar("indicadorDoLogin", janela)
        assert _esperar(lambda: indicador.property("visible") is True)
        assert t.achar("campoDeUmaLinha", janela).property("enabled") is False
        assert t.achar("botaoConectarLogin", janela).property("enabled") is False
        assert t.achar("botaoDaPaginaDoLogin", janela).property("enabled") is False
        assert t.achar("botaoCancelarLogin", janela).property("enabled") is True
    finally:
        t.fechar()


def test_a_janela_fechada_por_fora_some_sem_levantar(tela):
    tela.clicar("botaoDaConta_epic")
    janela = tela.achar("janelaEpic")
    assert _esperar(lambda: janela.property("visible") is True)
    tela.contas.fechar()
    assert _esperar(lambda: janela.property("visible") is False)
    assert isinstance(tela.janela, QQuickWindow)


# -- Auditoria GTK x Qt, pacote E --------------------------------------------------------------------


def _y(item, raiz):
    return item.mapToItem(raiz, 0, 0).y()


def test_login_tem_cabecalho_com_titulo_centrado_e_x(tela):
    """L1: faixa de 47 com o título em heading centrado e o X circular, como o `Adw.HeaderBar` da `main`."""
    tela.clicar("botaoDaConta_epic")
    janela = tela.achar("janelaEpic")
    assert _esperar(lambda: janela.property("visible") is True)
    cartao = tela.achar("cartaoDoDialogo", janela)
    titulo = tela.achar("tituloDoLogin", janela)
    assert titulo.property("text") == "Entrar na conta Epic"
    assert _valor(titulo, "font.pixelSize") == 12 and _valor(titulo, "font.weight") == 700
    assert titulo.parentItem().height() == 47
    # O centro do título é o do cabeçalho (no offscreen a fonte de reserva é larga e os botões podem alargar a coluna).
    cabecalho = titulo.parentItem()
    assert abs(titulo.x() + titulo.width() / 2 - cabecalho.width() / 2) <= 1
    assert cartao.width() == 460
    assert _valor(cartao, "radius") == 15
    x = tela.achar("fecharDoCabecalho", janela)  # o X de verdade, com o mouse
    QTest.mouseClick(tela.janela, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, x.mapToScene(x.boundingRect().center()).toPoint())
    assert _esperar(lambda: janela.property("visible") is False)
    assert tela.contas.loginEpic is None


def test_login_da_epic_usa_a_linha_de_texto_numa_lista(tela):
    """L2/L3/L7: o código vai numa `Adw.EntryRow` de lista com borda, com o rótulo flutuando dentro; 18 entre os blocos."""
    tela.clicar("botaoDaConta_epic")
    janela = tela.achar("janelaEpic")
    assert _esperar(lambda: janela.property("visible") is True)
    campo = tela.achar("campoDeUmaLinha", janela)
    assert campo.property("titulo") == "Código de autorização"
    assert campo.property("alturaMinima") == 50
    assert tela.achar("rotuloDoCampoDoLogin", janela).property("visible") is False  # o rótulo é o da fileira
    passos = tela.achar("passosDoLogin", janela)
    cartao = tela.achar("cartaoDoDialogo", janela)
    lista = campo.parentItem().parentItem()  # a coluna do `GrupoDeLinhas` e o grupo
    assert _y(lista, cartao) - (_y(passos, cartao) + passos.height()) == 18
    assert _valor(passos, "font.pixelSize") == 12
    assert _valor(tela.achar("botaoCancelarLogin", janela), "estilo") == "normal"
    # O corpo: 12 em cima do cabeçalho, 24 dos lados.
    assert _y(passos, cartao) == 47 + 12
    assert passos.mapToItem(cartao, 0, 0).x() == 24


def test_login_da_ea_tem_o_texto_na_moldura_da_main_e_12_entre_blocos(tela):
    """L3/L4: `TextView` em moldura de 1 px a 15%, fundo da vista, margens 6, quebra por palavra, sem anel de foco."""
    tela.clicar("botaoDaConta_ea")
    janela = tela.achar("janelaEa")
    assert _esperar(lambda: janela.property("visible") is True)
    area = tela.achar("rolagemDoLogin", janela)
    assert _valor(area, "border.width") == 1 and _valor(area, "radius") == 0
    assert _valor(area, "color") == _valor(area, "Tema.vista") and _valor(area, "border.color") == _valor(area, "Tema.borda")
    campo = tela.achar("campoDeVariasLinhas", janela)
    assert campo.property("padding") == 6
    assert _valor(campo, "wrapMode === TextArea.Wrap") is True
    assert _valor(campo, "font.pixelSize") == 12
    cartao = tela.achar("cartaoDoDialogo", janela)
    rotulo = tela.achar("rotuloDoCampoDoLogin", janela)
    assert rotulo.property("visible") is True and _valor(rotulo, "font.weight") == 700
    passos = tela.achar("passosDoLogin", janela)
    assert _y(rotulo, cartao) - (_y(passos, cartao) + passos.height()) == 12


def test_botoes_e_indicador_do_login_seguem_a_main(tela):
    """L5/L8: botões da `main` (34, 12 px em negrito, "Conectar" em destaque) e o `Adw.Spinner` de 16 px."""
    tela.clicar("botaoDaConta_epic")
    janela = tela.achar("janelaEpic")
    assert _esperar(lambda: janela.property("visible") is True)
    for nome, estilo in (("botaoDaPaginaDoLogin", "normal"), ("botaoCancelarLogin", "normal"), ("botaoConectarLogin", "sugestao")):
        botao = tela.achar(nome, janela)
        assert botao.height() == 34 and _valor(botao, "estilo") == estilo, nome
    indicador = tela.achar("indicadorDoLogin", janela)
    assert (_valor(indicador, "implicitWidth"), _valor(indicador, "implicitHeight")) == (16, 16)
    assert _valor(indicador, "objectName") == "indicadorDoLogin" and _valor(indicador, "grossura") == pytest.approx(1.6)


def test_endereco_da_epic_em_cor_normal_do_texto(desconectadas, avisos):
    """L7: o endereço mostrado sem navegador usa a cor do texto, não a secundária."""

    def sem_navegador(_url):
        raise OSError("sem navegador")

    t = _Tela(avisos, abrir=sem_navegador)
    try:
        t.clicar("botaoDaConta_epic")
        janela = t.achar("janelaEpic")
        endereco = t.achar("enderecoDoLogin", janela)
        assert _esperar(lambda: endereco.property("visible") is True)
        assert _valor(endereco, "color") == _valor(endereco, "Tema.texto")
    finally:
        t.fechar()


def test_login_abre_com_o_foco_no_campo_sem_anel(tela):
    """L9: medido num `Adw.Dialog` com o mesmo corpo, o foco cai no campo (Epic: o texto da fileira; EA: o `TextView`), sem
    anel de foco (a `TextView` não tem) e, na Epic, o contorno da fileira."""
    tela.clicar("botaoDaConta_epic")
    campo = tela.achar("campoDeUmaLinha", tela.achar("janelaEpic"))
    assert _esperar(lambda: campo.property("activeFocus") is True)
    assert _valor(campo, "foco") is True  # a fileira acende o contorno do campo, como a `EntryRow` com foco
    tela.clicar("botaoDaConta_ea")
    area = tela.achar("campoDeVariasLinhas", tela.achar("janelaEa"))
    assert _esperar(lambda: area.property("activeFocus") is True)


def test_grupo_das_contas_segue_as_medidas_da_main(tela):
    """C1: título e descrição de 12 (a descrição apagada), fileira de 54 com título 12 e subtítulo 10, margem de 14."""
    titulo = tela.achar("tituloDoGrupoDasContas")
    assert _valor(titulo, "font.pixelSize") == 12 and _valor(titulo, "font.weight") == 700
    descricao = tela.achar("descricaoDoGrupoDasContas")
    assert _valor(descricao, "font.pixelSize") == 12 and _valor(descricao, "color.toString()") == _valor(descricao, "Tema.textoSecundario.toString()")
    for chave in ("microsoft", "epic", "ea"):
        assert _valor(tela.achar(f"tituloDaConta_{chave}"), "font.pixelSize") == 12
        assert _valor(tela.achar(f"subtituloDaConta_{chave}"), "font.pixelSize") == 10
        botao = tela.achar(f"botaoDaConta_{chave}")
        assert botao.height() == 34 and _valor(botao, "estilo") == "normal"
    linha = tela.achar("tituloDaConta_microsoft").parentItem().parentItem()
    assert linha.height() == 54
    assert tela.achar("tituloDaConta_microsoft").mapToItem(linha, 0, 0).x() == 14
    assert _valor(tela.achar("tituloDaConta_microsoft").parentItem(), "spacing") == 3
    botao = tela.achar("botaoDaConta_microsoft")
    assert linha.width() - (botao.mapToItem(linha, 0, 0).x() + botao.width()) == 14


def test_nome_longo_da_conta_quebra_a_linha_e_alarga_a_fileira(monkeypatch, desconectadas, avisos):
    """C2: o subtítulo quebra (o `AdwActionRow` faz o mesmo); a altura acompanha o conteúdo."""
    nome = "Uma conta com um nome muito comprido que não cabe em uma linha só " * 2
    monkeypatch.setattr(epic_conta, "conectada", lambda: True)
    monkeypatch.setattr(epic_conta, "nome", lambda: nome)
    t = _Tela(avisos)
    try:
        subtitulo = t.achar("subtituloDaConta_epic")
        assert subtitulo.property("lineCount") > 1
        assert subtitulo.property("text") == nome  # inteiro, sem corte
        linha = subtitulo.parentItem().parentItem()
        assert linha.height() > 54
        assert t.achar("tituloDaConta_microsoft").parentItem().parentItem().height() == 54
    finally:
        t.fechar()
