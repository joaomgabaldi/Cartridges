# test_modelo_biblioteca.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O modelo da grade da biblioteca e o manager que o alimenta."""

import threading
import time

from PySide6.QtCore import QEventLoop, QTimer

from cartridges import shared
from cartridges.jogo import Jogo
from cartridges.configuracoes import Configuracoes
from cartridges.modelos import biblioteca as modulo
from cartridges.modelos.biblioteca import FiltroDaPagina, FiltrosDaBiblioteca, ModeloDaBiblioteca
from cartridges.store.managers.exibicao_manager import ExibicaoManager
from cartridges.utils import thread_principal
from cartridges.utils.thread_principal import eh_thread_principal


def _jogo(game_id, nome, **extra):
    return Jogo({"game_id": game_id, "source": "imported", "name": nome, **extra})


def _nomes(modelo):
    return [modelo.data(modelo.index(i), ModeloDaBiblioteca.Papel.Nome) for i in range(modelo.rowCount())]


def _pagina(modelo, pagina="biblioteca"):
    """O proxy da página, com filtros novos, no modo A-Z."""
    filtros = FiltrosDaBiblioteca(modelo)
    filtros.modo = "a-z"
    return FiltroDaPagina(modelo, filtros, pagina), filtros


def _nomes_de(proxy):
    return [proxy.data(proxy.index(i, 0), ModeloDaBiblioteca.Papel.Nome) for i in range(proxy.rowCount())]


def _rodar_ate(condicao, limite=5.0):
    fim = time.monotonic() + limite
    while not condicao() and time.monotonic() < fim:
        laco = QEventLoop()
        QTimer.singleShot(10, laco.quit)
        laco.exec()
    return condicao()


def test_entram_so_os_visiveis(app_qt):
    modelo = ModeloDaBiblioteca()
    modelo.atualizar(_jogo("a", "A"))
    modelo.atualizar(_jogo("b", "B", removed=True))
    modelo.atualizar(_jogo("c", "C", blacklisted=True))
    assert _nomes(modelo) == ["A"]


def test_ordem_por_nome_sem_caixa(app_qt):
    modelo = ModeloDaBiblioteca()
    pagina, _ = _pagina(modelo)
    for i, nome in enumerate(["zelda", "Banjo", "alpha", "Celeste"]):
        modelo.atualizar(_jogo(str(i), nome))
    assert _nomes_de(pagina) == ["alpha", "Banjo", "Celeste", "zelda"]


def test_atualizar_muda_o_papel_nome(app_qt):
    modelo = ModeloDaBiblioteca()
    jogo = _jogo("a", "Alfa")
    modelo.atualizar(jogo)
    mudancas = []
    modelo.dataChanged.connect(lambda de, ate, papeis: mudancas.append((de.row(), tuple(papeis))))
    jogo.name = "Alfa 2"
    modelo.atualizar(jogo)
    assert _nomes(modelo) == ["Alfa 2"]
    assert mudancas and mudancas[0][0] == 0


def test_renomear_reordena(app_qt):
    modelo = ModeloDaBiblioteca()
    pagina, _ = _pagina(modelo)
    a, b = _jogo("a", "A"), _jogo("b", "B")
    modelo.atualizar(a)
    modelo.atualizar(b)
    a.name = "Z"
    modelo.atualizar(a)
    assert _nomes_de(pagina) == ["B", "Z"]


def test_jogo_removido_sai_do_modelo(app_qt):
    modelo = ModeloDaBiblioteca()
    jogo = _jogo("a", "A")
    modelo.atualizar(jogo)
    jogo.removed = True
    modelo.atualizar(jogo)
    assert modelo.rowCount() == 0


def test_capa_vazia_sem_arquivo(app_qt):
    modelo = ModeloDaBiblioteca()
    modelo.atualizar(_jogo("a", "A"))
    assert modelo.data(modelo.index(0), ModeloDaBiblioteca.Papel.Capa) == ""


def test_capa_e_url_de_arquivo(app_qt):
    (shared.covers_dir / "a.tiff").write_bytes(b"x")
    modelo = ModeloDaBiblioteca()
    modelo.atualizar(_jogo("a", "A"))
    assert modelo.data(modelo.index(0), ModeloDaBiblioteca.Papel.Capa).startswith("file:///")


def test_iniciar_lanca_o_jogo(app_qt, monkeypatch):
    modelo = ModeloDaBiblioteca()
    jogo = _jogo("a", "A")
    lancados = []
    monkeypatch.setattr(jogo, "launch", lambda *a: lancados.append(jogo) or True)
    modelo.atualizar(jogo)
    modelo.iniciar("a")
    modelo.iniciar("inexistente")
    assert lancados == [jogo]


def test_atualizacao_vinda_de_thread_chega_na_principal(app_qt, store):
    thread_principal.na_thread_principal(lambda: None)  # garante a ponte
    modelo = ModeloDaBiblioteca()
    vistos = []
    original = modelo.atualizar
    modelo.atualizar = lambda jogo: (vistos.append(eh_thread_principal()), original(jogo))
    store.add_manager(ExibicaoManager(modelo))
    jogo = _jogo("a", "Alfa")
    store.add_game(jogo, {}, run_pipeline=False)
    jogo.name = "Beta"
    thread = threading.Thread(target=jogo.save)
    thread.start()
    thread.join()
    assert vistos == []
    assert _rodar_ate(lambda: vistos)
    assert vistos == [True]
    assert _nomes(modelo) == ["Beta"]


def test_grade_carrega_no_qml(app_qt):
    from pathlib import Path  # noqa: PLC0415

    from PySide6.QtCore import QUrl  # noqa: PLC0415
    from PySide6.QtQml import QQmlComponent, QQmlEngine  # noqa: PLC0415

    qml = Path(shared.__file__).parent / "qml"
    motor = QQmlEngine()
    motor.addImportPath(str(qml.parent))
    modelo = ModeloDaBiblioteca()
    modelo.atualizar(_jogo("a", "A"))
    componente = QQmlComponent(motor, QUrl.fromLocalFile(str(qml / "Grade.qml")))
    objeto = componente.createWithInitialProperties({"biblioteca": modelo})
    assert objeto is not None, componente.errorString()


def test_jogo_excluido_sai_da_grade(app_qt, store):
    modelo = ModeloDaBiblioteca()
    modelo.ligar_store(store)
    modelo.atualizar(_jogo("a", "A"))
    modelo.atualizar(_jogo("b", "B"))
    vistos = []
    modelo.rowsRemoved.connect(lambda *_: vistos.append(eh_thread_principal()))
    thread = threading.Thread(target=store.jogo_excluido.emit, args=("a",))
    thread.start()
    thread.join()
    assert _nomes(modelo) == ["A", "B"]  # enfileirado, não síncrono
    assert _rodar_ate(lambda: vistos)
    assert vistos == [True]
    assert _nomes(modelo) == ["B"]


def test_troca_de_id_tira_o_antigo(app_qt, store):
    modelo = ModeloDaBiblioteca()
    modelo.ligar_store(store)
    modelo.atualizar(_jogo("a", "A"))
    store.capa_trocou_de_id.emit("a", "b")
    assert _rodar_ate(lambda: modelo.rowCount() == 0)
    assert modelo.rowCount() == 0
    assert "a" not in modelo._jogos  # noqa: SLF001


# --- ordem, filtros e busca (tarefa 2 do plano 2) ---


def test_zerado_removido_so_na_pagina_de_zerados(app_qt):
    modelo = ModeloDaBiblioteca()
    biblioteca, _ = _pagina(modelo)
    zerados, _ = _pagina(modelo, "zerados")
    modelo.atualizar(_jogo("a", "Viva"))
    modelo.atualizar(_jogo("b", "Zerado", removed=True, status="beaten"))
    modelo.atualizar(_jogo("c", "Desinstalado", removed=True))
    assert modelo.rowCount() == 2  # o desinstalado comum não entra
    assert _nomes_de(biblioteca) == ["Viva"]
    assert _nomes_de(zerados) == ["Zerado"]


def test_pendente_de_restauracao_fica_fora(app_qt, monkeypatch):
    monkeypatch.setattr(modulo, "_pendente", lambda game_id: game_id == "b")
    modelo = ModeloDaBiblioteca()
    modelo.atualizar(_jogo("a", "A"))
    modelo.atualizar(_jogo("b", "B"))
    assert _nomes(modelo) == ["A"]


def test_trocar_modo_reordena_e_grava_sort_mode(app_qt):
    modelo = ModeloDaBiblioteca()
    pagina, filtros = _pagina(modelo)
    modelo.atualizar(_jogo("a", "A", last_played=1))
    modelo.atualizar(_jogo("b", "B", last_played=9))
    assert _nomes_de(pagina) == ["A", "B"]
    filtros.modo = "last_played"
    assert _nomes_de(pagina) == ["B", "A"]
    assert shared.state_schema.get_string("sort-mode") == "last_played"
    filtros.modo = "z-a"
    assert _nomes_de(pagina) == ["B", "A"]
    filtros.modo = "a-z"
    assert shared.state_schema.get_string("sort-mode") == "a-z"
    assert _nomes_de(pagina) == ["A", "B"]


def test_modo_inicial_vem_do_registro(app_qt):
    shared.state_schema.set_string("sort-mode", "playtime")
    assert FiltrosDaBiblioteca(ModeloDaBiblioteca()).modo == "playtime"


def test_modo_lido_uma_vez(app_qt, monkeypatch):
    modelo = ModeloDaBiblioteca()
    for i in range(200):
        modelo.atualizar(_jogo(str(i), f"Jogo {i}", last_played=i))
    leituras = []
    original = Configuracoes._ler
    monkeypatch.setattr(Configuracoes, "_ler", lambda self, *a: leituras.append(a) or original(self, *a))
    filtros = FiltrosDaBiblioteca(modelo)
    pagina = FiltroDaPagina(modelo, filtros, "biblioteca")
    pagina.sort(0)
    assert pagina.rowCount() == 200
    assert len(leituras) <= 1


def test_vazia_e_sem_resultados(app_qt):
    modelo = ModeloDaBiblioteca()
    pagina, filtros = _pagina(modelo)
    avisos = []
    pagina.vaziaChanged.connect(lambda: avisos.append("vazia"))
    pagina.semResultadosChanged.connect(lambda: avisos.append("sem"))
    assert pagina.vazia and not pagina.semResultados
    modelo.atualizar(_jogo("a", "Alfa", genre="RPG"))
    assert not pagina.vazia and not pagina.semResultados
    pagina.busca = "xyz"
    assert not pagina.vazia and pagina.semResultados
    pagina.busca = ""
    assert not pagina.semResultados
    filtros.genero = "Ação"
    assert not pagina.vazia and pagina.semResultados
    assert avisos
    modelo.retirar("a")
    assert pagina.vazia and not pagina.semResultados
    assert pagina.primeiro() == ""


def test_primeiro_devolve_o_primeiro_da_ordem(app_qt):
    modelo = ModeloDaBiblioteca()
    pagina, _ = _pagina(modelo)
    modelo.atualizar(_jogo("b", "B"))
    modelo.atualizar(_jogo("a", "A"))
    assert pagina.primeiro() == "a"


def test_busca_nao_vale_em_zerados(app_qt):
    modelo = ModeloDaBiblioteca()
    biblioteca, _ = _pagina(modelo)
    zerados, _ = _pagina(modelo, "zerados")
    modelo.atualizar(_jogo("a", "Zelda"))
    modelo.atualizar(_jogo("b", "Halo", removed=True, status="beaten"))
    biblioteca.busca = "zelda"
    zerados.busca = "zelda"
    assert _nomes_de(biblioteca) == ["Zelda"]
    assert _nomes_de(zerados) == ["Halo"]


def test_filtros_valem_nas_duas_paginas(app_qt):
    modelo = ModeloDaBiblioteca()
    filtros = FiltrosDaBiblioteca(modelo)
    biblioteca = FiltroDaPagina(modelo, filtros, "biblioteca")
    zerados = FiltroDaPagina(modelo, filtros, "zerados")
    modelo.atualizar(_jogo("a", "A", genre="RPG"))
    modelo.atualizar(_jogo("b", "B", genre="Ação"))
    modelo.atualizar(_jogo("c", "C", genre="RPG", removed=True, status="beaten"))
    modelo.atualizar(_jogo("d", "D", genre="Ação", removed=True, status="beaten"))
    filtros.genero = "RPG"
    assert _nomes_de(biblioteca) == ["A"]
    assert _nomes_de(zerados) == ["C"]


def test_filtro_que_sumiu_volta_a_todos(app_qt):
    modelo = ModeloDaBiblioteca()
    filtros = FiltrosDaBiblioteca(modelo)
    modelo.atualizar(_jogo("a", "A", genre="RPG", release_date="2020"))
    filtros.recalcularOpcoes()
    assert filtros.generos == ["RPG"] and filtros.anos == ["2020"]
    filtros.genero, filtros.ano, filtros.status = "RPG", "2020", "beaten"
    modelo.retirar("a")
    filtros.recalcularOpcoes()
    assert (filtros.genero, filtros.ano) == ("", "")
    assert filtros.status == "beaten"  # lista fixa: não some
    filtros.limpar()
    assert filtros.status == ""


def test_opcoes_incluem_zerados(app_qt):
    modelo = ModeloDaBiblioteca()
    filtros = FiltrosDaBiblioteca(modelo)
    modelo.atualizar(_jogo("a", "A", removed=True, status="beaten", genre="Ação"))
    filtros.recalcularOpcoes()
    assert filtros.generos == ["Ação"]


def test_status_tem_rotulo_e_valor(app_qt):
    assert [s["valor"] for s in FiltrosDaBiblioteca.STATUS] == ["backlog", "playing", "beaten", "dropped"]
    assert FiltrosDaBiblioteca.STATUS[2]["rotulo"] == "Zerado"


def test_capa_muda_a_url_quando_o_arquivo_muda(app_qt):
    import os  # noqa: PLC0415

    arquivo = shared.covers_dir / "a.tiff"
    arquivo.write_bytes(b"x")
    modelo = ModeloDaBiblioteca()
    jogo = _jogo("a", "A")
    modelo.atualizar(jogo)
    antes = modelo.data(modelo.index(0), ModeloDaBiblioteca.Papel.Capa)
    assert "?v=" in antes
    os.utime(arquivo, ns=(1_000_000_000, 1_000_000_000))
    modelo.atualizar(jogo)
    depois = modelo.data(modelo.index(0), ModeloDaBiblioteca.Papel.Capa)
    assert depois != antes and depois.startswith("file:///")


def test_papel_carregando(app_qt):
    modelo = ModeloDaBiblioteca()
    jogo = _jogo("a", "A")
    modelo.atualizar(jogo)
    assert modelo.data(modelo.index(0), ModeloDaBiblioteca.Papel.Carregando) is False
    jogo.loading = 1
    modelo.atualizar(jogo)
    assert modelo.data(modelo.index(0), ModeloDaBiblioteca.Papel.Carregando) is True
    assert modelo.linha(0).jogo_id == "a" and len(modelo.linhas()) == 1
