# test_avisos.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A fila de avisos (um por vez) e o "Desfazer" da remoção de um jogo."""

import time

import pytest
from PySide6.QtCore import QEventLoop, QTimer

from cartridges import shared
from cartridges.jogo import Jogo
from cartridges.modelos.avisos import FilaDeAvisos
from cartridges.ponte import Ponte


def _esperar(ate=None, limite=3.0, minimo=0.0):
    fim, inicio = time.monotonic() + limite, time.monotonic()
    while time.monotonic() < fim:
        laco = QEventLoop()
        QTimer.singleShot(10, laco.quit)
        laco.exec()
        if ate is not None and ate() and time.monotonic() - inicio >= minimo:
            return True
    return ate is None


def test_um_por_vez_na_ordem(app_qt):
    fila = FilaDeAvisos()
    fila.adicionar("um", segundos=0)
    segundo = fila.adicionar("dois", segundos=0)
    assert (fila.texto, fila.visivel) == ("um", True)
    fila.fechar()
    assert (fila.texto, fila.visivel) == ("dois", True)
    fila.dispensar(segundo)
    assert fila.visivel is False


def test_dispensar_um_da_fila(app_qt):
    fila = FilaDeAvisos()
    fila.adicionar("um", segundos=0)
    do_meio = fila.adicionar("dois", segundos=0)
    fila.adicionar("tres", segundos=0)
    fila.dispensar(do_meio)
    fila.fechar()
    assert fila.texto == "tres"


def test_dispensar_depois_conta_quando_aparece(app_qt):
    fila = FilaDeAvisos()
    fila.adicionar("um", segundos=0)
    segundo = fila.adicionar("dois", segundos=0)
    fila.dispensar_depois(segundo, 0.15)
    _esperar(minimo=0.3)
    assert fila.texto == "um"  # ainda na fila: a contagem não começou
    fila.fechar()
    assert (fila.texto, fila.visivel) == ("dois", True)
    assert _esperar(lambda: not fila.visivel)


def test_segundos_fecha_sozinho(app_qt):
    fila = FilaDeAvisos()
    fila.adicionar("oi", segundos=0.05)
    assert fila.visivel
    assert _esperar(lambda: not fila.visivel)


def test_mesma_chave_substitui(app_qt):
    fila = FilaDeAvisos()
    fila.adicionar("a", segundos=0)
    fila.adicionar("b1", segundos=0, chave=("x", "remove"))
    fila.adicionar("b2", segundos=0, chave=("x", "remove"))  # na fila: troca no lugar
    fila.fechar()
    assert fila.texto == "b2"
    fila.adicionar("b3", segundos=0, chave=("x", "remove"))  # na tela: troca a da tela
    assert fila.texto == "b3"
    fila.fechar()
    assert fila.visivel is False


def test_clicar_roda_a_acao_e_fecha(app_qt):
    fila, feito = FilaDeAvisos(), []
    fila.adicionar("oi", "Desfazer", lambda: feito.append(1), segundos=0)
    assert fila.botao == "Desfazer"
    fila.clicar()
    assert feito == [1] and fila.visivel is False


class _Loja(dict):
    """O mínimo da Store que o desfazer consulta."""


@pytest.fixture(autouse=True)
def loja(dados_temporarios, monkeypatch):
    loja = _Loja()
    monkeypatch.setattr(shared, "store", loja)
    monkeypatch.setattr(shared, "games_dir", dados_temporarios / "games")
    (dados_temporarios / "games").mkdir(exist_ok=True)
    return loja


def _remover(ponte, jogo):
    shared.store[jogo.game_id] = jogo
    (shared.games_dir / f"{jogo.game_id}.json").write_text("{}")
    ponte.ligar(jogo)
    jogo.save = lambda: gravados.append(jogo.game_id)
    jogo.remove_game()


gravados: list = []


def test_desfazer_devolve_o_jogo(app_qt):
    gravados.clear()
    ponte = Ponte()
    jogo = Jogo({"game_id": "a", "source": "imported", "name": "Alfa"})
    atualizados = []
    jogo.atualizado.connect(lambda: atualizados.append(jogo.removed))
    _remover(ponte, jogo)
    fila = ponte.fila
    assert (fila.texto, fila.botao, jogo.removed) == ("Alfa removido", "Desfazer", True)
    fila.clicar()
    assert jogo.removed is False
    assert gravados == ["a", "a"]  # a remoção e o desfazer
    assert atualizados[-1] is False
    assert fila.visivel is False


def test_excluir_dispensa_o_desfazer(app_qt):
    gravados.clear()
    ponte = Ponte()
    jogo = Jogo({"game_id": "a", "source": "imported", "name": "Alfa"})
    _remover(ponte, jogo)
    ponte.fila.adicionar("outro", segundos=0)  # na fila, atrás do desfazer
    ponte.dispensar_desfazer("a")
    assert ponte.fila.texto == "outro"  # o desfazer saiu da tela
    ponte.fila.fechar()
    assert ponte.fila.visivel is False


def test_excluir_chega_enfileirado_da_store(app_qt):
    from PySide6.QtCore import Signal  # noqa: PLC0415
    from PySide6.QtCore import QObject  # noqa: PLC0415

    class Falsa(QObject):
        jogo_excluido = Signal(str)

    gravados.clear()
    ponte, store = Ponte(), Falsa()
    ponte.ligar_store(store)
    jogo = Jogo({"game_id": "a", "source": "imported", "name": "Alfa"})
    _remover(ponte, jogo)
    store.jogo_excluido.emit("a")
    assert _esperar(lambda: not ponte.fila.visivel)


def test_desfazer_de_jogo_excluido_nao_levanta(app_qt):
    gravados.clear()
    ponte = Ponte()
    jogo = Jogo({"game_id": "a", "source": "imported", "name": "Alfa"})
    _remover(ponte, jogo)
    shared.store.pop("a")
    del jogo
    import gc  # noqa: PLC0415

    gc.collect()
    ponte.fila.clicar()  # o jogo já foi embora: nada a fazer
    assert ponte.fila.visivel is False
    assert gravados == ["a"]


def test_aviso_simples_sem_botao(app_qt):
    ponte = Ponte()
    jogo = Jogo({"game_id": "a", "source": "imported", "name": "<b>Alfa</b>"})
    ponte.ligar(jogo)
    jogo.aviso.emit("<b>Alfa</b> iniciado", "")
    assert (ponte.fila.texto, ponte.fila.botao) == ("<b>Alfa</b> iniciado", "")


def test_desfazer_de_jogo_tirado_da_store_nao_regrava(app_qt, loja):
    gravados.clear()
    ponte = Ponte()
    jogo = Jogo({"game_id": "a", "source": "imported", "name": "Alfa"})
    _remover(ponte, jogo)
    del loja["a"]  # excluído, com o jogo ainda vivo e o sinal ainda na fila
    ponte.fila.clicar()
    assert jogo.removed is True and gravados == ["a"] and ponte.fila.visivel is False


def test_desfazer_sem_a_ficha_em_disco_nao_regrava(app_qt):
    gravados.clear()
    ponte = Ponte()
    jogo = Jogo({"game_id": "a", "source": "imported", "name": "Alfa"})
    _remover(ponte, jogo)
    (shared.games_dir / "a.json").unlink()
    ponte.fila.clicar()
    assert jogo.removed is True and gravados == ["a"]
