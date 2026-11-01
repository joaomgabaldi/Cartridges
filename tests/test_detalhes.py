# test_detalhes.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O modelo da página de detalhes: textos, logo, desfoque e a saída da página."""

import gc
import threading
import time
import weakref

from PIL import Image
from PySide6.QtCore import QEventLoop, QSize, QTimer

from cartridges import shared
from cartridges.jogo import Jogo
from cartridges.modelos import detalhes as modulo
from cartridges.modelos.detalhes import DetalhesDoJogo
from cartridges.utils import desfoque, game_logo


def _jogo(game_id="a", **extra):
    return Jogo({"game_id": game_id, "source": "imported", "name": game_id.upper(), **extra})


def _rodar_ate(condicao, limite=5.0):
    fim = time.monotonic() + limite
    while not condicao() and time.monotonic() < fim:
        laco = QEventLoop()
        QTimer.singleShot(10, laco.quit)
        laco.exec()
    return condicao()


def _modelo(store, *jogos):
    for jogo in jogos:
        store.games_by_id[jogo.game_id] = jogo
    return DetalhesDoJogo(store)


# -- regras puras --------------------------------------------------------------------------------


def test_nota_cinco_simbolos(app_qt):
    assert modulo.nota(_jogo(rating=3)) == "Minha nota: ★★★☆☆"
    assert modulo.nota(_jogo(rating=0)) == ""
    assert modulo.nota(_jogo(rating=9)) == "Minha nota: ★★★★★"


def test_sem_data_esconde_a_linha(app_qt):
    assert modulo.data_de_lancamento(_jogo()) == ""
    assert modulo.data_de_lancamento(_jogo(release_date="inválida")) == ""
    assert modulo.data_de_lancamento(_jogo(release_date="2/set./2026")) == "Data de lançamento: 2/set./2026"


def test_metacritic_e_avaliacoes(app_qt):
    assert modulo.metacritic(_jogo()) == ""
    assert modulo.metacritic(_jogo(metacritic=0)) == "Metacritic: 0"
    assert modulo.avaliacoes(_jogo(steam_review="Muito positivas")) == "Avaliações: Muito positivas"
    assert modulo.avaliacoes(_jogo()) == ""


def test_controle_so_full_e_partial(app_qt):
    assert modulo.controle(_jogo(controller_support="full")) == "Compatibilidade total com controle"
    assert modulo.controle(_jogo(controller_support="partial")) == "Compatibilidade parcial com controle"
    assert modulo.controle(_jogo(controller_support="none")) == ""
    assert modulo.controle(_jogo()) == ""


def test_jogado_nunca(app_qt):
    assert modulo.jogado_por_ultimo(_jogo(last_played=0)) == "Jogado por último: nunca"
    assert modulo.jogado_por_ultimo(_jogo(last_played=int(time.time()))).startswith("Jogado por último: ")
    assert modulo.adicionado(_jogo(added=int(time.time()))).startswith("Adicionado: ")


def test_tempo_de_jogo_e_tamanho(app_qt):
    assert modulo.tempo_de_jogo(_jogo()) == ""
    assert modulo.tempo_de_jogo(_jogo(playtime=3600 * 10)) == "Tempo de jogo: 10 horas"
    assert modulo.tamanho(_jogo(install_size=3 * 1024**3)) == "Tamanho: 3 GB"
    assert modulo.tamanho(_jogo()) == ""


def test_tamanho_some_no_zerado(app_qt):
    zerado = _jogo(install_size=3 * 1024**3, removed=True, status="beaten")
    assert zerado.zerado
    assert modulo.tamanho(zerado) == ""


def test_rotulo_do_status(app_qt):
    assert modulo.rotulo_do_status(_jogo()) == "Definir status"
    assert modulo.rotulo_do_status(_jogo(status="playing")) == "Jogando"
    assert modulo.rotulo_do_status(_jogo(status="inexistente")) == "Definir status"


def test_hltb_separador_vai_com_a_celula_da_direita(app_qt):
    bloco = modulo.hltb(_jogo(hltb_main=3600 * 10, hltb_completionist=3600 * 30))
    assert [c["rotulo"] for c in bloco["celulas"]] == ["História", "Completista"]
    assert [c["separador"] for c in bloco["celulas"]] == [False, True]
    assert bloco["celulas"][0]["valor"] == "10 h"
    assert bloco["capitulos"] == []


def test_hltb_sem_dados_some_inteiro(app_qt):
    assert modulo.hltb(_jogo()) == {"colunas": ["História", "Extras", "Completista"], "celulas": [], "capitulos": []}
    todas = modulo.hltb(_jogo(hltb_main=3600, hltb_main_extra=7200, hltb_completionist=10800))
    assert [c["separador"] for c in todas["celulas"]] == [False, True, True]


def test_hltb_capitulos_trocam_o_cartao(app_qt):
    bloco = modulo.hltb(
        _jogo(
            hltb_main=3600,
            hltb_chapters=[{"number": 1, "hltb_main": 3600}, {"hltb_main_extra": 7200}],
        )
    )
    assert bloco["celulas"] == []
    assert bloco["capitulos"] == [
        {"rotulo": "Capítulo 1", "valores": ["1 h", "—", "—"]},
        {"rotulo": "Capítulo 2", "valores": ["—", "2 h", "—"]},
    ]


def test_anotacao_em_jogando_ou_com_texto(app_qt):
    assert modulo.mostra_anotacao(_jogo(status="playing")) is True
    assert modulo.mostra_anotacao(_jogo(notes="fase 3")) is True
    assert modulo.mostra_anotacao(_jogo(notes="  \n")) is False
    assert modulo.mostra_anotacao(_jogo(status="backlog")) is False
    assert modulo.dica_da_anotacao(_jogo()) == "Anotar onde você parou neste jogo"


def test_anotacao_de_zerado_so_leitura(app_qt, store):
    zerado = _jogo(removed=True, status="beaten", notes="final bom")
    vazio = _jogo("b", removed=True, status="beaten")
    assert modulo.mostra_anotacao(zerado) is True
    assert modulo.mostra_anotacao(vazio) is False
    assert modulo.dica_da_anotacao(zerado) == "Ver onde você parou neste jogo"
    detalhes = _modelo(store, zerado)
    detalhes.mostrar("a")
    assert detalhes.anotacaoEditavel is False
    assert detalhes.anotacao == "final bom"


def test_opacidade_do_fundo(app_qt):
    assert modulo.opacidade_do_fundo((0.2, 0.6), True, False) == 0.8
    assert modulo.opacidade_do_fundo((0.2, 0.6), False, False) == 0.6
    assert modulo.opacidade_do_fundo((0.2, 0.6), True, True) == 0.3


def test_opacidade_do_fundo_segue_o_esquema_de_cores(app_qt, store, monkeypatch):
    from PySide6.QtCore import Qt  # noqa: PLC0415
    from PySide6.QtGui import QGuiApplication  # noqa: PLC0415

    monkeypatch.setattr(modulo, "_alto_contraste", lambda: False)
    Image.new("RGB", (200, 300), (200, 40, 40)).save(shared.covers_dir / "a.tiff")
    detalhes = _modelo(store, _jogo())
    detalhes.mostrar("a")
    assert _rodar_ate(lambda: detalhes.fundo)
    luminancia = desfoque.calcular(shared.covers_dir / "a.tiff").luminancia
    dicas = QGuiApplication.styleHints()
    esperado = {
        Qt.ColorScheme.Dark: 1 - luminancia[0],
        Qt.ColorScheme.Light: luminancia[1],
        Qt.ColorScheme.Unknown: 0.3,
    }
    for esquema, valor in esperado.items():
        monkeypatch.setattr(dicas, "colorScheme", lambda e=esquema: e)
        dicas.colorSchemeChanged.emit(esquema)  # o caminho público: o sistema trocou o tema
        assert detalhes.opacidadeDoFundo == valor, esquema


# -- o modelo --------------------------------------------------------------------------------------


def test_mostrar_preenche_as_propriedades(app_qt, store):
    jogo = _jogo(developer="Estúdio", status="playing", has_hltb=None)
    detalhes = _modelo(store, jogo)
    detalhes.mostrar("a")
    assert (detalhes.jogoId, detalhes.nome, detalhes.desenvolvedora) == ("a", "A", "Estúdio")
    assert detalhes.rotuloDoStatus == "Jogando"
    assert detalhes.mostraAnotacao is True
    assert detalhes.temAtualizacao is False
    detalhes.mostrar("inexistente")  # sem jogo: nada muda
    assert detalhes.jogoId == "a"


def test_atualizado_de_thread_chega_ao_qml(app_qt, store):
    jogo = _jogo()
    detalhes = _modelo(store, jogo)
    detalhes.mostrar("a")
    avisos = []
    detalhes.alterado.connect(lambda: avisos.append(1))

    def mudar():
        jogo.name = "Novo nome"
        jogo.update()

    thread = threading.Thread(target=mudar)
    thread.start()
    thread.join()
    assert _rodar_ate(lambda: detalhes.nome == "Novo nome")
    assert avisos


def test_trocar_de_jogo_desliga_o_anterior(app_qt, store):
    a, b = _jogo("a"), _jogo("b")
    detalhes = _modelo(store, a, b)
    detalhes.mostrar("a")
    detalhes.mostrar("b")
    a.name = "Outro"
    a.update()
    assert detalhes.nome == "B"


def test_excluir_emite_sair(app_qt, store):
    jogo = _jogo(removed=True, status="beaten")
    detalhes = _modelo(store, jogo)
    detalhes.mostrar("a")
    saidas = []
    detalhes.sair.connect(lambda: saidas.append(1))
    store.excluir(jogo)
    assert _rodar_ate(lambda: saidas)


def test_excluir_outro_jogo_nao_emite_sair(app_qt, store):
    detalhes = _modelo(store, _jogo("a"))
    detalhes.mostrar("a")
    saidas = []
    detalhes.sair.connect(lambda: saidas.append(1))
    store.jogo_excluido.emit("b")
    _rodar_ate(lambda: False, 0.1)
    assert not saidas


def test_remover_emite_sair(app_qt, store):
    jogo = _jogo()
    detalhes = _modelo(store, jogo)
    detalhes.mostrar("a")
    saidas = []
    detalhes.sair.connect(lambda: saidas.append(1))
    jogo.remove_game()
    assert saidas == [1]


def test_sair_do_zerado_sem_voltar(app_qt, store):
    zerado = _jogo(removed=True, status="beaten")
    detalhes = _modelo(store, zerado)
    detalhes.mostrar("a")
    saidas = []
    detalhes.sair.connect(lambda: saidas.append(1))
    zerado.update()  # continua zerado: a página fica
    assert saidas == []
    zerado.status = "dropped"
    zerado.update()
    assert saidas == [1]


# -- logo --------------------------------------------------------------------------------------------


def _logo_em_disco(nome):
    shared.logos_dir.mkdir(parents=True, exist_ok=True)
    caminho = shared.logos_dir / nome
    Image.new("RGBA", (400, 100), "white").save(caminho)
    return caminho


def _fetch_travado(monkeypatch, resultados):
    """`fetch_logo` falso que espera o `Event`; devolve (event, chamadas)."""
    liberar, chamadas = threading.Event(), []

    def falso(jogo):
        chamadas.append(jogo.game_id)
        liberar.wait(5)
        return resultados.get(jogo.game_id)

    monkeypatch.setattr(game_logo, "fetch_logo", falso)
    return liberar, chamadas


def test_logo_em_disco_aparece_sem_busca(app_qt, store, schema):
    schema["sgdb-key"] = "chave"
    caminho = _logo_em_disco("a.png")
    game_logo._write_sidecar("a", "A", "a.png")  # noqa: SLF001
    detalhes = _modelo(store, _jogo())
    detalhes.mostrar("a")
    assert detalhes.logo.startswith("file:///") and "a.png" in detalhes.logo
    assert detalhes.larguraDoLogo == 288  # 400x100 cabe em 72 de altura
    assert caminho.exists()


def test_logo_atrasado_de_outro_jogo_e_descartado(app_qt, store, schema, monkeypatch):
    schema["sgdb-key"] = "chave"
    liberar, chamadas = _fetch_travado(monkeypatch, {"a": _logo_em_disco("a.png")})
    detalhes = _modelo(store, _jogo("a"), _jogo("b"))
    detalhes.mostrar("a")
    detalhes.mostrar("b")
    liberar.set()
    assert _rodar_ate(lambda: not detalhes._buscas_de_logo)  # noqa: SLF001
    assert sorted(chamadas) == ["a", "b"]
    assert detalhes.jogoId == "b"
    assert detalhes.logo == ""


def test_logo_do_mesmo_jogo_revisitado_aparece(app_qt, store, schema, monkeypatch):
    schema["sgdb-key"] = "chave"
    liberar, chamadas = _fetch_travado(monkeypatch, {"a": _logo_em_disco("a.png")})
    detalhes = _modelo(store, _jogo("a"), _jogo("b"))
    detalhes.mostrar("a")
    detalhes.mostrar("b")
    detalhes.mostrar("a")
    liberar.set()
    assert _rodar_ate(lambda: detalhes.logo)
    assert "a.png" in detalhes.logo
    assert chamadas.count("a") == 1  # a busca em andamento não é repetida


def test_busca_que_falha_libera_o_jogo(app_qt, store, schema, monkeypatch):
    schema["sgdb-key"] = "chave"

    def quebra(_jogo):
        raise RuntimeError("falha")

    monkeypatch.setattr(game_logo, "fetch_logo", quebra)
    detalhes = _modelo(store, _jogo())
    detalhes.mostrar("a")
    assert _rodar_ate(lambda: not detalhes._buscas_de_logo)  # noqa: SLF001
    assert detalhes.logo == ""


# -- desfoque ----------------------------------------------------------------------------------------


def test_desfoque_sem_capa_usa_placeholder(app_qt, store, tmp_path):
    assert desfoque.calcular(None) is None
    assert desfoque.calcular(tmp_path / "nao-existe.tiff") is None
    detalhes = _modelo(store, _jogo())
    detalhes.mostrar("a")
    assert detalhes.fundo == ""
    assert detalhes._luminancia == (0.3, 0.5)  # noqa: SLF001


def test_desfoque_com_capa_serve_o_png(app_qt, store):
    Image.new("RGB", (200, 300), (200, 40, 40)).save(shared.covers_dir / "a.tiff")
    detalhes = _modelo(store, _jogo())
    detalhes.mostrar("a")
    assert _rodar_ate(lambda: detalhes.fundo)
    assert detalhes.fundo.startswith("image://desfoque/a?v=")
    imagem = detalhes.provedor.requestImage("a?v=1", QSize(), QSize())
    assert (imagem.width(), imagem.height()) == (100, 150)
    assert detalhes.provedor.requestImage("b", QSize(), QSize()).isNull()


def _calcular_travado(monkeypatch):
    """`desfoque.calcular` falso que espera o `Event`; devolve (event, chamadas)."""
    liberar, chamadas = threading.Event(), []
    real = desfoque.calcular

    def falso(caminho):
        chamadas.append(caminho)
        liberar.wait(5)
        return real(caminho)

    monkeypatch.setattr(desfoque, "calcular", falso)
    return liberar, chamadas


def test_desfoque_de_outro_jogo_e_descartado(app_qt, store, monkeypatch):
    Image.new("RGB", (200, 300), "red").save(shared.covers_dir / "a.tiff")
    liberar, chamadas = _calcular_travado(monkeypatch)
    detalhes = _modelo(store, _jogo("a"), _jogo("b"))
    detalhes.mostrar("a")
    assert _rodar_ate(lambda: chamadas)
    detalhes.mostrar("b")  # b não tem capa
    entregas = []
    original = detalhes._fundo_chegou  # noqa: SLF001
    monkeypatch.setattr(detalhes, "_fundo_chegou", lambda *a: (entregas.append(a), original(*a)))
    liberar.set()
    assert _rodar_ate(lambda: entregas)  # o resultado de "a" chegou, e foi descartado
    assert detalhes.jogoId == "b"
    assert detalhes.fundo == ""


def test_desfoque_em_voo_entre_sair_e_mostrar_nao_trava_o_fundo(app_qt, store, monkeypatch):
    Image.new("RGB", (200, 300), "red").save(shared.covers_dir / "a.tiff")
    liberar, chamadas = _calcular_travado(monkeypatch)
    detalhes = _modelo(store, _jogo())
    detalhes.mostrar("a")
    assert _rodar_ate(lambda: chamadas)
    detalhes._excluido("a")  # noqa: SLF001  (o `sair`: o modelo para de seguir o jogo)
    entregas = []
    original = detalhes._fundo_chegou  # noqa: SLF001
    monkeypatch.setattr(detalhes, "_fundo_chegou", lambda *a: (entregas.append(a), original(*a)))
    liberar.set()
    assert _rodar_ate(lambda: entregas)  # chegou sem página: descartado
    assert detalhes.fundo == ""
    detalhes.mostrar("a")
    assert _rodar_ate(lambda: detalhes.fundo)


def test_desfoque_que_falha_ainda_entrega(app_qt, store, monkeypatch):
    Image.new("RGB", (200, 300), "red").save(shared.covers_dir / "a.tiff")

    def quebra(_caminho):
        raise MemoryError

    monkeypatch.setattr(desfoque, "calcular", quebra)
    detalhes = _modelo(store, _jogo())
    entregas = []
    original = detalhes._fundo_chegou  # noqa: SLF001
    monkeypatch.setattr(detalhes, "_fundo_chegou", lambda *a: (entregas.append(a), original(*a)))
    detalhes.mostrar("a")
    assert _rodar_ate(lambda: entregas)
    assert entregas[0][2] is None and detalhes.fundo == ""


def test_a_new_cover_recomputes_the_blur_for_the_open_page(app_qt, store):
    """Uma capa dada a um jogo com a página aberta refaz o fundo, que ficaria no de reserva para sempre."""
    jogo = _jogo()
    detalhes = _modelo(store, jogo)
    detalhes.mostrar("a")
    assert detalhes.fundo == ""
    Image.new("RGB", (200, 300), "red").save(shared.covers_dir / "a.tiff")
    jogo.update()
    assert _rodar_ate(lambda: detalhes.fundo)
    assert detalhes.fundo.startswith("image://desfoque/a?v=")


def test_editing_the_cover_refreshes_the_open_details_page(app_qt, store):
    """A capa trocada com a página aberta chega à página (a URL muda e o QML relê o arquivo)."""
    import os  # noqa: PLC0415

    capa = shared.covers_dir / "a.tiff"
    Image.new("RGB", (200, 300), "red").save(capa)
    jogo = _jogo()
    detalhes = _modelo(store, jogo)
    detalhes.mostrar("a")
    antes = detalhes.capa
    Image.new("RGB", (200, 300), "blue").save(capa)
    os.utime(capa, ns=(1_000_000_000, 1_000_000_000))
    jogo.update()
    assert detalhes.capa.startswith("file:///") and detalhes.capa != antes


def test_an_unchanged_apply_keeps_the_computed_blur(app_qt, store, monkeypatch):
    """Aplicar sem trocar a capa não refaz o desfoque nem apaga o fundo (a página piscava preta)."""
    Image.new("RGB", (200, 300), "green").save(shared.covers_dir / "a.tiff")
    jogo = _jogo()
    detalhes = _modelo(store, jogo)
    detalhes.mostrar("a")
    assert _rodar_ate(lambda: detalhes.fundo)
    fundo = detalhes.fundo
    calculos = []
    monkeypatch.setattr(desfoque, "calcular", lambda caminho: calculos.append(caminho))
    jogo.name = "Outro nome"
    jogo.update()
    _rodar_ate(lambda: False, 0.2)
    assert calculos == [] and detalhes.fundo == fundo


def test_uma_atualizacao_um_aviso(app_qt, store):
    detalhes = _modelo(store, _jogo())
    avisos = []
    detalhes.alterado.connect(lambda: avisos.append(1))
    detalhes.mostrar("a")
    assert len(avisos) == 1


def test_depois_do_sair_nao_segue_mais(app_qt, store):
    jogo = _jogo()
    detalhes = _modelo(store, jogo)
    detalhes.mostrar("a")
    saidas = []
    detalhes.sair.connect(lambda: saidas.append(1))
    jogo.remove_game()
    jogo.update()
    jogo.name = "Outro"
    jogo.update()
    assert saidas == [1]
    assert detalhes.nome == "A"


def test_esquecer_descarta_logo_e_desfoque_atrasados(app_qt, store, schema, monkeypatch):
    schema["sgdb-key"] = "chave"
    Image.new("RGB", (200, 300), "red").save(shared.covers_dir / "a.tiff")
    liberar, _chamadas = _fetch_travado(monkeypatch, {"a": _logo_em_disco("a.png")})
    liberar_fundo, chamadas_fundo = _calcular_travado(monkeypatch)
    detalhes = _modelo(store, _jogo())
    detalhes.mostrar("a")
    assert _rodar_ate(lambda: chamadas_fundo)
    detalhes.esquecer()
    liberar.set()
    liberar_fundo.set()
    assert _rodar_ate(lambda: not detalhes._buscas_de_logo)  # noqa: SLF001
    _rodar_ate(lambda: False, 0.3)
    assert detalhes.logo == "" and detalhes.fundo == ""


# -- vida útil -----------------------------------------------------------------------------------------


def test_detalhes_nao_prende_o_jogo(app_qt, store):
    jogo = _jogo()
    detalhes = _modelo(store, jogo)
    detalhes.mostrar("a")
    _rodar_ate(lambda: False, 0.1)
    referencia = weakref.ref(jogo)
    store.games_by_id.clear()
    del jogo
    gc.collect()
    assert referencia() is None
    detalhes._ao_atualizar()  # noqa: SLF001  (o jogo morreu: nada a fazer)
