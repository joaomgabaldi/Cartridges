# test_detalhes.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O modelo da página de detalhes: textos, logo, desfoque e a saída da página."""

import gc
import threading
import time
import weakref

import pytest
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
    assert _rodar_ate(lambda: detalhes.fundo)  # a thread do desfoque não pode estar lendo a capa ao regravá-la
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


def test_thread_de_fundo_e_de_logo_nao_seguram_o_modelo(app_qt, store, monkeypatch):
    """Com as threads presas, apagar o modelo o solta; ao soltá-las nada é entregue e nada quebra."""
    Image.new("RGB", (200, 300), "red").save(shared.covers_dir / "a.tiff")
    preso, solto = threading.Event(), threading.Event()
    monkeypatch.setattr(desfoque, "calcular", lambda _c: (preso.set(), solto.wait(5))[1] and None)
    monkeypatch.setattr(game_logo, "logo_lookup_needed", lambda _j: True)
    monkeypatch.setattr(game_logo, "fetch_logo", lambda _j: solto.wait(5) and None)
    detalhes = _modelo(store, _jogo())
    entregas = []
    monkeypatch.setattr(modulo.DetalhesDoJogo, "_fundo_chegou", lambda *a: entregas.append(a))
    monkeypatch.setattr(modulo.DetalhesDoJogo, "_logo_chegou", lambda *a: entregas.append(a))
    detalhes.mostrar("a")
    assert preso.wait(5)
    fraco = weakref.ref(detalhes)
    del detalhes
    gc.collect()
    assert fraco() is None
    solto.set()
    _rodar_ate(lambda: False, 0.3)
    assert entregas == []


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


def test_set_loading_avisa_quando_o_estado_muda(app_qt, store):
    jogo = _jogo()
    detalhes = _modelo(store, jogo)
    detalhes.mostrar("a")
    avisos = []
    jogo.atualizado.connect(lambda *_a: avisos.append(1))

    jogo.set_loading(1)
    assert len(avisos) == 1
    assert detalhes.carregando is True
    jogo.set_loading(1)  # 1 -> 2: o estado visível é o mesmo
    assert len(avisos) == 1
    jogo.set_loading(-1)
    assert len(avisos) == 1
    jogo.set_loading(-1)
    assert len(avisos) == 2
    assert detalhes.carregando is False


# -- as cópias animadas da página ----------------------------------------------------------------


@pytest.fixture(autouse=True)
def _ganchos_da_pagina_limpos(monkeypatch):
    """Os ganchos da página são globais: cada teste começa sem os de outro e o `monkeypatch` os devolve no fim."""
    from cartridges.utils import copias_animadas  # noqa: PLC0415

    monkeypatch.setattr(copias_animadas, "ao_terminar_da_pagina", None)
    monkeypatch.setattr(copias_animadas, "soltar_da_pagina", None)


def _com_copias(game_id="a", grade=True, grande=True):
    """Uma capa animada de verdade em `covers_dir`, com as cópias pedidas já geradas."""
    from cartridges.utils import copias_animadas  # noqa: PLC0415

    shared.covers_dir.mkdir(parents=True, exist_ok=True)
    capa = shared.covers_dir / f"{game_id}.webp"
    quadros = [Image.new("RGBA", (8, 12), (tom, 0, 0, 255)) for tom in (0, 90)]
    quadros[0].save(capa, "WEBP", save_all=True, append_images=quadros[1:], duration=[100, 100], loop=0, lossless=True)
    for pedida, tamanho in zip((grade, grande), copias_animadas.tamanhos(), strict=True):
        if pedida:
            assert copias_animadas.gerar(capa, copias_animadas.caminho_para(capa, tamanho), tamanho)
    return capa


def _tamanho_no_nome(indice):
    from cartridges.utils import copias_animadas  # noqa: PLC0415

    return "{}x{}".format(*copias_animadas.tamanhos()[indice])


def test_pagina_toca_a_copia_grande(app_qt, store):
    _com_copias()
    detalhes = _modelo(store, _jogo())
    detalhes.mostrar("a")
    assert _tamanho_no_nome(1) in detalhes.capaAnimada


def test_pagina_usa_a_da_grade_sem_a_grande(app_qt, store):
    _com_copias(grande=False)
    detalhes = _modelo(store, _jogo())
    detalhes.mostrar("a")
    assert _tamanho_no_nome(0) in detalhes.capaAnimada


def test_pagina_troca_para_a_copia_grande_quando_ela_fica_pronta(app_qt, store, monkeypatch):
    from cartridges.utils import copias_animadas  # noqa: PLC0415

    capa = _com_copias(grande=False)
    jogo = _jogo()
    detalhes = _modelo(store, jogo)
    detalhes.mostrar("a")
    assert _tamanho_no_nome(0) in detalhes.capaAnimada
    monkeypatch.setattr(jogo, "update", lambda: pytest.fail("a página deve ser avisada sem atualizar o jogo"))
    tamanho = copias_animadas.tamanhos()[1]
    assert copias_animadas.gerar(capa, copias_animadas.caminho_para(capa, tamanho), tamanho)

    copias_animadas.ao_terminar_da_pagina("a", "pronta")

    assert _tamanho_no_nome(1) in detalhes.capaAnimada


def test_copia_de_outro_jogo_nao_muda_a_pagina(app_qt, store):
    from cartridges.utils import copias_animadas  # noqa: PLC0415

    capa = _com_copias(grande=False)
    detalhes = _modelo(store, _jogo())
    detalhes.mostrar("a")
    antes = detalhes.capaAnimada
    tamanho = copias_animadas.tamanhos()[1]
    assert copias_animadas.gerar(capa, copias_animadas.caminho_para(capa, tamanho), tamanho)

    copias_animadas.ao_terminar_da_pagina("b", "pronta")

    assert detalhes.capaAnimada == antes


def test_mudar_o_tema_nao_le_o_historico(app_qt, store, monkeypatch):
    lidos = []
    original = modulo.session_log.load
    monkeypatch.setattr(modulo.session_log, "load", lambda game_id: (lidos.append(game_id), original(game_id))[1])
    detalhes = _modelo(store, _jogo(playtime=3600))

    detalhes.mostrar("a")
    assert lidos == ["a"]
    detalhes._tema_mudou()  # noqa: SLF001

    assert lidos == ["a"], "o tema não muda as sessões"
