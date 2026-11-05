# test_preferencias_fitas_qt.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A iluminação inteligente nas Preferências: o interruptor, o brilho, a cor do app, o teste e o brilho por dispositivo. Nenhuma fita de verdade: a prévia, o arranque e o `aplicar` são espiões, e o `sem_fita_de_verdade` do conftest falha alto se algo escapar."""

import gc
import subprocess
import sys
import threading
import weakref
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QMetaObject, Qt
from PySide6.QtGui import QColor
from PySide6.QtQuick import QQuickItem

from cartridges import shared
from cartridges.modelos import preferencias as preferencias_mod
from cartridges.modelos.preferencias import Preferencias
from cartridges.utils import session_fita
from tests.apoio_fita import falsas, pastas, sem_fade, sem_vigia  # noqa: F401
from tests.apoio_qml_biblioteca import _App, _esperar, _jogos
from tests.apoio_qml_preferencias import _avaliar
from tests.apoio_preferencias_fitas_qt import _com_fitas, previas  # noqa: F401  (as fixtures vêm junto)

SEM_RESPOSTA = (
    "Sem resposta: {}. Se o dispositivo estiver ligado, o endereço dele na rede pode ter mudado; configure a "
    "iluminação inteligente novamente."
)


@pytest.fixture
def arranques(monkeypatch):
    chamadas = []
    monkeypatch.setattr(session_fita, "reacender", lambda: chamadas.append(shared.schema.get_boolean("session-fita")))
    return chamadas


@pytest.fixture
def p(app_qt):  # noqa: ARG001
    modelo = Preferencias(None, lambda: True)
    assert modelo.abrir()
    yield modelo
    modelo.fechar()


@pytest.fixture
def teste_preso(monkeypatch):
    """A thread do "Testar" e a entrega na principal capturadas: o teste roda a tarefa e a volta quando quiser."""
    capturado = SimpleNamespace(tarefas=[], entregas=[])
    monkeypatch.setattr(
        preferencias_mod,
        "threading",
        # `Event` de verdade: é o sinal de parada do teste.
        SimpleNamespace(
            Thread=lambda target, daemon: SimpleNamespace(start=lambda: capturado.tarefas.append(target)),
            Event=threading.Event,
        ),
    )
    monkeypatch.setattr(
        preferencias_mod, "na_thread_principal", lambda funcao, *args: capturado.entregas.append((funcao, args))
    )

    def rodar():
        capturado.tarefas.pop()()
        funcao, args = capturado.entregas.pop()
        return funcao(*args)

    capturado.rodar = rodar
    return capturado


# region Interruptor e arranque


def test_preferencias_bloqueiam_a_fita_sem_configuracao(app_qt):  # noqa: ARG001
    """Sem fita configurada não há o que ligar, e a tela diz isso."""
    shared.schema.set_boolean("session-fita", True)
    modelo = Preferencias(None, lambda: True)
    modelo.abrir()

    assert modelo.fitas.configuradas == 0
    assert modelo.fitas.subtitulo == "Nenhum dispositivo configurado"
    assert shared.schema.get_boolean("session-fita") is False
    modelo.fechar()


def test_preferencias_liberam_a_fita_e_contam_as_configuradas(p):
    _com_fitas("Centro", "Direita")
    p.fitas.reler()
    assert p.fitas.configuradas == 2
    assert p.fitas.subtitulo == "2 dispositivos configurados"
    _com_fitas("Centro")
    p.fitas.reler()
    assert p.fitas.subtitulo == "1 dispositivo configurado"


def test_ligar_o_interruptor_arranca_o_ciclo(app_qt, arranques):  # noqa: ARG001
    """Ligar com o app aberto guarda o estado de antes na hora (sem isto a `fita-estado-anterior` ficava vazia)."""
    _com_fitas()
    modelo = Preferencias(None, lambda: True)
    modelo.abrir()
    assert arranques == []

    modelo.definir("session-fita", True)
    assert arranques == [True]

    # Desligar não desfaz nada aqui: quem devolve as fitas é o fechamento.
    modelo.definir("session-fita", False)
    assert arranques == [True]
    modelo.fechar()


def test_abrir_a_tela_com_o_recurso_ligado_nao_arranca(app_qt, arranques):  # noqa: ARG001
    _com_fitas()
    shared.schema.set_boolean("session-fita", True)
    modelo = Preferencias(None, lambda: True)
    modelo.abrir()
    assert modelo.valores["session-fita"] is True
    assert arranques == []
    modelo.fechar()


def test_ligar_grava_a_chave_antes_de_arrancar(p, arranques):
    """O `reacender` decide pela chave (`ligada()`): ela tem de estar gravada quando ele roda."""
    _com_fitas()
    p.definir("session-fita", True)
    assert arranques == [True]


def test_abrir_nao_acende_nem_grava_alem_do_previsto(app_qt, monkeypatch):  # noqa: ARG001
    """Com fitas, o recurso ligado e uma escolha de monitor antiga (pelo nome), abrir não chama `reacender`, `previa` nem `aplicar`, e o registro só muda em `session-monitor` (regravado pelo caminho)."""
    _com_fitas("Centro", "Direita")
    shared.schema.set_boolean("session-fita", True)
    shared.schema.set_boolean("playtime-tracking", True)
    shared.schema.set_boolean("minimize-after-launch", True)
    shared.schema.set_string("session-monitor", r"\\.\DISPLAY2")
    chamadas = []
    for nome in ("reacender", "previa", "aplicar", "abrir", "previa_calibracao"):
        monkeypatch.setattr(session_fita, nome, lambda *a, nome=nome, **_k: chamadas.append(nome))
    antes = {c: shared.schema.get_value(c) for c in shared.schema.list_keys()}

    modelo = Preferencias(None, lambda: True)
    assert modelo.abrir()

    depois = {c: shared.schema.get_value(c) for c in shared.schema.list_keys()}
    mudaram = {c for c in depois if depois[c] != antes.get(c)}
    assert mudaram == {"session-monitor"}
    assert depois["session-monitor"] == r"\\?\DISPLAY#FALSO#2"
    assert chamadas == []
    assert modelo.fitas.configuradas == 2
    modelo.fechar()


# endregion
# region Brilho e cor do app


def test_cor_vai_e_volta_entre_o_seletor_e_o_modulo():
    original = session_fita.Cor(340, 1000, 150)
    vermelho, verde, azul = session_fita.cor_para_rgb(original)
    volta = session_fita.rgb_para_cor(vermelho, verde, azul, 150)
    # Matiz e saturação sobrevivem à ida e à volta, com folga de arredondamento.
    assert abs(volta.matiz - original.matiz) <= 2
    assert abs(volta.saturacao - original.saturacao) <= 10
    assert volta.brilho == 150


def test_escolher_a_cor_do_app_nas_preferencias_grava_e_mostra(p, previas):
    """Sem botão de aplicar: as Preferências gravam na hora, e a fita acompanha."""
    _com_fitas()
    # Abrir a tela não conta como escolha.
    assert session_fita.tom_do_app() == session_fita.COR_PADRAO_DO_APP
    assert p.fitas.corDoAppPadrao is True
    assert previas == []

    p.fitas.escolherCorDoApp(QColor.fromRgbF(*session_fita.cor_para_rgb(session_fita.Cor(210, 1000, 0))))

    matiz, saturacao = session_fita.tom_do_app()
    assert abs(matiz - 210) <= 2
    assert abs(saturacao - 1000) <= 10
    assert p.fitas.corDoAppPadrao is False
    assert previas[-1] == (session_fita.cor_do_app(), None)
    assert abs(p.fitas.corDoApp.hsvHueF() * 360 - 210) <= 2

    p.fitas.voltarCorDoApp()
    assert session_fita.tom_do_app() == session_fita.COR_PADRAO_DO_APP
    assert p.fitas.corDoAppPadrao is True


def test_voltar_a_cor_padrao_grava_o_roxo_exato(p, previas):
    session_fita.salvar_tom_do_app(200, 800)
    p.fitas.voltarCorDoApp()
    # O roxo exato, e não a ida e volta pela cor da tela (que pode arredondar uma unidade).
    assert session_fita.tom_do_app() == session_fita.COR_PADRAO_DO_APP
    assert previas == [(session_fita.Cor(*session_fita.COR_PADRAO_DO_APP, session_fita.brilho_padrao()), None)]


def test_brilho_mostra_na_hora(p, previas):
    p.fitas.definirBrilho(50)
    assert shared.schema.get_int("fita-brilho-padrao") == 500
    assert p.fitas.brilho == 50
    assert previas[-1] == (session_fita.Cor(*session_fita.tom_do_app(), 500), None)
    # Abaixo do mínimo a fita apagaria: o 0 vira o menor brilho que ainda acende.
    p.fitas.definirBrilho(0)
    assert shared.schema.get_int("fita-brilho-padrao") == session_fita.BRILHO_MINIMO


def test_fechar_depois_de_uma_previa_nao_mexe_nas_fitas(app_qt, previas):  # noqa: ARG001
    """Só o balão do pulso e os diálogos internos devolvem a cor do app; fechar as Preferências não."""
    modelo = Preferencias(None, lambda: True)
    modelo.abrir()
    modelo.fitas.definirBrilho(30)
    quantas = len(previas)
    modelo.fechar()
    assert len(previas) == quantas


# endregion
# region Testar


def test_o_teste_nao_escreve_em_tela_ja_fechada(app_qt, monkeypatch, teste_preso):  # noqa: ARG001
    """O resultado do "Testar" volta por `na_thread_principal`, e a tela pode ter fechado nesse meio-tempo."""
    _com_fitas()
    monkeypatch.setattr(session_fita, "aplicar", lambda *_a: True)
    modelo = Preferencias(None, lambda: True)
    modelo.abrir()

    modelo.fitas.testar()
    assert modelo.fitas.resultadoDoTeste == "Testando…"
    assert modelo.fitas.testando is True
    teste_preso.rodar()
    assert modelo.fitas.resultadoDoTeste == "Teste concluído"
    assert modelo.fitas.testando is False

    modelo.fitas.testar()
    modelo.fechar()
    teste_preso.rodar()
    assert modelo.fitas.resultadoDoTeste == "Testando…"
    assert modelo.fitas.testando is False
    # Reaberta, a linha volta ao texto de sempre.
    modelo.abrir()
    assert modelo.fitas.resultadoDoTeste == ""
    modelo.fechar()


def test_resultado_do_teste_sobrevive_ao_fechar_do_assistente_das_fitas(app_qt, monkeypatch, teste_preso):  # noqa: ARG001
    """O resultado fica até as Preferências fecharem, mesmo depois do assistente (`recontar`)."""
    _com_fitas()
    monkeypatch.setattr(session_fita, "aplicar", lambda *_a: True)
    modelo = Preferencias(None, lambda: True)
    modelo.abrir()
    modelo.fitas.testar()
    teste_preso.rodar()
    assert modelo.fitas.resultadoDoTeste == "Teste concluído"
    modelo.fitas.recontar()
    assert modelo.fitas.resultadoDoTeste == "Teste concluído"
    modelo.fechar()


def test_resultado_do_teste_depois_de_fechar_nao_levanta(app_qt, monkeypatch, teste_preso, previas):  # noqa: ARG001
    """Fechar e coletar a tela com o teste na rede; a entrega que chega depois não levanta nem reabre."""
    _com_fitas()
    monkeypatch.setattr(session_fita, "aplicar", lambda *_a: True)
    modelo = Preferencias(None, lambda: True)
    modelo.abrir()
    modelo.fitas.testar()
    fraca = weakref.ref(modelo.fitas)
    modelo.fechar()
    del modelo
    gc.collect()

    assert teste_preso.rodar() is None
    vivo = fraca()
    assert vivo is None
    assert previas == []


def test_segundo_clique_para_o_teste(p, monkeypatch, flush_idle):
    _com_fitas("Centro", "Direita")
    entrou, solta = threading.Event(), threading.Event()
    tentadas = []

    def aplicar(fita, *_a):
        tentadas.append(fita.nome)
        entrou.set()
        solta.wait(5)
        return True

    monkeypatch.setattr(session_fita, "aplicar", aplicar)
    p.fitas.testar()
    assert entrou.wait(5)
    p.fitas.testar()  # o botão agora é o de parar
    solta.set()
    for _ in range(50):
        flush_idle()
        if not p.fitas.testando:
            break
    assert p.fitas.testando is False
    assert p.fitas.resultadoDoTeste == "Teste interrompido"
    assert tentadas == ["Centro"]


def test_teste_lista_quem_nao_respondeu(p, monkeypatch, teste_preso):
    _com_fitas("Centro", "Sala", "Quarto")
    retomadas = []
    monkeypatch.setattr(session_fita, "retomar", lambda *a: retomadas.append(a))
    pedidas = []

    def aplicar(fita, ligada, cor_hex):
        pedidas.append((fita.nome, ligada, cor_hex))
        return fita.nome == "Centro"

    monkeypatch.setattr(session_fita, "aplicar", aplicar)
    p.fitas.testar()
    assert retomadas == [()]  # quem clica quer saber de novo, inclusive das suspensas
    teste_preso.rodar()
    assert p.fitas.resultadoDoTeste == SEM_RESPOSTA.format("Sala, Quarto")
    cor = session_fita.cor_do_app()
    assert pedidas[0] == ("Centro", True, session_fita.hsv_hex(session_fita.na_fita(cor, session_fita.fitas()[0])))


# endregion
# region Brilho por dispositivo


def _duas_com_teto():
    session_fita.gravar_fitas(
        [
            session_fita.Fita("Centro", "eb0", "192.0.2.10", "k", brilho=100),
            session_fita.Fita("Direita", "eb1", "192.0.2.11", "k", brilho=60),
        ]
    )


def test_brilho_por_dispositivo_salva_so_no_salvar(p, previas):
    _duas_com_teto()
    assert p.brilhoPorDispositivo is None
    p.abrirBrilhoPorDispositivo()
    janela = p.brilhoPorDispositivo
    assert [dict(linha) for linha in janela.linhas] == [
        {"id": "eb0", "nome": "Centro", "brilho": 100},
        {"id": "eb1", "nome": "Direita", "brilho": 60},
    ]
    cheia = session_fita.Cor(*session_fita.tom_do_app(), session_fita.BRILHO_CHEIO)
    assert previas[-1] == (cheia, {"eb0": 100, "eb1": 60})

    janela.mudar("eb0", 40)
    assert previas[-1] == (cheia, {"eb0": 40, "eb1": 60})
    assert [f.brilho for f in session_fita.fitas()] == [100, 60]
    janela.mudar("outro", 10)  # id que não é linha: ignorado
    assert previas[-1] == (cheia, {"eb0": 40, "eb1": 60})

    janela.salvar()
    assert [f.brilho for f in session_fita.fitas()] == [40, 60]
    assert previas[-1] == (session_fita.cor_do_app(), None)
    assert p.brilhoPorDispositivo is None


def test_brilho_por_dispositivo_cancelado_volta_a_cor_do_app(p, previas):
    _duas_com_teto()
    p.abrirBrilhoPorDispositivo()
    p.brilhoPorDispositivo.mudar("eb1", 20)
    p.brilhoPorDispositivo.cancelar()
    assert [f.brilho for f in session_fita.fitas()] == [100, 60]
    assert previas[-1] == (session_fita.cor_do_app(), None)
    assert p.brilhoPorDispositivo is None
    # Fechar as Preferências com a janela aberta também volta à cor do app, sem gravar.
    p.abrirBrilhoPorDispositivo()
    p.brilhoPorDispositivo.mudar("eb1", 20)
    p.fechar()
    assert p.brilhoPorDispositivo is None
    assert [f.brilho for f in session_fita.fitas()] == [100, 60]
    assert previas[-1] == (session_fita.cor_do_app(), None)


# endregion
# region Sem GTK


def test_session_fita_sem_gdk():
    codigo = (
        "import builtins, sys; builtins._ = lambda m: m; "
        "builtins.ngettext = lambda s, p, n: s if n == 1 else p; "
        "from cartridges.utils import session_fita; "
        "assert not hasattr(session_fita, 'cor_para_rgba') and not hasattr(session_fita, 'rgba_para_cor'); "
        "import cartridges.modelos.preferencias; "
        "assert 'gi' not in sys.modules"
    )
    subprocess.run([sys.executable, "-c", codigo], check=True, cwd=Path(__file__).resolve().parent.parent, timeout=60)


# endregion
# region Na tela


@pytest.fixture
def app(app_qt, previas, arranques):  # noqa: ARG001
    janela = _App(_jogos((1, "Alfa", {})))
    yield janela
    janela.fechar()


def _abrir(app):
    assert app.preferencias.abrir("session")
    assert _esperar(lambda: app.achar("paginaDePersonalizacao").property("visible") is True)


def _enabled(app, nome):
    return app.achar(nome).property("enabled") is True


def test_interruptor_da_tela_segue_o_da_iluminacao(app):
    _com_fitas()
    _abrir(app)
    linha = app.achar("interruptor-fita-acompanha-tela")
    assert linha.property("titulo") == "Cor acompanha a tela do jogo"
    assert linha.property("subtitulo") == (
        "A cor da iluminação acompanha, devagar, a cor predominante do jogo. "
        "Jogos com cor escolhida manualmente mantêm a cor fixa."
    )
    app.preferencias.definir("session-fita", False)
    assert _esperar(lambda: not _enabled(app, "interruptor-fita-acompanha-tela"))
    app.preferencias.definir("session-fita", True)
    assert _esperar(lambda: _enabled(app, "interruptor-fita-acompanha-tela"))


def test_m14_sem_contar_horas_as_fitas_seguem_configuraveis(app):
    # A metade do papel de parede está em test_qml_preferencias.py.
    _com_fitas()
    shared.schema.set_boolean("playtime-tracking", False)
    _abrir(app)
    assert _enabled(app, "grupoIluminacao")
    assert _enabled(app, "interruptor-session-fita")
    assert _enabled(app, "linhaConfigurarFitas")
    assert not _enabled(app, "grupoPapelDeParede")


def _textos_com_formato(raiz):
    achados, pilha = [], [raiz]
    while pilha:
        atual = pilha.pop()
        texto = atual.property("text")
        if isinstance(texto, str) and texto:
            achados.append((texto, _avaliar(atual, "textFormat")))
        pilha.extend(atual.childItems() if isinstance(atual, QQuickItem) else [])
    return achados


def test_nome_da_fita_em_texto_puro(app):
    """O nome da fita aparece como está, sem virar marcação."""
    nome = "<b>Sala</b> & Cia"
    session_fita.gravar_fitas([session_fita.Fita(nome, "eb0", "192.0.2.10", "k", brilho=70)])
    shared.schema.set_boolean("session-fita", True)
    _abrir(app)
    QMetaObject.invokeMethod(app.achar("linhaDoBrilhoPorDispositivoBotao"), "click", Qt.ConnectionType.DirectConnection)
    assert _esperar(lambda: app.achar("dialogoDoBrilhoPorDispositivo").property("visible") is True)
    janela = app.achar("dialogoDoBrilhoPorDispositivo")
    textos = _textos_com_formato(janela)
    assert (nome, 0) in textos  # 0 = Text.PlainText
    assert "Brilho máximo por dispositivo" in [t for t, _f in textos]
    assert (
        "Brilho máximo de cada dispositivo, em porcentagem. O brilho definido nas Preferências e em cada jogo é "
        "aplicado proporcionalmente sobre estes valores."
    ) in [t for t, _f in textos]
    assert app.achar("brilhoDoDispositivo-eb0Caixa").property("value") == 70
    QMetaObject.invokeMethod(app.achar("botaoCancelarDoBrilho"), "click", Qt.ConnectionType.DirectConnection)
    assert _esperar(lambda: app.achar("dialogoDoBrilhoPorDispositivo").property("visible") is False)
    assert app.preferencias.brilhoPorDispositivo is None


# endregion


def test_erro_no_meio_do_teste_vale_como_interrompido(p, monkeypatch, teste_preso):
    _com_fitas("Centro", "Sala")

    def aplicar(fita, *_a):
        if fita.nome == "Sala":
            raise OSError("quebrou no meio")
        return False

    monkeypatch.setattr(session_fita, "aplicar", aplicar)
    p.fitas.testar()
    teste_preso.rodar()
    assert p.fitas.resultadoDoTeste == "Teste interrompido"
    assert p.fitas.testando is False


def test_brilho_por_dispositivo_foco_no_salvar_tab_e_esc(app, flush_idle):
    from PySide6.QtTest import QTest  # noqa: PLC0415

    _com_fitas("Centro", "Direita")
    shared.schema.set_boolean("session-fita", True)
    _abrir(app)
    botao = app.achar("linhaDoBrilhoPorDispositivoBotao")
    botao.forceActiveFocus(Qt.FocusReason.TabFocusReason)
    QMetaObject.invokeMethod(botao, "click", Qt.ConnectionType.DirectConnection)
    dialogo = app.achar("dialogoDoBrilhoPorDispositivo")
    assert _esperar(lambda: dialogo.property("visible") is True)
    # Sem resposta padrão: o foco abre no primeiro controle, o Cancelar.
    cancelar = app.achar("botaoCancelarDoBrilho")
    assert _esperar(lambda: cancelar.hasActiveFocus())
    caixas = {app.achar("brilhoDoDispositivo-eb0Caixa"), app.achar("brilhoDoDispositivo-eb1Caixa")}
    focados = []
    for _ in range(6):
        QTest.keyClick(app.janela, Qt.Key.Key_Tab)
        flush_idle(0.03)
        atual = app.janela.activeFocusItem()
        focados.append(atual)
        dentro, item = False, atual
        while item is not None:
            dentro = dentro or item is dialogo
            item = item.parentItem()
        assert dentro  # o Tab circula dentro do modal
    assert any(f in caixas or (f is not None and f.parentItem() in caixas) for f in focados)
    QTest.keyClick(app.janela, Qt.Key.Key_Escape)
    assert _esperar(lambda: dialogo.property("visible") is False)
    assert app.preferencias.brilhoPorDispositivo is None
    assert _esperar(lambda: botao.hasActiveFocus())


# region O assistente da iluminação inteligente


@pytest.fixture(autouse=True)
def conta_da_tuya(tmp_path, monkeypatch):
    """A conta salva da Tuya vai para a pasta do teste: o assistente a lê ao abrir."""
    monkeypatch.setattr(shared, "tuya_conta_arquivo", tmp_path / "tuya_conta.json")


ANTES = {"ligada": False, "cor": "000003e800b4"}


def test_fechar_o_assistente_com_fita_nova_arranca_o_ciclo(p, monkeypatch, schema):  # noqa: ARG001
    """Configurar a primeira fita com o recurso já ligado também arranca."""
    shared.schema.set_boolean("session-fita", True)
    chamadas = []
    monkeypatch.setattr(session_fita, "reacender", lambda: chamadas.append("reacender"))

    p.abrirConfiguracaoDasFitas()
    assert p.configuracaoDasFitas is not None
    # Sem fita, `ligada()` é falso (e a releitura desliga a chave): não há o que arrancar.
    p.configuracaoDasFitas.fechar()
    assert chamadas == []
    assert p.configuracaoDasFitas is None

    p.abrirConfiguracaoDasFitas()
    session_fita.gravar_fitas([session_fita.Fita("Centro", "eb0", "1.2.3.4", "k")])
    shared.schema.set_boolean("session-fita", True)
    p.configuracaoDasFitas.fechar()

    assert chamadas == ["reacender"]
    assert p.fitas.configuradas == 1


def test_a3_reacender_das_preferencias_nao_devolve_nem_perde_fita(p, falsas, monkeypatch, schema):  # noqa: ARG001
    """Fechar o assistente com o app aberto não é arranque: sem piscar no estado de antes, e a fita que não
    responde à releitura segue na chave."""
    from tests.apoio_fita import estado_mandado  # noqa: PLC0415

    shared.schema.set_boolean("session-fita", True)
    modulos = falsas(False, False)
    session_fita._guardar_e_vestir()  # noqa: SLF001
    guardado = shared.schema.get_string(session_fita.CHAVE_ESTADO)
    antes = [len(modulo.recebidos) for modulo in modulos.values()]

    modulos["eb1"].quebrada = True
    monkeypatch.setattr(session_fita, "_em_thread", lambda tarefa: tarefa())
    p.abrirConfiguracaoDasFitas()
    p.configuracaoDasFitas.fechar()

    assert shared.schema.get_string(session_fita.CHAVE_ESTADO) == guardado
    novos = modulos["eb0"].recebidos[antes[0] :]
    assert ANTES["cor"] not in [c.get("24") for c in novos]
    assert estado_mandado(modulos["eb0"]) is True


def test_b4_versao_da_varredura_e_resposta_da_consulta_nova(monkeypatch, schema):  # noqa: ARG001
    from cartridges.fita_wizard import com_enderecos  # noqa: PLC0415
    from tests.apoio_fita import FitaFalsa, Msg  # noqa: PLC0415

    achados = {"192.168.0.150": {"gwId": "eb0", "version": "3.4"}}
    (fita,) = com_enderecos(
        [session_fita.Fita("Centro", "eb0", "", "k")],
        session_fita.ips_da_varredura(achados),
        session_fita.versoes_da_varredura(achados),
    )
    assert fita.versao == "3.4"

    class Fita34(FitaFalsa):
        def status(self, nowait=False):  # noqa: ARG002
            self.socket.a_caminho.append(Msg(16, {"dps": dict(self.dps)}))

    session_fita.gravar_fitas([fita._replace(ip="192.168.0.150")])
    monkeypatch.setattr(session_fita, "_dispositivo", lambda _fita: Fita34())
    assert session_fita.ler_estado(session_fita.fitas()[0]) == ANTES


def test_conftest_bloqueia_a_tuya():
    from cartridges import fita_wizard  # noqa: PLC0415

    mensagem = "tuya: nenhuma busca na nuvem nem na rede nos testes"
    with pytest.raises(AssertionError, match=mensagem):
        fita_wizard._nuvem("us", "chave", "segredo")  # noqa: SLF001
    with pytest.raises(AssertionError, match=mensagem):
        session_fita.enderecos_na_rede()


def _thread_presa(monkeypatch):
    """A thread da busca capturada: o teste a roda quando quiser."""
    import cartridges.fita_wizard as wizard_module  # noqa: PLC0415

    tarefas = []
    monkeypatch.setattr(
        wizard_module,
        "threading",
        SimpleNamespace(
            Thread=lambda target, args=(), daemon=False: SimpleNamespace(  # noqa: ARG005
                start=lambda: tarefas.append(lambda: target(*args))
            )
        ),
    )
    return tarefas


def test_resultado_da_busca_depois_de_fechar_e_descartado(p, monkeypatch, flush_idle):
    import cartridges.fita_wizard as wizard_module  # noqa: PLC0415

    tarefas = _thread_presa(monkeypatch)
    monkeypatch.setattr(
        wizard_module,
        "_nuvem",
        lambda *_a: SimpleNamespace(
            getdevices=lambda: [{"name": "Sala", "id": "eb9", "key": "k", "ip": "1.2.3.4"}], token="t", error=None
        ),
    )
    monkeypatch.setattr(session_fita, "enderecos_na_rede", lambda: ({}, {}))
    mostradas = []
    monkeypatch.setattr(wizard_module.FitaWizard, "_mostrar", lambda _eu, achadas: mostradas.append(achadas))
    p.abrirConfiguracaoDasFitas()
    assistente = p.configuracaoDasFitas
    assistente.chave, assistente.segredo = "c", "s"
    assistente.buscar()
    assert assistente.pagina == "buscando"
    assert len(tarefas) == 1

    assistente.fechar()
    assert p.configuracaoDasFitas is None
    tarefas[0]()
    flush_idle()
    # O assistente fechado não recebeu o resultado, e nenhuma fita foi gravada.
    assert mostradas == []
    assert session_fita.fitas() == []


def test_segredo_nunca_vai_ao_log(p, monkeypatch, caplog, flush_idle):
    import logging  # noqa: PLC0415

    import cartridges.fita_wizard as wizard_module  # noqa: PLC0415

    def nuvem(_regiao, chave, segredo):
        raise RuntimeError(f"401 em https://api/?id={chave}&secret={segredo}")

    monkeypatch.setattr(wizard_module, "_nuvem", nuvem)
    monkeypatch.setattr(session_fita, "enderecos_na_rede", lambda: ({}, {}))
    monkeypatch.setattr(
        wizard_module,
        "threading",
        SimpleNamespace(Thread=lambda target, args=(), daemon=False: SimpleNamespace(start=lambda: target(*args))),  # noqa: ARG005
    )
    p.abrirConfiguracaoDasFitas()
    assistente = p.configuracaoDasFitas
    assistente.chave, assistente.segredo = "id-publico", "SEGREDO-DA-CONTA"
    with caplog.at_level(logging.DEBUG):
        assistente.buscar()
        flush_idle()
    assert "SEGREDO-DA-CONTA" not in caplog.text
    assert any("Busca na nuvem da Tuya falhou" in r.getMessage() for r in caplog.records)
    assert assistente.semResultado is True


def test_fechar_as_preferencias_fecha_o_assistente(p, monkeypatch):
    chamadas = []
    monkeypatch.setattr(session_fita, "reacender", lambda: chamadas.append(1))
    p.abrirConfiguracaoDasFitas()
    assert p.configuracaoDasFitas is not None
    p.fechar()
    assert p.configuracaoDasFitas is None


# endregion


# region O assistente de calibração


@pytest.fixture
def previas_da_calibracao(monkeypatch):
    """A prévia de uma fita só (a da etapa de calibração), anotada, sem acender nada."""
    pedidas = []
    monkeypatch.setattr(session_fita, "previa_calibracao", lambda id_, cor, calibracoes: pedidas.append((id_, cor)))
    return pedidas


def test_linha_da_calibracao_segue_o_interruptor_da_iluminacao(app):
    _com_fitas()
    _abrir(app)
    linha = app.achar("linhaCalibrarFitas")
    assert linha.property("titulo") == "Calibrar as cores"
    assert linha.property("subtitulo") == "Ajusta cada dispositivo para reproduzir as cores como a tela"
    assert app.achar("linhaCalibrarFitasBotao").property("dica") == "Abrir o assistente de calibração"
    app.preferencias.definir("session-fita", False)
    assert _esperar(lambda: not _enabled(app, "linhaCalibrarFitas"))
    app.preferencias.definir("session-fita", True)
    assert _esperar(lambda: _enabled(app, "linhaCalibrarFitas"))


def _abrir_a_calibracao(app):
    _com_fitas("Centro", "Direita")
    shared.schema.set_boolean("session-fita", True)
    _abrir(app)
    botao = app.achar("linhaCalibrarFitasBotao")
    botao.forceActiveFocus(Qt.FocusReason.TabFocusReason)
    QMetaObject.invokeMethod(botao, "click", Qt.ConnectionType.DirectConnection)
    dialogo = app.achar("assistenteDeCalibracao")
    assert _esperar(lambda: dialogo.property("visible") is True)
    return dialogo, botao


def test_botao_da_calibracao_abre_o_assistente(app, previas_da_calibracao):
    _abrir_a_calibracao(app)
    assistente = app.preferencias.calibracao
    assert [linha["id"] for linha in assistente.linhas][1:] == ["eb0", "eb1"]
    assert assistente.paginaAtual == "inicio"
    # Só abrir o assistente não acende nada; quem acende é escolher um dispositivo.
    assert previas_da_calibracao == []


def test_abrir_a_calibracao_duas_vezes_nao_cria_outra(p):
    _com_fitas()
    p.abrirCalibracao()
    primeira = p.calibracao
    p.abrirCalibracao()
    assert p.calibracao is primeira


def test_fechar_as_preferencias_fecha_a_calibracao_e_volta_a_cor_do_app(p, previas, previas_da_calibracao):  # noqa: ARG001
    _com_fitas()
    p.abrirCalibracao()
    p.calibracao.escolher("eb0")
    previas.clear()
    p.fechar()
    assert p.calibracao is None
    assert previas == [(session_fita.cor_do_app(), None)]  # uma só, e nenhuma outra por cima


def test_calibracao_foco_tab_e_esc(app, previas, previas_da_calibracao, flush_idle):  # noqa: ARG001
    from PySide6.QtTest import QTest  # noqa: PLC0415

    dialogo, botao = _abrir_a_calibracao(app)
    fechados = []
    app.preferencias.calibracao.fechado.connect(lambda: fechados.append(1))
    previas.clear()
    assert _esperar(lambda: app.achar("dispositivoDaCalibracao-__todos__Botao").hasActiveFocus())
    # O cartão das Preferências fica apagado por trás.
    assert app.achar("cartaoDasPreferencias").property("enabled") is False
    for _ in range(8):
        QTest.keyClick(app.janela, Qt.Key.Key_Tab)
        flush_idle(0.03)
        dentro, item = False, app.janela.activeFocusItem()
        while item is not None:
            dentro = dentro or item is dialogo
            item = item.parentItem()
        assert dentro  # o Tab circula dentro do modal
    QTest.keyClick(app.janela, Qt.Key.Key_Escape)
    assert _esperar(lambda: dialogo.property("visible") is False)
    assert app.preferencias.calibracao is None
    flush_idle(0.1)
    # O Esc de verdade: um `fechado` e uma só volta à cor do app.
    assert fechados == [1]
    assert previas == [(session_fita.cor_do_app(), None)]
    assert app.achar("cartaoDasPreferencias").property("enabled") is True
    assert _esperar(lambda: botao.hasActiveFocus())


# endregion

