# test_edicao_fita.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A linha "Iluminação inteligente" do editor, sobre o `ModeloDaEdicao`; nenhuma fita de verdade (`session_fita.previa` é espionada e `_dispositivo` levanta)."""

from types import SimpleNamespace

import pytest
from PIL import Image
from PySide6.QtGui import QColor

from cartridges import edicao as regra
from cartridges.modelos.edicao import ModeloDaEdicao
from cartridges.utils import session_fita
from tests.apoio_edicao import jogo
from tests.apoio_fita import pastas  # noqa: F401  # a pasta descartável das fitas (autouse)


@pytest.fixture
def aplicativo():
    return SimpleNamespace(pedir_dialogo=lambda *_a: None)


@pytest.fixture
def previas(monkeypatch):
    """As prévias que o editor pediu às fitas, em ordem. Nada acende de verdade."""
    pedidas = []
    monkeypatch.setattr(session_fita, "previa", lambda cor, *a, **k: pedidas.append(cor))
    return pedidas


@pytest.fixture
def editor(store, schema, aplicativo, previas):
    modelo = ModeloDaEdicao(aplicativo)
    yield modelo
    modelo.cancelar()


def _com_fita():
    session_fita.gravar_fitas([session_fita.Fita("Centro", "eb0", "192.0.2.10", "chave")])


def _capa(app_dirs, game_id, cor):
    Image.new("RGB", (60, 90), cor).save(app_dirs.covers / f"{game_id}.tiff")


def _capa_verde(tmp_path):
    """Uma capa provisória verde, longe da emenda do vermelho no círculo."""
    caminho = tmp_path / "provisoria.tiff"
    Image.new("RGB", (60, 90), (20, 200, 20)).save(caminho)
    return caminho


def _jogo(store, app_dirs, cor=(220, 20, 20)):
    """Um jogo de verdade na store, com capa vermelha no disco."""
    game = jogo(store, 1, name="Jogo", executable=r'start "" "C:\g\jogo.exe"')
    _capa(app_dirs, game.game_id, cor)
    return game


def _cor(matiz, saturacao=1.0):
    return QColor.fromHsvF(matiz / 360, saturacao, 1.0)


def _matiz(modelo):
    return round(modelo.fitaCor.hsvHueF() * 360)


def test_sem_fita_linhas_apagadas_com_o_aviso(editor, store, app_dirs, monkeypatch, previas):
    """Sem fita configurada não há cor para escolher, nem para calcular, nem para gravar."""
    game = _jogo(store, app_dirs)
    guardada = session_fita.Cor(340, 1000, 150)
    session_fita.salvar_cor(game.game_id, game.name, guardada)
    # Tirar a dominante da capa custa milissegundos na thread principal: sem fita, não se gasta.
    monkeypatch.setattr(
        session_fita, "dominante", lambda *_a, **_k: pytest.fail("calculou a cor da capa sem fita configurada")
    )

    editor.abrir(game.game_id)

    assert editor.fitaDisponivel is False
    assert editor.fitaSubtitulo == "Nenhum dispositivo configurado"
    assert editor.fitaAutomatica is False
    editor.escolherCorDaFita(_cor(200))
    editor.definirBrilhoDaFita(50)
    editor.redefinirFita()
    assert previas == []
    # E o Aplicar não apaga a cor que o jogo já tinha, nem marca escolha nova.
    editor.nome = "Jogo renomeado"
    editor.aplicar()
    assert session_fita.cor_do_jogo(game) == guardada


def test_subtitulos_manual_automatico_e_da_capa(editor, store, app_dirs, schema):
    _com_fita()
    game = _jogo(store, app_dirs)

    editor.abrir(game.game_id)
    assert editor.fitaDisponivel is True
    assert editor.fitaSubtitulo == "Extraída da capa"
    assert editor.dicaDeVoltar == "Voltar a escolher a cor a partir da capa"
    assert editor.fitaManual is False
    editor.cancelar()

    schema.set_boolean("fita-acompanha-tela", True)
    editor.abrir(game.game_id)
    assert editor.fitaSubtitulo == "Automático"
    assert editor.dicaDeVoltar == "Voltar ao automático"
    assert editor.fitaAutomatica is True
    editor.cancelar()

    session_fita.salvar_cor(game.game_id, game.name, session_fita.Cor(340, 1000, 150))
    editor.abrir(game.game_id)
    assert editor.fitaSubtitulo == "Escolhida manualmente"
    assert editor.fitaManual is True
    assert editor.fitaAutomatica is False
    assert round(editor.fitaBrilho) == session_fita.por_cento(150)


def test_mexer_na_cor_acende_a_previa(editor, store, app_dirs, previas):
    """Cada tentativa de cor aparece nas fitas na hora, ainda dentro do seletor, sem gravar nada."""
    _com_fita()
    game = _jogo(store, app_dirs)
    editor.abrir(game.game_id)
    assert previas == []

    editor.escolherCorDaFita(_cor(200))
    assert abs(previas[-1].matiz - 200) <= 2
    assert previas[-1].brilho == session_fita.brilho_padrao()
    assert editor.fitaManual is False  # prévia não é escolha
    assert not session_fita.escolhida(game.game_id)

    editor.definirBrilhoDaFita(40)
    assert previas[-1].brilho == session_fita.de_por_cento(40)
    assert abs(previas[-1].matiz - 200) <= 2


def test_fechar_sem_previa_nao_repinta(editor, store, app_dirs, previas):
    """Abrir e fechar a tela de um jogo qualquer não repinta as fitas; com prévia, o fechar as devolve ao app."""
    _com_fita()
    game = _jogo(store, app_dirs)
    editor.abrir(game.game_id)
    editor.cancelar()
    assert previas == []

    editor.abrir(game.game_id)
    editor.escolherCorDaFita(_cor(200))
    editor.cancelar()
    assert previas[-1] == session_fita.cor_do_app()
    # E aplicar também fecha: a cor do jogo só vale na sessão.
    previas.clear()
    editor.abrir(game.game_id)
    editor.escolherCorDaFita(_cor(120))
    editor.aplicar()
    assert previas[-1] == session_fita.cor_do_app()


def test_renomear_nao_grava_cor(editor, store, app_dirs):
    """Quem abriu a tela só para renomear não pediu cor: gravar tiraria o jogo da cor automática para sempre."""
    _com_fita()
    game = _jogo(store, app_dirs)
    editor.abrir(game.game_id)
    editor.nome = "Outro nome"
    editor.aplicar()

    assert game.name == "Outro nome"
    assert session_fita.escolhida(game.game_id) is False
    assert session_fita.brilho_escolhido(game.game_id) is None


def test_aplicar_a_cor_e_escolha_manual(editor, store, app_dirs):
    _com_fita()
    game = _jogo(store, app_dirs)
    editor.abrir(game.game_id)
    editor.escolherCorDaFita(_cor(120))
    editor.aplicar()

    assert session_fita.escolhida(game.game_id)
    assert abs(session_fita.cor_do_jogo(game).matiz - 120) <= 2


def test_so_brilho_mantem_a_cor_automatica(editor, store, app_dirs, schema):
    """O brilho é separado da cor: mexido, a roda continua e o jogo segue na cor automática."""
    schema.set_boolean("fita-acompanha-tela", True)
    _com_fita()
    game = _jogo(store, app_dirs)
    editor.abrir(game.game_id)
    editor.definirBrilhoDaFita(40)
    assert editor.fitaAutomatica is True

    editor.aplicar()

    assert not session_fita.escolhida(game.game_id)
    assert session_fita.brilho_escolhido(game.game_id) == session_fita.de_por_cento(40)
    editor.abrir(game.game_id)
    assert editor.fitaSubtitulo == "Automático"
    assert editor.fitaBrilho == 40


def test_o_brilho_de_volta_ao_padrao_apaga_o_proprio(editor, store, app_dirs):
    _com_fita()
    game = _jogo(store, app_dirs)
    session_fita.salvar_brilho(game.game_id, game.name, 400)
    editor.abrir(game.game_id)
    editor.definirBrilhoDaFita(session_fita.por_cento(session_fita.brilho_padrao()))
    editor.aplicar()

    assert session_fita.brilho_escolhido(game.game_id) is None


def test_cor_mexida_nao_e_mais_a_roda(editor, store, app_dirs, schema):
    schema.set_boolean("fita-acompanha-tela", True)
    _com_fita()
    game = _jogo(store, app_dirs)
    editor.abrir(game.game_id)
    assert editor.fitaAutomatica is True

    editor.escolherCorDaFita(_cor(200))

    assert editor.fitaAutomatica is False


def test_voltar_ao_automatico_apaga_no_aplicar(editor, store, app_dirs):
    """A intenção fica em memória até o Aplicar: quem fecha no X não pediu para perder a cor escolhida."""
    _com_fita()
    game = _jogo(store, app_dirs)
    session_fita.salvar_cor(game.game_id, game.name, session_fita.Cor(340, 1000, 150))
    editor.abrir(game.game_id)

    editor.redefinirFita()

    assert session_fita.escolhida(game.game_id)  # ainda em disco
    assert editor.fitaManual is False
    assert editor.fitaSubtitulo == "Extraída da capa"
    editor.aplicar()
    assert not session_fita.escolhida(game.game_id)


def test_voltar_ao_automatico_sem_aplicar_nao_apaga(editor, store, app_dirs):
    _com_fita()
    game = _jogo(store, app_dirs)
    session_fita.salvar_cor(game.game_id, game.name, session_fita.Cor(340, 1000, 150))
    editor.abrir(game.game_id)
    editor.redefinirFita()
    editor.cancelar()

    assert session_fita.escolhida(game.game_id)


def test_cor_depois_de_voltar_cancela_a_redefinicao(editor, store, app_dirs):
    """O que vale é o que está na tela na hora do Aplicar."""
    _com_fita()
    game = _jogo(store, app_dirs)
    session_fita.salvar_cor(game.game_id, game.name, session_fita.Cor(340, 1000, 150))
    editor.abrir(game.game_id)
    editor.redefinirFita()
    editor.escolherCorDaFita(_cor(120))
    editor.aplicar()

    assert session_fita.escolhida(game.game_id)
    assert abs(session_fita.cor_do_jogo(game).matiz - 120) <= 2


def test_capa_nova_leva_a_cor_intocada(editor, store, app_dirs, tmp_path, previas):
    """A linha diz "Extraída da capa": tem de ser a capa que a tela mostra, e não a gravada no disco."""
    _com_fita()
    game = _jogo(store, app_dirs)
    editor.abrir(game.game_id)
    assert editor.fitaCor.hsvHueF() * 360 < 10 or editor.fitaCor.hsvHueF() * 360 > 350

    editor._trocar_capa(_capa_verde(tmp_path))  # noqa: SLF001

    assert abs(_matiz(editor) - 120) <= 2
    assert editor.fitaSubtitulo == "Extraída da capa"
    # Trocar a capa não acende a fita (a prévia é para quem mexe na cor) nem vira escolha.
    assert previas == []
    regra.aplicar_fita(editor._form, game)  # noqa: SLF001
    assert session_fita.escolhida(game.game_id) is False


def test_cor_mexida_sobrevive_a_troca_de_capa(editor, store, app_dirs, tmp_path):
    _com_fita()
    game = _jogo(store, app_dirs)
    editor.abrir(game.game_id)
    editor.escolherCorDaFita(_cor(240))

    editor._trocar_capa(_capa_verde(tmp_path))  # noqa: SLF001

    assert abs(_matiz(editor) - 240) <= 2


def test_cor_escolhida_nao_segue_a_capa_nova(editor, store, app_dirs, tmp_path):
    _com_fita()
    game = _jogo(store, app_dirs)
    session_fita.salvar_cor(game.game_id, game.name, session_fita.Cor(340, 1000, 150))
    editor.abrir(game.game_id)

    editor._trocar_capa(_capa_verde(tmp_path))  # noqa: SLF001

    assert abs(_matiz(editor) - 340) <= 2
    assert editor.fitaSubtitulo == "Escolhida manualmente"


def test_voltar_ao_automatico_e_trocar_a_capa_segue_a_capa_nova(editor, store, app_dirs, tmp_path):
    _com_fita()
    game = _jogo(store, app_dirs)
    session_fita.salvar_cor(game.game_id, game.name, session_fita.Cor(340, 1000, 150))
    editor.abrir(game.game_id)
    editor.redefinirFita()

    editor._trocar_capa(_capa_verde(tmp_path))  # noqa: SLF001

    assert abs(_matiz(editor) - 120) <= 2
    editor.aplicar()  # a redefinição continua de pé
    assert not session_fita.escolhida(game.game_id)


def test_brilho_mexido_e_capa_trocada_segue_a_capa_nova(editor, store, app_dirs, tmp_path):
    _com_fita()
    game = _jogo(store, app_dirs)
    editor.abrir(game.game_id)
    editor.definirBrilhoDaFita(40)

    editor._trocar_capa(_capa_verde(tmp_path))  # noqa: SLF001

    assert abs(_matiz(editor) - 120) <= 2
    assert editor.fitaBrilho == 40


def test_capa_excluida_volta_a_cor_do_app(editor, store, app_dirs):
    _com_fita()
    game = _jogo(store, app_dirs, cor=(20, 200, 20))
    editor.abrir(game.game_id)
    assert abs(_matiz(editor) - 120) <= 2

    editor.excluirCapa()

    assert editor._form.fita_na_tela == session_fita.cor_do_app()  # noqa: SLF001


def test_jogo_novo_com_capa_provisoria_mostra_a_cor_dela(editor, tmp_path):
    _com_fita()
    editor.adicionar()
    assert editor.fitaDisponivel is True
    assert editor.fitaManual is False

    editor._trocar_capa(_capa_verde(tmp_path))  # noqa: SLF001

    assert abs(_matiz(editor) - 120) <= 2


def test_abrir_a_edicao_calcula_a_cor_da_capa_uma_vez(editor, store, app_dirs, monkeypatch):
    _com_fita()
    game = _jogo(store, app_dirs)
    chamadas = []
    de_verdade = session_fita.dominante
    monkeypatch.setattr(session_fita, "dominante", lambda capa: chamadas.append(capa) or de_verdade(capa))

    editor.abrir(game.game_id)

    assert len(chamadas) == 1


def test_a_cor_cheia_nao_leva_o_brilho_da_fita(editor, store, app_dirs):
    """Um roxo a 18% apareceria quase preto no quadradinho: o seletor mostra a cor cheia."""
    _com_fita()
    game = _jogo(store, app_dirs)
    session_fita.salvar_cor(game.game_id, game.name, session_fita.Cor(284, 620, 180))
    editor.abrir(game.game_id)

    assert editor.fitaCor.valueF() == pytest.approx(1.0, abs=0.01)
    assert editor.fitaBrilho == session_fita.por_cento(180)


def test_a_regra_de_mesmo_tom_e_circular():
    cor = session_fita.Cor
    assert regra.mesmo_tom(cor(359, 800, 0), cor(1, 805, 900))
    assert not regra.mesmo_tom(cor(10, 800, 0), cor(20, 800, 0))
    assert not regra.mesmo_tom(cor(10, 800, 0), cor(10, 600, 0))


def test_cor_gravada_sem_fita_configurada_nao_mostra_o_voltar(editor, store, app_dirs):
    """Sem dispositivo a linha está apagada: o botão de voltar ao automático não aparece nela."""
    game = _jogo(store, app_dirs)
    session_fita.salvar_cor(game.game_id, game.name, session_fita.Cor(340, 1000, 150))
    editor.abrir(game.game_id)

    assert editor.fitaDisponivel is False
    assert editor.fitaManual is False


def test_voltar_ao_automatico_so_acende_se_a_cor_muda(editor, store, app_dirs, previas):
    """Sem mudança de cor, nada é repintado."""
    _com_fita()
    game = _jogo(store, app_dirs)
    editor.abrir(game.game_id)
    editor.escolherCorDaFita(_cor(120))
    editor.redefinirFita()  # a cor volta da escolhida nesta tela para a da capa
    assert len(previas) == 2 and previas[-1].matiz < 20

    editor.redefinirFita()  # a cor já é a da capa
    assert len(previas) == 2
