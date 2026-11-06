# test_assistente.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O assistente da primeira abertura: o `Assistente` sem tela e a `JanelaDoAssistente.qml` aberta pelo
`app._mostrar_assistente`, com o `_abrir` e o `_restaurar_e_abrir` espiões.

Nada de verdade: fitas, nuvem da Tuya, navegador, rede e monitores são os falsos do `conftest`; o backup é validado e
agendado por funções falsas; o seletor de arquivos nunca abre (o teste chama o slot com a URL).
"""

import os
import subprocess
import sys
import types
import uuid
import winreg
from pathlib import Path

import pytest
from PySide6.QtCore import Q_ARG, QMetaObject, QPointF, Qt, QUrl
from PySide6.QtTest import QTest

from kyron import app as modulo_app
from kyron import assistente as modulo
from kyron import shared
from kyron.assistente import Assistente
from kyron.conquistas.epic import conta as epic_conta
from kyron.modelos import big_picture
from kyron.utils import backup, session_fita, window_geometry
from tests.apoio_janela_atualizacao import achar, avaliar, esperar
from tests.apoio_registro import _apagar_chave

RAIZ = Path(__file__).resolve().parent.parent
_COD = "0123456789abcdef0123456789abcdef"


@pytest.fixture(autouse=True)
def _sem_monitores(monkeypatch):
    # Quem precisa de monitores sobrescreve.
    monkeypatch.setattr(window_geometry, "monitores_da_sessao", lambda: [])


@pytest.fixture(autouse=True)
def _sem_a_barra_do_qwindowkit(monkeypatch):
    # Sem a ponte do QWindowKit a janela fica com a moldura nativa (`comAgente` não existe).
    monkeypatch.setattr(modulo_app, "_com_barra_propria", lambda _motor: None)


@pytest.fixture(autouse=True)
def _com_animacoes(monkeypatch):
    # Quem precisa sem animações sobrescreve.
    monkeypatch.setattr(modulo, "_animacoes_do_sistema", lambda: True)


@pytest.fixture(autouse=True)
def _store_de_volta(monkeypatch):
    # O `_mostrar_assistente` troca a store.
    monkeypatch.setattr(shared, "store", None, raising=False)
    monkeypatch.setattr(shared, "aplicativo", None, raising=False)


@pytest.fixture(autouse=True)
def _sem_navegador(monkeypatch):
    abertos = []
    monkeypatch.setattr(modulo.open_uri, "abrir_url", abertos.append)
    return abertos


def _assistente():
    terminou, restaurou = [], []
    assistente = Assistente(ao_terminar=lambda: terminou.append(1), ao_restaurar=lambda: restaurou.append(1))
    return assistente, terminou, restaurou


@pytest.fixture
def sincrono(monkeypatch):
    """A thread do backup e a entrega na principal viram chamadas diretas; os diálogos pedidos ficam anotados."""
    monkeypatch.setattr(modulo, "_em_thread", lambda tarefa: tarefa())
    monkeypatch.setattr(modulo, "na_thread_principal", lambda funcao, *args: funcao(*args))


def _dialogos(assistente):
    pedidos = []
    assistente.dialogoPedido.connect(lambda titulo, corpo: pedidos.append((titulo, corpo)))
    return pedidos


class _Janela:
    """A `JanelaDoAssistente.qml` aberta pelo `app._mostrar_assistente`, com o `_abrir` e o `_restaurar_e_abrir` espiões."""

    def __init__(self, app_qt, monkeypatch, abrir=None, restaurar=None):
        self.eventos = []
        self.abertura = modulo_app._Abertura()  # noqa: SLF001

        def abrir_espiao(_app, _argv, abertura):
            self.eventos.append(("abrir", self.raiz.isVisible()))
            if abrir is not None:
                return abrir(abertura)
            return None

        def restaurar_espiao(_app, _argv, _abertura):
            self.eventos.append(("restaurar", self.raiz.isVisible()))
            if restaurar is not None:
                restaurar()

        monkeypatch.setattr(modulo_app, "_abrir", abrir_espiao)
        monkeypatch.setattr(modulo_app, "_restaurar_e_abrir", restaurar_espiao)
        monkeypatch.setattr(modulo_app, "_avisos_da_abertura", lambda *_a: self.eventos.append("avisos"))
        self.saidas = []
        monkeypatch.setattr(modulo_app.QGuiApplication, "exit", staticmethod(self.saidas.append))
        assert modulo_app._mostrar_assistente(app_qt, ["kyron"], self.abertura) is True  # noqa: SLF001
        self.motor = self.abertura.assistente
        self.raiz = self.motor.rootObjects()[0]
        self.modelo = self.motor.rootContext().contextProperty("assistente")
        esperar()

    def achar(self, nome):
        return achar(self.raiz, nome)

    def pagina(self):
        return self.modelo.paginas[self.modelo.indice]

    def ir_para(self, nome):
        for _ in range(len(self.modelo.paginas)):
            if self.pagina() == nome:
                break
            self.modelo.avancar()
        assert self.pagina() == nome, "a página não apareceu no assistente"
        esperar()

    def fechar(self):
        self.raiz.close()
        self.motor.deleteLater()
        esperar(limite=0.05)


@pytest.fixture
def janela(app_qt, monkeypatch):
    j = _Janela(app_qt, monkeypatch)
    yield j
    j.fechar()


def _clicar(item):
    QMetaObject.invokeMethod(item, "click", Qt.ConnectionType.DirectConnection)


# -- quando mostrar ---------------------------------------------------------------------------------------------------


def test_mostra_com_biblioteca_vazia(schema):
    assert modulo.precisa_mostrar() is True
    assert schema.get_boolean("assistente-concluido") is False


def test_com_jogos_marca_e_nao_mostra(schema, app_dirs):
    (app_dirs.games / "1.json").write_text("{}")
    assert modulo.precisa_mostrar() is False
    assert schema.get_boolean("assistente-concluido") is True


def test_concluido_nao_mostra(schema):
    schema.set_boolean("assistente-concluido", True)
    assert modulo.precisa_mostrar() is False


# -- concluir ---------------------------------------------------------------------------------------------------------


def test_concluir_chama_ao_terminar_antes_de_destruir(app_qt, monkeypatch):
    """A biblioteca abre com o assistente ainda na tela; só depois ele fecha (o app nunca fica sem janela)."""
    j = _Janela(app_qt, monkeypatch)
    try:
        j.modelo.concluir()
        assert j.eventos == [("abrir", True), "avisos"]
        assert esperar(lambda: not j.raiz.isVisible())
    finally:
        j.fechar()


def test_concluir_destroi_a_janela_mesmo_se_ao_terminar_falhar(app_qt, monkeypatch, caplog):
    def quebra(_abertura):
        raise RuntimeError("falha de teste")

    j = _Janela(app_qt, monkeypatch, abrir=quebra)
    try:
        j.modelo.concluir()
        assert esperar(lambda: not j.raiz.isVisible())
        assert j.saidas == [1]
        assert "falha de teste" in caplog.text
    finally:
        j.fechar()


def test_concluir_marca_e_chama_ao_terminar(schema):
    assistente, terminou, _ = _assistente()
    assistente.concluir()
    assert schema.get_boolean("assistente-concluido") is True and terminou == [1]
    assistente.concluir()  # um segundo clique não abre a biblioteca duas vezes
    assert terminou == [1]


def test_concluir_abre_a_biblioteca_e_fecha_o_assistente(app_qt, monkeypatch, schema):
    """"Abrir a biblioteca" na última tela abre a principal e o assistente sai."""
    j = _Janela(app_qt, monkeypatch, abrir=lambda abertura: setattr(abertura, "aplicativo", object()))
    try:
        j.ir_para("pronto")
        _clicar(j.achar("botaoAbrirBiblioteca"))
        assert j.eventos == [("abrir", True), "avisos"]
        assert schema.get_boolean("assistente-concluido") is True
        assert esperar(lambda: not j.raiz.isVisible())
        assert j.saidas == []
    finally:
        j.fechar()


def test_concluir_cancela_logins(monkeypatch):
    assistente, _, _ = _assistente()
    fechados = []
    monkeypatch.setattr(assistente.contas, "fechar", lambda: fechados.append(1))
    assistente.concluir()
    assert fechados == [1]


# -- a pasta, as chaves e os interruptores ---------------------------------------------------------------------------


def test_pasta_grava_e_liga_importacao_e_a_ultima_vale(schema, tmp_path):
    assistente, _, _ = _assistente()
    assistente.escolherPasta(QUrl.fromLocalFile(str(tmp_path / "a")))
    assistente.escolherPasta(QUrl.fromLocalFile(str(tmp_path / "b")))
    assert schema.get_string("shortcuts-location") == str(tmp_path / "b")
    assert schema.get_boolean("auto-import") is True
    assert assistente.subtituloDaPasta == str(tmp_path / "b").replace("/", "\\")
    assistente.escolherPasta(QUrl())  # o seletor cancelado não muda nada
    assert schema.get_string("shortcuts-location") == str(tmp_path / "b")


def test_subtitulo_da_pasta_com_e_comercial(janela, schema):
    """Um "&" no caminho aparece como está, em texto puro."""
    janela.modelo.escolherPasta(QUrl.fromLocalFile("D:/Jogos & Cia"))
    assert janela.modelo.subtituloDaPasta == "D:\\Jogos & Cia"
    esperar()
    subtitulo = janela.achar("linhaDaPastaSubtitulo")
    assert subtitulo.property("text") == "D:\\Jogos & Cia"
    assert avaliar(subtitulo, "textFormat === Text.PlainText") is True


def test_chave_sgdb_liga_e_apagar_desliga(janela, schema):
    janela.modelo.definirChaveSgdb("  k  ")
    assert schema.get_string("sgdb-key") == "k" and schema.get_boolean("sgdb") is True
    janela.ir_para("capas")
    assert janela.achar("linhaCapasAnimadas").isVisible()
    janela.modelo.definirChaveSgdb("")
    esperar()
    assert schema.get_boolean("sgdb") is False
    assert not janela.achar("linhaCapasAnimadas").isVisible()


def test_capas_animadas_grava_as_duas_chaves(schema):
    assistente, _, _ = _assistente()
    assistente.definirChaveSgdb("k")
    assistente.definirCapasAnimadas(True)
    assert schema.get_boolean("sgdb-animated") and schema.get_boolean("cover-autoplay")
    assert assistente.capasAnimadas is True


def test_sem_pasta_o_subtitulo_avisa():
    assistente, _, _ = _assistente()
    assert assistente.subtituloDaPasta == "Nenhuma pasta selecionada"


def test_chave_steam_grava_sem_espacos(schema):
    assistente, _, _ = _assistente()
    assistente.definirChaveSteam("  abc  ")
    assert schema.get_string("conquistas-chave-steam") == "abc"


def test_campos_nascem_com_o_que_ja_esta_gravado(schema, app_qt, monkeypatch):
    schema.set_string("sgdb-key", "k")
    schema.set_boolean("sgdb-animated", True)
    schema.set_string("conquistas-chave-steam", "s")
    schema.set_boolean("big-picture-ao-conectar", True)
    j = _Janela(app_qt, monkeypatch)
    try:
        assert j.modelo.chaveSgdb == "k" and j.modelo.capasAnimadas is True
        assert j.modelo.chaveSteam == "s" and j.modelo.bigPictureAoConectar is True
        assert j.achar("linhaDaChaveSgdb").property("text") == "k"
        assert j.achar("linhaCapasAnimadas").property("checked") is True
        assert j.achar("linhaDaChaveDaSteam").property("text") == "s"
        assert j.achar("linhaBigPicture").property("checked") is True
    finally:
        j.fechar()


def test_interruptores_gravam(schema):
    assistente, _, _ = _assistente()
    assistente.definir("big-picture-ao-conectar", True)
    assistente.definir("session-move-window", True)
    assistente.definir("session-wallpaper", True)
    assert schema.get_boolean("big-picture-ao-conectar")
    assert schema.get_boolean("session-move-window")
    assert schema.get_boolean("session-wallpaper")
    assert assistente.bigPictureAoConectar and assistente.moverJanela and assistente.papelDeParede


def test_definir_chave_fora_da_lista_e_ignorado(schema, caplog):
    assistente, _, _ = _assistente()
    assistente.definir("session-fita", True)
    assistente.definir("assistente-concluido", True)
    assert schema.get_boolean("session-fita") is False
    assert schema.get_boolean("assistente-concluido") is False
    assert "session-fita" in caplog.text


def test_monitores_gravam_a_escolha_ao_montar(schema, monkeypatch):
    dois = [
        window_geometry.Monitor(r"\\.\DISPLAY2", 1920, 0, 1920, 1080, False, 2, r"\\?\DISPLAY#FALSO#2"),
        window_geometry.Monitor(r"\\.\DISPLAY3", 3840, 0, 1920, 1080, False, 3, r"\\?\DISPLAY#FALSO#3"),
    ]
    monkeypatch.setattr(window_geometry, "monitores_da_sessao", lambda: dois)
    assistente, _, _ = _assistente()
    # Nada escolhido ainda: o primeiro da lista vale e é gravado, para a lista mostrar o que vai acontecer.
    assert schema.get_string("session-monitor") == dois[0].key
    assert assistente.monitores == ["Monitor 2", "Monitor 3"] and assistente.monitorEscolhido == 0
    assistente.escolherMonitor(1)
    assert schema.get_string("session-monitor") == dois[1].key and assistente.monitorEscolhido == 1
    assistente.escolherMonitor(7)  # fora da lista: nada
    assert schema.get_string("session-monitor") == dois[1].key


# -- as telas ---------------------------------------------------------------------------------------------------------


def test_navegacao_e_rodape():
    assistente, _, _ = _assistente()
    assert len(assistente.paginas) == 8
    assert not assistente.rodapeVisivel
    assistente.avancar()
    assert assistente.rodapeVisivel
    assistente.voltar()
    assert not assistente.rodapeVisivel
    assistente.voltar()  # antes da primeira: nada
    assert assistente.indice == 0
    for _ in range(10):
        assistente.avancar()
    assert assistente.indice == len(assistente.paginas) - 1 and not assistente.rodapeVisivel


def test_textos_das_telas(janela):
    def texto(nome):
        return janela.achar(nome).property("text")

    def titulo(nome):
        return janela.achar(nome).property("titulo")

    assert janela.raiz.title() == "Kyron"
    assert texto("titulo_boas_vindas") == "Boas-vindas ao Kyron"
    assert texto("descricao_boas_vindas") == (
        "Reúna os seus jogos em uma única biblioteca, com capas, tempo de jogo e "
        "conquistas. Configure o essencial em poucos passos."
    )
    assert texto("botaoComecar") == "Começar"
    assert texto("botaoRestaurar") == "Restaurar um backup"
    assert texto("botaoPularConfiguracao") == "Pular configuração"
    assert texto("titulo_jogos") == "Seus jogos"
    assert texto("descricao_jogos") == (
        "O Kyron adiciona à biblioteca os jogos cujos atalhos estão em uma pasta. "
        "Escolha a pasta onde estão, ou onde ficarão, os atalhos dos seus jogos. Novos "
        "atalhos colocados nela aparecem na biblioteca sempre que o aplicativo é aberto."
    )
    assert titulo("linhaDaPasta") == "Pasta"
    assert janela.achar("linhaDaPasta").property("rotulo") == "Escolher"
    assert texto("titulo_capas") == "Capas e logos"
    assert texto("descricao_capas") == (
        "O SteamGridDB fornece capas e logos para os seus jogos. Para usá-lo, informe "
        "uma chave da API."
    )
    assert titulo("linhaDaChaveSgdb") == "Chave da API"
    assert titulo("linhaCapasAnimadas") == "Capas animadas"
    assert texto("titulo_conquistas") == "Conquistas"
    assert texto("descricao_conquistas") == (
        "Entre com as contas das lojas para acompanhar as conquistas dos seus jogos."
    )
    assert janela.achar("grupoDaChaveDaSteam").property("titulo") == "Steam Web API"
    assert titulo("linhaDaChaveDaSteam") == "Chave da API"
    assert texto("titulo_iluminacao") == "Iluminação inteligente"
    assert texto("descricao_iluminacao") == (
        "O Kyron pode mudar a cor dos seus dispositivos de iluminação compatíveis "
        "com a Tuya de acordo com o jogo em execução."
    )
    assert texto("botaoConfigurar") == "Configurar"
    assert texto("titulo_controle") == "Controle"
    assert texto("descricao_controle") == (
        "O Kyron pode abrir o Big Picture automaticamente quando um controle é conectado."
    )
    assert titulo("linhaBigPicture") == "Abrir o Big Picture ao conectar um controle"
    assert janela.achar("linhaBigPicture").property("subtitulo") == (
        "Abre o Big Picture ao iniciar o aplicativo com um controle conectado ou ao conectar um controle na biblioteca"
    )
    assert texto("titulo_monitores") == "Outros monitores"
    assert texto("descricao_monitores") == "Escolha o que o Kyron faz com os demais monitores ao iniciar um jogo."
    assert titulo("linhaMover") == "Mover o aplicativo para outro monitor ao iniciar um jogo"
    assert titulo("linhaMonitor") == "Monitor"
    assert titulo("linhaIdentificar") == "Identificar monitores"
    assert titulo("linhaPapelDeParede") == "Trocar o papel de parede dos outros monitores"
    assert texto("titulo_pronto") == "Tudo pronto"
    assert texto("descricao_pronto") == "Você pode alterar estas opções a qualquer momento em Preferências."
    assert texto("botaoAbrirBiblioteca") == "Abrir a biblioteca"
    assert texto("botaoVoltar") == "Voltar"
    assert texto("botaoPular") == "Pular"
    assert texto("botaoContinuar") == "Continuar"
    for nome in ("titulo_boas_vindas", "descricao_jogos"):
        assert avaliar(janela.achar(nome), "textFormat === Text.PlainText") is True, nome


def test_sem_segundo_monitor_a_tela_some():
    assistente, _, _ = _assistente()
    assert "monitores" not in assistente.paginas


def test_sem_3d_a_tela_do_controle_some(monkeypatch):
    """Sem renderizador 3D, a tela do controle (o Big Picture) sai da lista."""
    monkeypatch.setattr(big_picture, "tem_3d", lambda _janela: False)
    assistente, _, _ = _assistente()
    assert "controle" in assistente.paginas
    assistente.avancar()
    janela = types.SimpleNamespace(rendererInterface=lambda: object())
    assistente.definir_janela(janela)
    assert "controle" not in assistente.paginas
    assert assistente.paginas[assistente.indice] == "jogos"  # a tela à vista não muda


def test_paginas_ocupam_a_largura_do_carrossel(janela):
    carrossel = janela.achar("carrossel")
    assert carrossel.width() == 640
    for nome in ("boas_vindas", "jogos", "idioma", "capas", "conquistas", "iluminacao", "controle", "monitores", "pronto"):
        assert janela.achar(f"pagina_{nome}").width() == carrossel.width(), nome


def test_rodape_nao_fica_numa_barra_da_janela(janela):
    """A moldura é a nativa do Windows: o rodapé é conteúdo da janela, nunca uma alça de arrastá-la."""
    flags = janela.raiz.flags()
    assert not flags & Qt.WindowType.FramelessWindowHint
    assert flags & Qt.WindowType.WindowTitleHint and flags & Qt.WindowType.WindowCloseButtonHint
    assert flags & Qt.WindowType.WindowMinimizeButtonHint and not flags & Qt.WindowType.WindowMaximizeButtonHint
    assert janela.raiz.width() == 640 and janela.raiz.height() == 640
    assert janela.raiz.minimumWidth() == janela.raiz.maximumWidth() == 640
    assert janela.raiz.minimumHeight() == janela.raiz.maximumHeight() == 640
    rodape = janela.achar("rodape")
    pai = rodape.parentItem()
    while pai is not None and pai is not janela.raiz.contentItem():
        pai = pai.parentItem()
    assert pai is janela.raiz.contentItem()


def test_cartao_do_aviso_na_pagina_de_conquistas_e_embutido(janela):
    """Contorno e sombra no cartão do assistente (`conquista-aviso-cartao-embutido`)."""
    janela.ir_para("conquistas")
    sombra = janela.achar("sombraDoAviso")
    assert sombra.property("visible") is True


def test_foco_do_teclado_fica_na_pagina_atual(janela):
    # Em JS: pelo Python, o PySide faz de cada item devolvido filho do anterior, e a cadeia, que é circular, fecha um ciclo
    # de pais que derruba o processo ao coletar os wrappers (`Object::invalidate` em memória liberada).
    percurso = """(function () {
        var alcancadas = {}, item = contentItem
        for (var passo = 0; passo < 60 && item; ++passo) {
            item = item.nextItemInFocusChain(true)
            for (var pai = item; pai; pai = pai.parent)
                if (pai.objectName.indexOf("pagina_") === 0) alcancadas[pai.objectName] = true
        }
        return Object.keys(alcancadas).join()
    })()"""

    assert avaliar(janela.raiz, percurso) == "pagina_boas_vindas"
    janela.modelo.avancar()
    esperar()
    assert avaliar(janela.raiz, percurso) == "pagina_jogos"


def test_continuar_da_tela_dos_jogos_espera_a_pasta(schema, tmp_path):
    assistente, _, _ = _assistente()
    assistente.avancar()
    assert assistente.paginas[assistente.indice] == "jogos"
    assert not assistente.podeContinuar
    assistente.escolherPasta(QUrl.fromLocalFile(str(tmp_path)))
    assert assistente.podeContinuar
    assistente.avancar()
    assert assistente.podeContinuar


def test_continuar_da_tela_dos_jogos_com_pasta_ja_gravada(schema, tmp_path):
    schema.set_string("shortcuts-location", str(tmp_path))
    assistente, _, _ = _assistente()
    assistente.avancar()
    assert assistente.podeContinuar


def test_continuar_volta_a_ficar_ativo_nas_outras_telas(janela):
    janela.modelo.avancar()
    esperar()
    continuar = janela.achar("botaoContinuar")
    assert not continuar.isEnabled() and janela.achar("botaoPular").isEnabled()
    janela.modelo.avancar()  # Pular: segue sem pasta
    esperar()
    assert continuar.isEnabled()
    janela.modelo.voltar()
    esperar()
    assert not continuar.isEnabled()


def test_boas_vindas_mostra_o_logo_do_app(janela):
    logo = janela.achar("imagem_boas_vindas")
    assert logo.isVisible()
    assert logo.property("source").toString().endswith("/data/icons/hicolor/scalable/apps/io.github.joaomgabaldi.Cartridges.svg")


def test_icone_da_iluminacao_e_de_luz(janela):
    # O "display-brightness-symbolic": o SVG da Adwaita em 128 px, e não o glifo da Segoe.
    icone = janela.achar("icone_iluminacao")
    assert icone.property("nome") == "display-brightness"
    assert icone.property("tamanho") == 128


def test_status_page_tem_os_tamanhos_do_libadwaita(janela):
    """Título title-1 (22), descrição de 12 e ícone de 128; a página das conquistas é `compact` (title-2 e 96)."""
    titulo = janela.achar("titulo_iluminacao")
    assert titulo.property("font").pixelSize() == 22
    assert janela.achar("descricao_iluminacao").property("font").pixelSize() == 12
    compacto = janela.achar("titulo_conquistas")
    assert compacto.property("font").pixelSize() == 16


def test_botoes_do_rodape_sao_os_da_main(janela):
    """"Voltar" e "Pular" são botões comuns; "Continuar" é sugestão sem cápsula; "Pular configuração" é plano."""
    janela.ir_para("jogos")
    assert janela.achar("botaoVoltar").property("estilo") == "normal"
    assert janela.achar("botaoPular").property("estilo") == "normal"
    continuar = janela.achar("botaoContinuar")
    assert continuar.property("estilo") == "sugestao" and continuar.property("pilula") is False
    pular = janela.achar("botaoPularConfiguracao")
    assert pular.property("estilo") == "plano" and pular.property("pilula") is False


def test_ponto_da_tela_atual_e_maior(janela):
    """O ponto da página à vista tem raio 4 (8 px) e os outros 3 (6 px)."""
    esperar()
    pontos = [p for p in janela.achar("pontos").childItems() if p.property("peso") is not None]
    assert len(pontos) == len(janela.modelo.paginas)
    assert pontos[0].width() == 8 and pontos[1].width() == 6


def test_animar_e_relido_a_cada_troca_de_tela(janela, monkeypatch):
    """O ajuste de animações do Windows muda com a janela aberta e é relido a cada rolagem."""
    assert janela.modelo.animar is True
    monkeypatch.setattr(modulo, "_animacoes_do_sistema", lambda: False)
    janela.modelo.avancar()
    assert janela.modelo.animar is False


def test_troca_de_tela_anima_o_carrossel_e_termina_no_indice_exato(janela):
    """Com `animar` verdadeiro o "Continuar" leva a posição por valores intermediários até o índice exato."""
    carrossel = janela.achar("carrossel")
    assert janela.modelo.animar is True and carrossel.property("posicao") == 0
    visto = []
    janela.modelo.avancar()
    assert esperar(lambda: visto.append(carrossel.property("posicao")) or 0 < visto[-1] < 1, limite=3.0)
    assert esperar(lambda: carrossel.property("posicao") == 1, limite=3.0)
    janela.modelo.alterado.emit()  # um ajuste qualquer no meio do repouso não reinicia nada
    esperar(limite=0.2)
    assert carrossel.property("posicao") == 1


# -- a animação das capas ---------------------------------------------------------------------------------------------


def test_tela_das_capas_tem_o_palco_com_as_duas_imagens(janela):
    palco = janela.achar("palcoDasCapas")
    capa, vazia = janela.achar("capaDeExemplo"), janela.achar("capaVazia")
    # As duas imagens passam por uma máscara de raio 6 (um item entre elas e o palco).
    assert capa.parentItem() is vazia.parentItem() and capa.parentItem().parentItem() is palco
    assert capa.property("source").toString().endswith("/data/capa_de_exemplo.svg")
    assert vazia.property("source").toString().endswith("/data/library_placeholder.svg")
    assert (palco.width(), palco.height()) == (120, 180)
    assert not janela.achar("icone_capas").isVisible()  # a animação ocupa o lugar do ícone


def test_animacao_das_capas_so_roda_com_a_tela_visivel(janela):
    palco = janela.achar("palcoDasCapas")
    assert palco.property("animando") is False
    janela.ir_para("capas")
    assert esperar(lambda: palco.property("animando") is True)
    janela.modelo.avancar()
    assert esperar(lambda: palco.property("animando") is False)
    janela.modelo.voltar()
    assert esperar(lambda: palco.property("animando") is True)


def test_sem_animacoes_do_sistema_a_capa_fica_parada(app_qt, monkeypatch):
    monkeypatch.setattr(modulo, "_animacoes_do_sistema", lambda: False)
    j = _Janela(app_qt, monkeypatch)
    try:
        assert j.modelo.animar is False
        j.ir_para("capas")
        esperar()
        assert j.achar("palcoDasCapas").property("animando") is False
        assert j.achar("capaDeExemplo").property("opacity") == 1
        assert j.achar("capaVazia").property("opacity") == 0
    finally:
        j.fechar()


def test_quadros_da_animacao_das_capas():
    x, vazia, capa = modulo.quadro_das_capas(0)  # placeholder parado no centro
    assert (x, vazia, capa) == (0, 1, 1)
    x, vazia, capa = modulo.quadro_das_capas(2000)  # a capa sozinha
    assert (vazia, capa) == (0, 1) and x == -modulo._DESLOCAMENTO
    _x, _vazia, capa = modulo.quadro_das_capas(3850)  # a capa some
    assert capa < 1
    _x, vazia, _capa = modulo.quadro_das_capas(4200)  # o placeholder volta ao centro
    assert 0 < vazia < 1
    x, vazia, capa = modulo.quadro_das_capas(modulo._CICLO)  # emenda do loop: igual ao quadro 0
    assert (x, vazia, capa) == (0, 1, 0)
    for instante in range(0, modulo._CICLO + 1, 50):
        _x, vazia, capa = modulo.quadro_das_capas(instante)
        assert 0 <= vazia <= 1 and 0 <= capa <= 1


# -- as chaves de API e o cartão --------------------------------------------------------------------------------------


def test_chave_do_steamgriddb_tem_o_link_das_preferencias(janela, _sem_navegador):
    grupo = janela.achar("grupoDaChaveSgdb")
    assert grupo.property("descricao") == (
        "É necessária uma chave da API para usar o SteamGridDB. "
        '<a href="https://www.steamgriddb.com/profile/preferences/api">Obtenha aqui</a>.'
    )
    assert grupo.property("descricaoRica") is True
    assert janela.achar("grupoDaChaveDaSteam").property("descricao") == (
        'Informe a chave da Steam Web API. <a href="https://steamcommunity.com/dev/apikey">Obtenha aqui</a>.'
    )
    avaliar(grupo, 'linkAcionado("https://www.steamgriddb.com/profile/preferences/api")')
    assert _sem_navegador == ["https://www.steamgriddb.com/profile/preferences/api"]


def test_tela_das_conquistas_mostra_o_cartao_real(janela):
    assert janela.modelo.cartao == {
        "rotulo": "Conquista desbloqueada · ★ Rara, 2,3%",
        "titulo": "Lenda das ruas",
        "descricao": "Vença todas as corridas em primeiro lugar.",
        "icone": QUrl.fromLocalFile(str(RAIZ / "data" / "conquista_de_exemplo.svg")).toString(),
    }
    cartao = janela.achar("cartaoDoAviso")
    assert cartao.parentItem() is not None
    assert cartao.property("rotulo") == "Conquista desbloqueada · ★ Rara, 2,3%"
    assert cartao.property("titulo") == "Lenda das ruas"
    assert cartao.property("descricao") == "Vença todas as corridas em primeiro lugar."
    assert cartao.property("icone").endswith("/data/conquista_de_exemplo.svg")
    assert not janela.achar("icone_conquistas").isVisible()


def test_grupo_das_contas_no_assistente_nao_repete_o_texto_da_pagina(janela):
    # A página já explica as contas; o grupo, aqui, só mostra as linhas.
    janela.ir_para("conquistas")
    assert janela.achar("grupoDasContas").isVisible()
    assert not janela.achar("tituloDoGrupoDasContas").isVisible()
    assert not janela.achar("descricaoDoGrupoDasContas").isVisible()
    assert janela.achar("tituloDaConta_microsoft").property("text") == "Conta Microsoft"


def test_pagina_das_conquistas_rola_ate_a_chave_da_steam(janela):
    # Em 640 px, com o rodapé, a página pode não caber: rolada até o fim, a chave da Steam fica à vista.
    janela.ir_para("conquistas")
    pagina = janela.achar("pagina_conquistas")
    pagina.setProperty("contentY", max(0, pagina.property("contentHeight") - pagina.height()))
    esperar()
    linha = janela.achar("linhaDaChaveDaSteam")
    topo = linha.mapToItem(pagina, QPointF(0, 0)).y()
    assert topo >= 0
    assert topo + linha.height() <= pagina.height()


# -- a iluminação ------------------------------------------------------------------------------------------------------


def test_iluminacao_configurada_liga_o_recurso(monkeypatch, schema):
    monkeypatch.setattr(session_fita, "fitas", lambda: ["dispositivo"])
    assistente, _, _ = _assistente()
    assistente.configurarIluminacao()
    assert assistente.configuracaoDasFitas is not None
    assistente.configuracaoDasFitas.fechar()
    assert assistente.configuracaoDasFitas is None
    assert schema.get_boolean("session-fita") is True


def test_iluminacao_sem_dispositivos_nao_liga(monkeypatch, schema):
    monkeypatch.setattr(session_fita, "fitas", lambda: [])
    schema.set_boolean("session-fita", False)
    assistente, _, _ = _assistente()
    assistente.configurarIluminacao()
    assistente.configuracaoDasFitas.fechar()
    assert schema.get_boolean("session-fita") is False


def test_assistente_nunca_acende_fitas(janela, monkeypatch, schema):
    """O fluxo inteiro, com "Configurar" e o fechamento do assistente das fitas, não fala com nenhuma fita."""
    chamadas = []
    for nome in ("reacender", "previa", "aplicar", "abrir"):
        monkeypatch.setattr(session_fita, nome, lambda *a, _n=nome, **k: chamadas.append(_n))
    monkeypatch.setattr(session_fita, "fitas", lambda: ["dispositivo"])
    janela.ir_para("iluminacao")
    _clicar(janela.achar("botaoConfigurar"))
    assert esperar(lambda: janela.achar("dialogoDaConfiguracaoDasFitas").isVisible())
    janela.modelo.configuracaoDasFitas.fechar()
    assert esperar(lambda: not janela.achar("dialogoDaConfiguracaoDasFitas").isVisible())
    assert schema.get_boolean("session-fita") is True
    for _ in range(10):
        janela.modelo.avancar()
    _clicar(janela.achar("botaoAbrirBiblioteca"))
    assert chamadas == []


# -- o X e o backup ---------------------------------------------------------------------------------------------------


def test_fechar_no_x_cancela_logins_e_nao_marca(monkeypatch, schema):
    assistente, terminou, _ = _assistente()
    fechados = []
    monkeypatch.setattr(assistente.contas, "fechar", lambda: fechados.append(1))
    assert assistente.fecharNoX() is True
    assert fechados == [1] and terminou == []
    assert not schema.get_boolean("assistente-concluido")


def test_backup_valido_marca_e_restaura(monkeypatch, schema, tmp_path, sincrono):
    agendados = []
    monkeypatch.setattr(backup, "validar", lambda caminho: {})
    monkeypatch.setattr(backup, "agendar", agendados.append)
    assistente, _, restaurou = _assistente()
    pedidos = _dialogos(assistente)
    assistente.restaurarBackup(QUrl.fromLocalFile(str(tmp_path / "b.zip")))
    assert agendados == [tmp_path / "b.zip"] and restaurou == [1]
    assert schema.get_boolean("assistente-concluido") is True and pedidos == []
    assert not assistente.avisos.visivel  # o "Aguarde" sai em todos os ramos


def test_backup_invalido_avisa_e_continua(monkeypatch, schema, tmp_path, sincrono):
    def invalido(_caminho):
        raise backup.BackupInvalido()

    monkeypatch.setattr(backup, "validar", invalido)
    assistente, _, restaurou = _assistente()
    pedidos = _dialogos(assistente)
    assistente.restaurarBackup(QUrl.fromLocalFile(str(tmp_path / "x.zip")))
    assert pedidos == [("Backup inválido", "O arquivo não é um backup válido do Kyron.")]
    assert restaurou == [] and schema.get_boolean("assistente-concluido") is False
    assert not assistente.preparando and not assistente.avisos.visivel


def test_backup_com_falha_generica_avisa_e_continua(monkeypatch, schema, tmp_path, sincrono):
    def falha(_caminho):
        raise OSError("disco cheio")

    monkeypatch.setattr(backup, "validar", lambda caminho: {})
    monkeypatch.setattr(backup, "agendar", falha)
    assistente, _, restaurou = _assistente()
    pedidos = _dialogos(assistente)
    assistente.restaurarBackup(QUrl.fromLocalFile(str(tmp_path / "x.zip")))
    assert pedidos == [("Não foi possível restaurar", "Não foi possível restaurar o backup. Tente novamente.")]
    assert restaurou == [] and schema.get_boolean("assistente-concluido") is False
    assert not assistente.preparando and not assistente.avisos.visivel


def test_restaurar_bloqueia_a_tela_ate_terminar(janela, monkeypatch, tmp_path):
    pendentes = []
    monkeypatch.setattr(modulo, "_em_thread", pendentes.append)

    def invalido(_caminho):
        raise backup.BackupInvalido()

    monkeypatch.setattr(backup, "validar", invalido)
    janela.modelo.restaurarBackup(QUrl.fromLocalFile(str(tmp_path / "x.zip")))
    esperar()
    botoes = [janela.achar(n) for n in ("botaoComecar", "botaoRestaurar", "botaoPularConfiguracao")]
    assert len(pendentes) == 1 and janela.modelo.preparando
    assert not any(b.isEnabled() for b in botoes)
    # O X também fica sem efeito nesses segundos: o aviso pede para aguardar.
    assert janela.achar("textoDoAviso").property("text") == "Preparando a restauração. Aguarde…"
    janela.modelo.restaurarBackup(QUrl.fromLocalFile(str(tmp_path / "y.zip")))  # um segundo pedido não roda
    assert len(pendentes) == 1
    pendentes[0]()
    dialogo = janela.achar("dialogoDoAssistente")
    assert esperar(lambda: dialogo.isVisible())
    assert dialogo.property("titulo") == "Backup inválido"
    assert not janela.modelo.preparando and not janela.modelo.avisos.visivel
    avaliar(dialogo, "fechar()")
    assert esperar(lambda: all(b.isEnabled() for b in botoes))


def test_fechar_no_x_espera_a_preparacao_da_restauracao(janela, monkeypatch, tmp_path):
    """O X durante "Preparando a restauração. Aguarde…" é recusado."""
    pendentes = []
    monkeypatch.setattr(modulo, "_em_thread", pendentes.append)

    def invalido(_caminho):
        raise backup.BackupInvalido()

    monkeypatch.setattr(backup, "validar", invalido)
    fechados = []
    monkeypatch.setattr(janela.modelo.contas, "fechar", lambda: fechados.append(1))
    janela.modelo.restaurarBackup(QUrl.fromLocalFile(str(tmp_path / "x.zip")))
    janela.raiz.close()
    esperar()
    assert janela.raiz.isVisible() and fechados == []
    pendentes[0]()
    assert esperar(lambda: not janela.modelo.preparando)
    janela.raiz.close()
    assert esperar(lambda: not janela.raiz.isVisible())
    assert fechados == [1]


def test_as_tres_saidas_fecham_as_contas(app_qt, monkeypatch, schema, tmp_path, sincrono):
    """Concluir, o X e o backup agendado: `contas.fechar()` uma vez em cada."""
    monkeypatch.setattr(backup, "validar", lambda caminho: {})
    monkeypatch.setattr(backup, "agendar", lambda caminho: None)
    for saida in ("concluir", "x", "backup"):
        schema.set_boolean("assistente-concluido", False)
        j = _Janela(app_qt, monkeypatch)
        fechados = []
        monkeypatch.setattr(j.modelo.contas, "fechar", lambda f=fechados: f.append(1))
        try:
            if saida == "concluir":
                j.modelo.concluir()
            elif saida == "x":
                j.raiz.close()
            else:
                j.modelo.restaurarBackup(QUrl.fromLocalFile(str(tmp_path / "b.zip")))
            assert esperar(lambda: not j.raiz.isVisible()), saida
            assert fechados == [1], saida
        finally:
            j.fechar()
        assert fechados == [1], saida  # nem o fechamento da janela pelo app fecha de novo


# -- as contas sem biblioteca -----------------------------------------------------------------------------------------


def test_conectar_conta_no_assistente_sem_biblioteca_nao_levanta(janela, monkeypatch):
    """A conta conecta antes de a biblioteca existir; a leitura dos jogos da loja corre sobre a store
    vazia do assistente, sem levantar."""
    conectada = []
    monkeypatch.setattr(epic_conta, "conectada", lambda: bool(conectada))
    monkeypatch.setattr(epic_conta, "conectar", lambda _codigo: conectada.append(1))
    varridos = []
    varredura = types.SimpleNamespace(varrer_jogos=lambda games, filtro=None: varridos.append(list(games)))
    monkeypatch.setattr(shared, "aplicativo", types.SimpleNamespace(varredura_conquistas=varredura), raising=False)
    assert shared.store is not None and list(shared.store) == []
    contas = janela.modelo.contas
    abertos = []
    monkeypatch.setattr(contas, "_abrir", abertos.append)
    contas.clicarEpic()
    login = contas.loginEpic
    assert login is not None and abertos == [epic_conta.PAGINA_DE_LOGIN]
    assert esperar(lambda: janela.achar("janelaDeLoginEpic").isVisible())
    login.texto = _COD
    login.conectar()
    assert esperar(lambda: contas.loginEpic is None)
    assert varridos == [[]]
    assert contas.epic["botao"] == "Sair"


# -- sem gi -----------------------------------------------------------------------------------------------------------


def test_assistente_sem_gi(tmp_path):
    roteiro = (
        "import builtins, sys; builtins._ = lambda m: m; sys.modules['gi'] = None; "
        "import kyron.assistente; print('ok')"
    )
    registro = rf"Software\KyronTestes\assistente-sem-gi-{uuid.uuid4()}"
    ambiente = {
        **os.environ,
        "KYRON_DADOS": str(tmp_path / "dados"),
        "KYRON_REGISTRO": registro,
        "QT_QPA_PLATFORM": "offscreen",
    }
    try:
        resultado = subprocess.run(
            [sys.executable, "-c", roteiro], cwd=RAIZ, env=ambiente, capture_output=True, text=True, timeout=60,
            check=False,
        )
    finally:
        _apagar_chave(winreg.HKEY_CURRENT_USER, registro)
    assert resultado.returncode == 0, resultado.stderr
    assert resultado.stdout.strip().endswith("ok")


def test_concluir_durante_a_preparacao_e_recusado_e_o_backup_restaura_uma_vez(monkeypatch, schema, tmp_path):
    """"Abrir a biblioteca" no meio da preparação não abre a biblioteca duas vezes."""
    pendentes = []
    monkeypatch.setattr(modulo, "_em_thread", pendentes.append)
    monkeypatch.setattr(modulo, "na_thread_principal", lambda funcao, *args: funcao(*args))
    monkeypatch.setattr(backup, "validar", lambda caminho: {})
    monkeypatch.setattr(backup, "agendar", lambda caminho: None)
    assistente, terminou, restaurou = _assistente()
    assistente.restaurarBackup(QUrl.fromLocalFile(str(tmp_path / "b.zip")))
    assert assistente.preparando

    assistente.concluir()

    assert terminou == [] and not schema.get_boolean("assistente-concluido")
    pendentes[0]()  # o backup fica pronto
    assert restaurou == [1] and terminou == []
    assistente._backup_preparado("ok")  # noqa: SLF001  # um resultado repetido depois da saída não restaura de novo
    assert restaurou == [1]


def test_anel_de_foco_so_aparece_com_o_teclado(janela):
    """Aberto e avançado com o mouse, o primeiro controle de cada tela não mostra o anel; pelo teclado, sim."""
    comecar = janela.achar("botaoComecar")
    assert esperar(lambda: comecar.property("activeFocus") is True)
    assert comecar.property("visualFocus") is False  # aberto sem teclado: sem anel
    _clicar(comecar)  # o clique do mouse
    pasta = janela.achar("linhaDaPastaBotao")
    assert esperar(lambda: pasta.property("activeFocus") is True)
    assert pasta.property("visualFocus") is False

    janela.modelo.voltar()
    assert esperar(lambda: comecar.property("activeFocus") is True)
    janela.achar("botaoRestaurar").forceActiveFocus(Qt.FocusReason.TabFocusReason)  # o teclado entra em uso
    comecar.forceActiveFocus(Qt.FocusReason.TabFocusReason)
    QTest.keyClick(janela.raiz, Qt.Key.Key_Return)
    assert esperar(lambda: pasta.property("activeFocus") is True)
    assert pasta.property("visualFocus") is True


def test_barra_com_titulo_texto_no_clamp_de_600_e_botao_escolher_com_fundo(janela):
    """A barra mostra "Kyron"; o texto da tela cabe em 600 de largura; "Escolher" é um botão cinza de 34."""
    assert janela.achar("barraDoAssistente").property("titulo") == "Kyron"
    descricao = janela.achar("descricao_boas_vindas")
    assert descricao.property("width") <= 600
    assert descricao.property("lineHeight") == 17
    botao = janela.achar("linhaDaPastaRotulo")
    assert botao.property("height") == 34 and botao.property("radius") == 9


def test_idioma_e_nome_do_jogador_na_etapa_propria(janela, schema):
    janela.ir_para("idioma")
    assert janela.modelo.paginas.index("idioma") == janela.modelo.paginas.index("jogos") + 1
    assert janela.achar("titulo_idioma").property("text") == "Idioma e nome do jogador"
    campo, linha = janela.achar("campoDoNomeDoJogadorNoAssistente"), janela.achar("linhaDoIdiomaNoAssistente")
    campo.setProperty("text", "Joao")
    QMetaObject.invokeMethod(campo, "editado", Qt.ConnectionType.DirectConnection)
    assert schema.get_string("nome-do-jogador") == ""  # a cada tecla não grava
    QMetaObject.invokeMethod(campo, "terminado", Qt.ConnectionType.DirectConnection)
    assert schema.get_string("nome-do-jogador") == "Joao"
    campo.setProperty("text", "João")
    QMetaObject.invokeMethod(campo, "terminado", Qt.ConnectionType.DirectConnection)
    assert schema.get_string("nome-do-jogador") == "Joao"
    assert campo.property("erro") is True
    assert campo.property("subtitulo") == "Use até 32 caracteres, sem acentos nem símbolos especiais."
    QMetaObject.invokeMethod(linha, "escolhido", Qt.ConnectionType.DirectConnection, Q_ARG(int, 1))
    assert schema.get_string("idioma-do-jogador") == "brazilian"
