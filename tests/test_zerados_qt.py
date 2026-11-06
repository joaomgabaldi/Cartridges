# test_zerados_qt.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Jogos Zerados: as regras do `Jogo` e da `Store`, o `SeletorDeZerados` e o `SeletorDeZerados.qml` no `Aplicativo.qml` inteiro.

Nada de verdade: a busca da Steam é sempre falsa (`zerado_manual.helper_da_steam` trocado) e a rede já é recusada pelo
`sem_rede`; o `FileDialog` e o navegador nunca abrem.
"""

import pytest
from PySide6.QtCore import QMetaObject, Qt
from PySide6.QtTest import QTest

from kyron import shared
from kyron.modelos import zerados_manuais as modulo
from kyron.modelos.zerados_manuais import MOTIVO, SeletorDeZerados, candidatos, descricao
from kyron.utils import zerado_manual
from kyron.utils.steam import SteamError, SteamGameNotFoundError
from tests.apoio_janela_atualizacao import Janela, achar, avaliar, esperar


def jogo(store, numero, **campos):
    """Um ``Jogo`` de verdade, já registrado na store (sem pipeline)."""
    from kyron.jogo import Jogo  # noqa: PLC0415

    novo = Jogo(
        {
            "source": "shortcuts",
            "game_id": f"shortcuts_z{numero}",
            "name": f"Jogo {numero}",
            "executable": "x",
            "added": 0,
            **campos,
        }
    )
    if store is not None:
        store.source_games.setdefault("shortcuts", {})[novo.game_id] = novo
        store.games_by_id[novo.game_id] = novo
    return novo


# -- O que é um zerado, a carga e a store ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("campos", "esperado"),
    [
        ({"removed": True, "status": "beaten"}, True),
        ({"removed": False, "status": "beaten"}, False),
        ({"removed": True, "status": "playing"}, False),
        ({"removed": True, "status": ""}, False),
        ({"removed": True, "status": "beaten", "blacklisted": True}, False),
    ],
)
def test_zerado_e_desinstalado_com_a_marca(campos, esperado):
    assert jogo(None, 1, **campos).zerado is esperado


def test_ficha_antiga_com_hidden_carrega_normal(store, write_record):
    from kyron.carga import carregar_jogos_do_disco  # noqa: PLC0415
    from kyron.jogo import PERSISTED_ATTRS  # noqa: PLC0415

    write_record("shortcuts_h", executable="x", hidden=True)
    carregar_jogos_do_disco(store)

    assert store.get("shortcuts_h") is not None
    assert "hidden" not in PERSISTED_ATTRS


def test_proximo_id_importado_pula_os_usados_e_os_estranhos(store, make_game):
    assert store.proximo_id_importado() == "imported_1"
    for game_id in ("imported_1", "imported_7", "imported_x"):
        store.add_game(make_game(game_id=game_id, source="imported"), {}, run_pipeline=False)
    assert store.proximo_id_importado() == "imported_8"


@pytest.fixture
def espiao(store):
    """Um manager que só escuta os dois sinais do `Jogo`."""
    from kyron.store.managers.manager import Manager  # noqa: PLC0415

    class Espiao(Manager):
        signals = {"atualizado", "salvar"}

        def main(self, game, additional_data):
            pass

    store.add_manager(Espiao())


def test_tumbas_carregadas_ficam_conectadas(store, espiao, make_game):
    zerado = make_game(game_id="shortcuts_z", removed=True, status="beaten")
    comum = make_game(game_id="shortcuts_c", removed=True)
    store.add_game(zerado, {"skip_save": True})
    store.add_game(comum, {"skip_save": True})

    assert {sinal for sinal, _ in zerado.signals} == {"atualizado", "salvar"}
    assert {sinal for sinal, _ in comum.signals} == {"atualizado", "salvar"}
    assert zerado.updates == 1, "o zerado vai para a tela na carga"
    assert comum.updates == 0, "o desinstalado comum continua fora de tela"


def test_reinstalar_um_zerado_mantem_a_ficha(store, make_game):
    tumba = make_game(
        game_id="shortcuts_z",
        removed=True,
        status="beaten",
        playtime=3600,
        executable="velho",
        shortcut_path=r"C:\velho.lnk",
        shortcut_mtime=100,
    )
    store.add_game(tumba, {"skip_save": True})

    novo = make_game(game_id="shortcuts_z", executable="novo", shortcut_path=r"C:\novo.lnk", shortcut_mtime=200)
    assert store.add_game(novo, {}) is None

    assert store.get("shortcuts_z") is tumba
    assert tumba.removed is True
    assert tumba.status == "beaten"
    assert tumba.playtime == 3600
    assert tumba.executable == "novo"
    assert tumba.shortcut_path == r"C:\novo.lnk"
    assert tumba.shortcut_mtime == 200
    assert tumba.saves == 1
    assert "shortcuts_z" in store.duplicate_game_ids


def test_o_mesmo_atalho_de_sempre_nao_mexe_no_zerado(store, make_game):
    tumba = make_game(game_id="shortcuts_z", removed=True, status="beaten", shortcut_mtime=100)
    store.add_game(tumba, {"skip_save": True})

    store.add_game(make_game(game_id="shortcuts_z", shortcut_mtime=100), {})

    assert store.get("shortcuts_z") is tumba
    assert tumba.saves == 0


def test_reinstalar_um_desinstalado_comum_segue_como_antes(store, make_game, app_dirs, flush_idle):
    tumba = make_game(game_id="shortcuts_c", removed=True, shortcut_mtime=100)
    store.add_game(tumba, {"skip_save": True})
    (app_dirs.games / "shortcuts_c.json").write_text("{}", encoding="utf-8")

    novo = make_game(game_id="shortcuts_c", shortcut_mtime=200)
    store.add_game(novo, {}, run_pipeline=False)

    assert store.get("shortcuts_c") is novo
    assert not (app_dirs.games / "shortcuts_c.json").exists()


def test_atalho_renomeado_de_zerado_e_seguido(store, make_game, tmp_path):
    antigo = tmp_path / "antigo.lnk"
    novo = tmp_path / "novo.lnk"
    novo.write_text("x")
    zerado = make_game(
        game_id="shortcuts_a", removed=True, status="beaten", shortcut_path=str(antigo), shortcut_mtime=100
    )
    store.add_game(zerado, {}, run_pipeline=False)
    chegando = make_game(game_id="shortcuts_a", shortcut_path=str(novo), shortcut_mtime=100)
    store.add_game(chegando, {}, run_pipeline=False)
    assert zerado.shortcut_path == str(novo)


def test_tumba_sem_executavel_carrega_e_jogo_vivo_nao(store, write_record):
    from kyron.carga import carregar_jogos_do_disco  # noqa: PLC0415

    write_record("imported_1", source="imported", executable="", removed=True, status="beaten")
    write_record("imported_2", source="imported", executable="")
    carregar_jogos_do_disco(store)

    assert store.get("imported_1") is not None
    assert store.get("imported_2") is None


def test_desmarcar_com_o_atalho_na_pasta_volta_a_biblioteca(tmp_path):
    atalho = tmp_path / "Jogo.lnk"
    atalho.write_bytes(b"")
    game = jogo(None, 20, removed=True, status="beaten", shortcut_path=str(atalho))

    game.definir_status("")

    assert game.status == ""
    assert game.removed is False


def test_desmarcar_sem_o_atalho_vira_desinstalado_comum(tmp_path):
    game = jogo(None, 21, removed=True, status="beaten", shortcut_path=str(tmp_path / "x.lnk"))

    game.definir_status("playing")

    assert game.removed is True
    assert game.zerado is False


def test_marcar_zerado_nao_ressuscita_ninguem(tmp_path):
    atalho = tmp_path / "Jogo.lnk"
    atalho.write_bytes(b"")
    game = jogo(None, 22, removed=True, shortcut_path=str(atalho))

    game.definir_status("beaten")

    assert game.zerado is True


def test_desmarcar_sem_executavel_nao_ressuscita(tmp_path):
    # A carga descarta uma ficha viva sem executável como malformada: de volta à biblioteca assim, o jogo sumiria
    # no próximo início.
    atalho = tmp_path / "Jogo.lnk"
    atalho.write_bytes(b"")
    game = jogo(None, 25, removed=True, status="beaten", executable="", shortcut_path=str(atalho))

    game.definir_status("")

    assert game.removed is True


def test_apagar_jogo_leva_so_as_sessoes_dele():
    from kyron.utils import session_log  # noqa: PLC0415

    session_log.record("a", 60, end=1_700_000_000)
    session_log.record("b", 120, end=1_700_000_100)
    session_log.record("a", 30, end=1_700_000_200)

    session_log.apagar_jogo("a")

    assert session_log.load() == [{"game_id": "b", "end": 1_700_000_100, "seconds": 120}]


def test_excluir_apaga_ficha_capa_sessoes_e_o_lugar_na_store(store, make_game, app_dirs, flush_idle):
    from kyron.store.store import _path_key  # noqa: PLC0415
    from kyron.utils import session_log  # noqa: PLC0415

    game = make_game(game_id="shortcuts_z", removed=True, status="beaten", shortcut_path=r"C:\Jogos\Z.lnk")
    store.add_game(game, {"skip_save": True})
    chave = (game.base_source, _path_key(game.shortcut_path))
    assert store._games_by_shortcut.get(chave) is game
    (app_dirs.games / "shortcuts_z.json").write_text("{}", encoding="utf-8")
    (app_dirs.covers / "shortcuts_z.tiff").write_bytes(b"capa")
    session_log.record("shortcuts_z", 60, end=1_700_000_000)

    store.excluir(game)

    assert store.get("shortcuts_z") is None
    assert game not in list(store)
    assert not (app_dirs.games / "shortcuts_z.json").exists()
    assert not (app_dirs.covers / "shortcuts_z.tiff").exists()
    assert session_log.load("shortcuts_z") == []
    assert chave not in store._games_by_shortcut


def test_zerado_nao_mostra_aviso_de_atualizacao(store, app_qt):  # noqa: ARG001
    from kyron.modelos.detalhes import DetalhesDoJogo  # noqa: PLC0415

    zerado = jogo(store, 32, removed=True, status="beaten", track_updates=True, update_available_ts=5)
    vivo = jogo(store, 33, track_updates=True, update_available_ts=5)
    detalhes = DetalhesDoJogo(store)

    assert detalhes.mostrar(zerado.game_id)
    assert detalhes.temAtualizacao is False
    assert detalhes.mostrar(vivo.game_id)
    assert detalhes.temAtualizacao is True


# -- O seletor: as regras ----------------------------------------------------------------------------------------


def resultado(appid, nome):
    return ({"id": appid, "name": nome}, None)


class _HelperFalso:
    """A busca da Steam: devolve o que o teste pôs, ou levanta."""

    def __init__(self, achados=(), erro=None):
        self.achados = list(achados)
        self.erro = erro
        self.pedidos = []

    def find_candidates(self, texto):
        self.pedidos.append(texto)
        if self.erro is not None:
            raise self.erro
        return self.achados


@pytest.fixture
def steam(monkeypatch):
    """O helper da Steam falso; o teste põe `steam.achados`/`steam.erro` antes de buscar."""
    falso = _HelperFalso()
    monkeypatch.setattr(zerado_manual, "helper_da_steam", lambda: falso)
    return falso


@pytest.fixture
def busca_sincrona(monkeypatch):
    """A thread da busca roda na hora, no lugar de nascer: o resultado ainda volta pela fila da principal."""

    class Inline:
        def __init__(self, target, args=(), daemon=None):  # noqa: ARG002
            self.target, self.args = target, args

        def start(self):
            self.target(*self.args)

    monkeypatch.setattr(modulo.threading, "Thread", Inline)


@pytest.fixture
def seletor(store, app_qt):  # noqa: ARG001
    modelo = SeletorDeZerados()
    modelo.abrir()
    return modelo


def titulos(seletor):
    return [(linha["titulo"], linha["subtitulo"], linha["ativa"]) for linha in seletor.linhas]


def test_candidatos_sao_os_desinstalados_sem_a_marca(store):
    b = jogo(store, 40, removed=True, name="b")
    a = jogo(store, 41, removed=True, name="A")
    jogo(store, 42, removed=True, status="beaten")
    jogo(store, 43)
    jogo(store, 44, removed=True, blacklisted=True)

    assert candidatos() == [a, b]


def test_descricao_separa_fichas_de_mesmo_nome(store):
    assert descricao(jogo(store, 45)) == "Nunca jogado"
    jogado = jogo(store, 46, playtime=7200, last_played=1_700_000_000)
    assert descricao(jogado).startswith("2 horas · Jogado por último: ")


def test_motivos_sao_os_da_main():
    assert MOTIVO == {"zerado": "Já está em Jogos Zerados", "biblioteca": "Já está na biblioteca"}


def test_abrir_lista_os_desinstalados_em_ordem_de_nome(store, seletor):
    jogo(store, 50, removed=True, name="b")
    jogo(store, 51, removed=True, name="A")
    seletor.abrir()

    assert seletor.aberto is True
    assert seletor.estado == "lista"
    assert [linha["chave"] for linha in seletor.linhas] == ["jogo:shortcuts_z51", "jogo:shortcuts_z50"]
    assert [linha["titulo"] for linha in seletor.linhas] == ["A", "b"]


def test_escolher_marca_zerado_e_tira_da_lista(store, seletor):
    game = jogo(store, 47, removed=True)
    seletor.abrir()

    seletor.escolher("jogo:shortcuts_z47")

    assert game.zerado is True
    assert seletor.linhas == []
    assert seletor.estado == "vazio"


@pytest.mark.parametrize("como", ["reinstalado", "trocado"])
def test_escolher_linha_velha_so_tira_da_lista(store, seletor, como):
    """O jogo mudou desde que a lista abriu: a linha sai, o jogo fica como está."""
    game = jogo(store, 48, removed=True)
    seletor.abrir()
    if como == "reinstalado":
        game.removed = False
    else:
        novo = jogo(store, 48, removed=True)
        assert store.get(game.game_id) is novo

    seletor.escolher("jogo:shortcuts_z48")

    assert game.status == ""
    assert seletor.linhas == []
    assert seletor.estado == "vazio"


def test_escolher_chave_fora_da_lista_e_ignorado(store, seletor):
    game = jogo(store, 52, removed=True)
    seletor.abrir()

    for chave in ("jogo:shortcuts_z999", "steam:570", "nome", "", "lixo"):
        seletor.escolher(chave)

    assert game.zerado is False
    assert store.get("imported_1") is None
    assert [linha["chave"] for linha in seletor.linhas] == ["jogo:shortcuts_z52"]


def test_escolher_linha_inativa_e_ignorado(store, seletor):
    jogo(store, 53, name="Hades", removed=True, status="beaten")
    seletor._mostrar_resultados("hades", [resultado(1145360, "Hades")], "", seletor._geracao)
    antes = list(seletor.linhas)

    seletor.escolher("steam:1145360")
    seletor.escolher("nome")

    assert store.get("imported_1") is None
    assert seletor.linhas == antes
    assert all(linha["ativa"] is False for linha in seletor.linhas)


def test_b27_seletor_vazio_nao_se_contradiz(app_qt, store):  # noqa: ARG001
    """Sem desinstalados o aviso não manda adicionar de uma lista que não existe: manda buscar na Steam."""
    j = Janela()
    try:
        j.zerados_manuais.abrir()
        assert j.zerados_manuais.estado == "vazio"
        vazio = j.achar("zeradosVazio")
        assert esperar(lambda: vazio.property("visible") is True)
        assert vazio.property("titulo") == "Nenhum jogo disponível"
        assert vazio.property("descricao") == "Busque um jogo na Steam para adicioná-lo."
    finally:
        j.fechar()


def test_buscar_sem_texto_ou_fechado_nao_faz_nada(store, steam, busca_sincrona, flush_idle, app_qt):  # noqa: ARG001
    modelo = SeletorDeZerados()
    modelo.buscar("hades")  # fechado
    modelo.abrir()
    modelo.buscar("   ")
    flush_idle()
    assert steam.pedidos == []
    assert modelo.estado == "vazio"


def test_buscar_mostra_carregando_e_depois_os_resultados(store, seletor, steam, flush_idle):
    steam.achados = [resultado(1145360, "Hades")]

    seletor.buscar("  hades ")  # a thread de verdade
    assert seletor.estado in ("carregando", "lista")
    assert esperar(lambda: seletor.estado == "lista" and bool(seletor.linhas))

    assert steam.pedidos == ["hades"]
    assert titulos(seletor) == [
        ("Hades", "ID na Steam: 1145360", True),
        ("Adicionar “hades” sem dados da Steam", "", True),
    ]


def test_steam_sem_resultado_avisa(store, seletor, steam, busca_sincrona, flush_idle):
    steam.erro = SteamGameNotFoundError()

    seletor.buscar("chrono")
    assert seletor.estado == "carregando"
    flush_idle()

    assert seletor.aviso == "Nenhum jogo encontrado na Steam."
    assert [t for t, _s, _a in titulos(seletor)] == ["Adicionar “chrono” sem dados da Steam"]


@pytest.mark.parametrize("erro", [SteamError("x"), ConnectionError("rede"), RuntimeError("inesperado")])
def test_steam_que_falha_avisa_e_nao_trava_o_carregando(store, seletor, steam, busca_sincrona, flush_idle, erro):
    steam.erro = erro

    seletor.buscar("chrono")
    flush_idle()

    assert seletor.aviso == "Não foi possível concluir a busca na Steam."
    assert seletor.estado == "lista"


def test_resultado_depois_de_fechar_e_descartado(store, seletor, steam, busca_sincrona, flush_idle):
    steam.achados = [resultado(1, "X")]

    seletor.buscar("x")
    seletor.fechar()
    flush_idle()

    assert seletor.aberto is False
    assert seletor.linhas == []
    assert seletor.estado == "vazio"


def test_resultado_de_busca_velha_e_descartado(store, seletor, steam, busca_sincrona, flush_idle):
    jogo(store, 54, removed=True, name="Antigo")
    steam.achados = [resultado(1, "X")]

    seletor.buscar("x")
    seletor.mudouBusca("")  # apagou o campo antes da resposta
    flush_idle()

    assert [t for t, _s, _a in titulos(seletor)] == ["Antigo"]


# -- O seletor na janela --------------------------------------------------------------------------------------------


@pytest.fixture
def janela(app_qt, store, steam):  # noqa: ARG001
    j = Janela()
    yield j
    j.fechar()


def _clique(janela, nome):
    QMetaObject.invokeMethod(janela.achar(nome), "click", Qt.ConnectionType.DirectConnection)


def _fechar_do_cabecalho(janela):
    """O X do cabeçalho do seletor (à direita, depois do que houver no cabeçalho)."""
    return achar(janela.achar("seletorDeZerados"), "fecharDoCabecalho")


def _digitar(janela, texto):
    for letra in texto:
        QTest.keyClick(janela.janela, letra)


def _ir_para_zerados(janela):
    _clique(janela, "botaoZerados")
    assert esperar(lambda: janela.janela.property("paginaAtual") == "zerados")


def _abrir(janela):
    _ir_para_zerados(janela)
    _clique(janela, "botaoAdicionarZerado")
    dialogo = janela.achar("seletorDeZerados")
    assert esperar(lambda: dialogo.property("visible") is True)
    return dialogo


def test_botao_mais_so_em_jogos_zerados(janela):
    botao = janela.achar("botaoAdicionarZerado")
    assert botao.property("visible") is False
    assert botao.property("dica") == "Adicionar a Jogos Zerados"
    assert avaliar(janela.janela, "botoesDaBarra.indexOf(botaoAdicionarZerado) >= 0") is True

    _ir_para_zerados(janela)
    assert botao.property("visible") is True
    assert janela.achar("botaoAdicionar").property("visible") is False
    assert botao.property("glifo") == janela.achar("botaoAdicionar").property("glifo")  # o mesmo glifo do "+"

    _clique(janela, "botaoVoltar")
    assert esperar(lambda: janela.janela.property("paginaAtual") == "todos")
    assert botao.property("visible") is False


def test_botao_mais_abre_o_seletor(janela, store):
    jogo(store, 60, removed=True, name="Antigo")
    dialogo = _abrir(janela)

    assert janela.zerados_manuais.aberto is True
    assert janela.achar("zeradosTitulo").property("text") == "Adicionar a Jogos Zerados"
    assert janela.achar("zeradosCampo").property("placeholderText") == "Buscar na Steam"
    assert janela.achar("zeradosLinha0Titulo").property("text") == "Antigo"
    assert dialogo.property("visible") is True


def test_busca_de_zerado_com_tags_em_texto_puro(janela, steam):
    steam.achados = [resultado(7, "Tom & <b>Jerry</b>")]
    _abrir(janela)
    campo = janela.achar("zeradosCampo")
    assert esperar(lambda: campo.property("activeFocus") is True)

    _digitar(janela, "Tom & <b>Jerry</b>")
    QTest.keyClick(janela.janela, Qt.Key.Key_Return)
    assert esperar(lambda: janela.zerados_manuais.estado == "lista" and len(janela.zerados_manuais.linhas) == 2)

    titulo = janela.achar("zeradosLinha0Titulo")
    assert esperar(lambda: titulo.property("text") == "Tom & <b>Jerry</b>")
    assert avaliar(titulo, "textFormat === Text.PlainText") is True
    assert janela.achar("zeradosLinha0Subtitulo").property("text") == "ID na Steam: 7"
    nome = janela.achar("zeradosLinha1Titulo")
    assert nome.property("text") == "Adicionar “Tom & <b>Jerry</b>” sem dados da Steam"
    assert avaliar(nome, "textFormat === Text.PlainText") is True
    assert avaliar(janela.achar("zeradosAviso"), "textFormat === Text.PlainText") is True


def test_aviso_da_busca_aparece_no_seletor(janela, steam):
    steam.erro = SteamGameNotFoundError()
    _abrir(janela)

    janela.zerados_manuais.buscar("chrono")

    aviso = janela.achar("zeradosAviso")
    assert esperar(lambda: aviso.property("visible") is True)
    assert aviso.property("text") == "Nenhum jogo encontrado na Steam."


def test_linhas_inativas_ficam_apagadas_e_nao_agem(janela, store, steam):
    jogo(store, 61, name="Hades", removed=True, status="beaten")
    steam.achados = [resultado(1145360, "Hades")]
    _abrir(janela)

    janela.zerados_manuais.buscar("hades")
    assert esperar(lambda: janela.zerados_manuais.estado == "lista" and len(janela.zerados_manuais.linhas) == 2)

    linha = janela.achar("zeradosLinha0")
    assert esperar(lambda: janela.achar("zeradosLinha0Subtitulo").property("text") == "Já está em Jogos Zerados")
    assert linha.property("opacity") < 1
    _clique(janela, "zeradosLinha0Botao")
    assert store.get("imported_1") is None


def test_a_linha_que_ja_esta_fica_fora_do_foco(janela, store, steam):
    """A linha "já está em Jogos Zerados" é insensível: as setas passam por ela sem parar."""
    jogo(store, 61, name="Hades", removed=True, status="beaten")
    steam.achados = [resultado(1145360, "Hades"), resultado(504230, "Celeste")]
    _abrir(janela)
    janela.zerados_manuais.buscar("hades")
    assert esperar(lambda: janela.zerados_manuais.estado == "lista" and len(janela.zerados_manuais.linhas) == 3)
    assert janela.achar("zeradosLinha0Botao").property("enabled") is False
    assert janela.achar("zeradosLinha1Botao").property("enabled") is True
    janela.achar("zeradosCampo").forceActiveFocus(Qt.FocusReason.TabFocusReason)
    QTest.keyClick(janela.janela, Qt.Key.Key_Down)
    assert esperar(lambda: janela.achar("zeradosLinha1Botao").property("activeFocus") is True)
    assert janela.achar("zeradosLinha0Botao").property("activeFocus") is False


def test_clicar_num_desinstalado_marca_e_tira_da_lista(janela, store):
    game = jogo(store, 62, removed=True, name="Antigo")
    _abrir(janela)

    _clique(janela, "zeradosLinha0Botao")

    assert game.zerado is True
    assert esperar(lambda: janela.achar("zeradosVazio").property("visible") is True)
    assert janela.zerados_manuais.aberto is True  # o diálogo fica aberto


def test_linhas_alcancaveis_por_teclado(janela, store):
    primeiro = jogo(store, 63, removed=True, name="A")
    segundo = jogo(store, 64, removed=True, name="B")
    _abrir(janela)
    campo = janela.achar("zeradosCampo")
    assert esperar(lambda: campo.property("activeFocus") is True)

    QTest.keyClick(janela.janela, Qt.Key.Key_Down)
    assert esperar(lambda: janela.achar("zeradosLinha0").property("activeFocus") is True)
    QTest.keyClick(janela.janela, Qt.Key.Key_Down)
    assert esperar(lambda: janela.achar("zeradosLinha1").property("activeFocus") is True)
    QTest.keyClick(janela.janela, Qt.Key.Key_Up)
    assert esperar(lambda: janela.achar("zeradosLinha0").property("activeFocus") is True)
    QTest.keyClick(janela.janela, Qt.Key.Key_Up)
    assert esperar(lambda: campo.property("activeFocus") is True)

    QTest.keyClick(janela.janela, Qt.Key.Key_Down)
    assert esperar(lambda: janela.achar("zeradosLinha0").property("activeFocus") is True)
    QTest.keyClick(janela.janela, Qt.Key.Key_Return)
    assert esperar(lambda: primeiro.zerado is True)
    assert segundo.zerado is False


def test_esc_fecha_e_o_foco_volta(janela, store):
    jogo(store, 65, removed=True, name="Antigo")
    _ir_para_zerados(janela)
    grade = janela.achar("gradeDeZerados")
    grade.forceActiveFocus(Qt.FocusReason.TabFocusReason)
    assert esperar(lambda: grade.property("activeFocus") is True)

    _clique(janela, "botaoAdicionarZerado")
    dialogo = janela.achar("seletorDeZerados")
    assert esperar(lambda: dialogo.property("visible") is True)
    assert esperar(lambda: janela.achar("zeradosCampo").property("activeFocus") is True)  # foco inicial por callLater

    QTest.keyClick(janela.janela, Qt.Key.Key_Escape)
    assert esperar(lambda: dialogo.property("visible") is False)
    assert janela.zerados_manuais.aberto is False
    assert esperar(lambda: grade.property("activeFocus") is True)  # o fundo desabilitado tirou o foco: volta à grade


def test_tab_circula_dentro_do_seletor(janela, store):
    jogo(store, 66, removed=True, name="A")
    _abrir(janela)
    fechar = _fechar_do_cabecalho(janela)
    campo = janela.achar("zeradosCampo")
    linha = janela.achar("zeradosLinha0")
    assert esperar(lambda: campo.property("activeFocus") is True)

    for esperado in (linha, fechar, campo):
        QTest.keyClick(janela.janela, Qt.Key.Key_Tab)
        assert esperar(lambda esperado=esperado: esperado.property("activeFocus") is True)
    QTest.keyClick(janela.janela, Qt.Key.Key_Backtab)
    assert esperar(lambda: fechar.property("activeFocus") is True)


def test_fundo_fica_apagado_com_o_seletor(janela):
    _abrir(janela)
    for nome in ("alvoDeSoltar", "botaoMenu", "botaoVoltar", "botaoAdicionarZerado", "pilha"):
        assert janela.achar(nome).property("enabled") is False, nome
    assert janela.janela.property("popupAberto") is True
    janela.zerados_manuais.fechar()
    assert esperar(lambda: janela.achar("botaoVoltar").property("enabled") is True)
    assert janela.achar("botaoAdicionarZerado").property("enabled") is True


def test_o_botao_fechar_fecha_o_seletor(janela):
    dialogo = _abrir(janela)
    x = _fechar_do_cabecalho(janela)
    x.forceActiveFocus(Qt.FocusReason.TabFocusReason)
    QTest.keyClick(janela.janela, Qt.Key.Key_Return)
    assert esperar(lambda: dialogo.property("visible") is False)
    assert janela.zerados_manuais.aberto is False


def test_reabrir_comeca_com_o_campo_vazio(janela, store):
    jogo(store, 67, removed=True, name="Antigo")
    dialogo = _abrir(janela)
    campo = janela.achar("zeradosCampo")
    _digitar(janela, "algo")
    assert esperar(lambda: campo.property("text") == "algo")

    janela.zerados_manuais.fechar()
    assert esperar(lambda: dialogo.property("visible") is False)
    janela.zerados_manuais.abrir()
    assert esperar(lambda: dialogo.property("visible") is True)

    assert campo.property("text") == ""
    assert janela.achar("zeradosLinha0Titulo").property("text") == "Antigo"


def test_sem_seletor_no_contexto_nao_ha_botao_nem_dialogo(app_qt):  # noqa: ARG001
    j = Janela(com_zerados=False)
    try:
        _ir_para_zerados(j)
        assert j.achar("botaoAdicionarZerado").property("visible") is False
        assert j.janela.property("popupAberto") is False
        assert j.achar("alvoDeSoltar").property("enabled") is True
    finally:
        j.fechar()
