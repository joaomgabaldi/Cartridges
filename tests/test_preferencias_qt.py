"""O modelo das Preferências: travas, regras dos textos, abrir/fechar e a busca."""

import types

from PySide6.QtCore import Qt

import pytest

from cartridges import shared
from cartridges.modelos.preferencias import PAGINAS, Preferencias
from cartridges.utils import window_geometry
from cartridges.utils.window_geometry import Monitor
from tests.apoio_capas import _ManagerDeCapas
from tests.apoio_preferencias_qt import PRINCIPAL, SEGUNDO

_CRIAR_PLACA_REAL = window_geometry._criar_placa  # antes da guarda `sem_placa_de_verdade`

TERCEIRO = Monitor(r"\\.\DISPLAY3", -1920, 0, 1920, 1080, False, 3, r"\\?\DISPLAY#C#3")


@pytest.fixture
def monitores(monkeypatch):
    """Os monitores que a máquina "tem": a lista que o teste mudar."""
    lista = [PRINCIPAL, SEGUNDO, TERCEIRO]
    monkeypatch.setattr(window_geometry, "monitors", lambda: lista)
    return lista


@pytest.fixture
def p(app_qt, monitores):  # noqa: ARG001
    modelo = Preferencias(None, lambda: True)
    assert modelo.abrir()
    yield modelo
    modelo.fechar()


def test_contar_horas_trava_minimizar_ligado(p):
    shared.schema.set_boolean("minimize-after-launch", False)
    p.definir("playtime-tracking", True)
    assert shared.schema.get_boolean("minimize-after-launch")
    assert p.valores["minimize-after-launch"] is True
    assert p.estado["minimizarTravado"]


def test_desligar_contar_horas_destrava_sem_mudar_minimizar(p):
    p.definir("playtime-tracking", True)
    p.definir("playtime-tracking", False)
    assert not p.estado["minimizarTravado"]
    assert shared.schema.get_boolean("minimize-after-launch")


def test_chave_do_sgdb_vazia_desliga_o_sgdb(p):
    p.definirTexto("sgdb-key", "abc")
    p.definir("sgdb", True)
    assert p.estado["sgdbAtivo"]
    p.definirTexto("sgdb-key", "")
    assert not shared.schema.get_boolean("sgdb")
    assert not p.estado["sgdbAtivo"]


def test_chave_do_sgdb_e_gravada_como_veio(p):
    # A chave do SteamGridDB não é aparada (só a do wallhaven e a da Steam).
    p.definirTexto("sgdb-key", "  abc ")
    assert shared.schema.get_string("sgdb-key") == "  abc "


def test_chave_do_sgdb_so_com_espacos_vale_como_preenchida(p):
    # `bool("   ")` é verdadeiro, então o SteamGridDB não desliga.
    p.definirTexto("sgdb-key", "abc")
    p.definir("sgdb", True)
    p.definirTexto("sgdb-key", "   ")
    assert shared.schema.get_string("sgdb-key") == "   "
    assert shared.schema.get_boolean("sgdb")


def test_chave_do_wallhaven_sem_espacos_nas_pontas(p):
    p.definirTexto("wallhaven-key", "  xyz \n")
    assert shared.schema.get_string("wallhaven-key") == "xyz"
    p.definirTexto("conquistas-chave-steam", " k ")
    assert shared.schema.get_string("conquistas-chave-steam") == "k"


def test_tempo_de_espera_limitado_e_inteiro(p):
    p.definir("process-tracking-grace", 200.7)
    assert shared.schema.get_int("process-tracking-grace") == 120
    p.definir("process-tracking-grace", -5)
    assert shared.schema.get_int("process-tracking-grace") == 0
    p.definir("process-tracking-grace", 30.9)
    assert shared.schema.get_int("process-tracking-grace") == 30


def test_chave_fora_da_lista_nao_e_gravada(p, caplog):
    antes = {c: shared.schema.get_value(c) for c in shared.schema.list_keys()}
    with caplog.at_level("WARNING"):
        p.definir("assistente-concluido", True)
        p.definir("fita-estado-anterior", "x")
        p.definir("news-check-interval", 3)
    assert {c: shared.schema.get_value(c) for c in shared.schema.list_keys()} == antes
    avisos = [r for r in caplog.records if r.name == "cartridges.modelos.preferencias"]
    assert [r.levelname for r in avisos] == ["WARNING"] * 3


def test_valores_seguem_o_schema(p):
    avisos = []
    p.alterado.connect(lambda: avisos.append(1))
    shared.schema.set_boolean("auto-import", True)
    assert avisos
    assert p.valores["auto-import"] is True


def test_abrir_duas_vezes_nao_reabre(p):
    assert not p.abrir("metadados")
    assert p.pagina == "geral"


def test_abrir_durante_a_importacao_nao_abre(app_qt, monkeypatch):  # noqa: ARG001
    monkeypatch.setattr(shared, "aplicativo", types.SimpleNamespace(importando=True), raising=False)
    modelo = Preferencias(None, lambda: True)
    assert not modelo.abrir()
    assert not modelo.aberto


def test_pagina_desconhecida_abre_o_geral(app_qt):  # noqa: ARG001
    modelo = Preferencias(None, lambda: True)
    assert modelo.abrir("nao-existe")
    assert modelo.pagina == "geral"
    modelo.fechar()
    assert modelo.abrir("metadados")
    assert modelo.pagina == "metadados"
    modelo.fechar()


@pytest.mark.parametrize("secao", PAGINAS)
def test_abrir_cada_secao(app_qt, secao):  # noqa: ARG001
    modelo = Preferencias(None, lambda: True)
    assert modelo.abrir(secao) and modelo.pagina == secao
    modelo.fechar()


def test_id_antigo_ou_desconhecido_cai_na_geral(app_qt):  # noqa: ARG001
    modelo = Preferencias(None, lambda: True)
    for antigo in ("general", "session", "sgdb", "import", "xyz"):
        modelo.fechar()
        modelo.abrir(antigo)
        assert modelo.pagina == "geral"
    modelo.fechar()


def test_fechar_duas_vezes_nao_levanta(p):
    p.fechar()
    p.fechar()
    assert not p.aberto


def test_fechado_nao_segue_o_schema(p):
    p.fechar()
    avisos = []
    p.alterado.connect(lambda: avisos.append(1))
    shared.schema.set_boolean("auto-import", True)
    assert not avisos


def test_busca_ignora_maiusculas_e_acentos(p):
    assert p.corresponde("Iluminação inteligente", "ILUMINACAO")
    assert not p.corresponde("Iluminação inteligente", "controle")


def test_busca_vazia_mostra_tudo(p):
    assert p.corresponde("qualquer", "")


def test_valor_de_tipo_errado_e_recusado_sem_excecao(p, caplog):
    antes = {c: shared.schema.get_value(c) for c in shared.schema.list_keys()}
    with caplog.at_level("WARNING"):
        for chave, valor in (
            ("process-tracking-grace", float("nan")),
            ("process-tracking-grace", float("inf")),
            ("process-tracking-grace", "x"),
            ("process-tracking-grace", True),
            ("conquistas-aviso-som-volume", None),
            ("auto-import", "sim"),
            ("auto-import", 1),
        ):
            p.definir(chave, valor)
    assert {c: shared.schema.get_value(c) for c in shared.schema.list_keys()} == antes
    avisos = [r for r in caplog.records if r.name == "cartridges.modelos.preferencias"]
    assert len(avisos) == 7


def test_volume_limitado_de_10_a_100(p):
    p.definir("conquistas-aviso-som-volume", 3)
    assert shared.schema.get_int("conquistas-aviso-som-volume") == 10
    p.definir("conquistas-aviso-som-volume", 250.2)
    assert shared.schema.get_int("conquistas-aviso-som-volume") == 100


def test_rumble_segue_o_controle(p):
    p.definir("gamepad", False)
    assert not p.estado["rumbleAtivo"]
    p.definir("gamepad", True)
    assert p.estado["rumbleAtivo"]


def test_definir_texto_so_aceita_as_chaves_de_texto(p, caplog):
    with caplog.at_level("WARNING"):
        p.definirTexto("sgdb", "x")
        p.definirTexto("shortcuts-location", "C:/x")
    assert not shared.schema.get_boolean("sgdb")
    assert shared.schema.get_string("shortcuts-location") != "C:/x"
    avisos = [r for r in caplog.records if r.name == "cartridges.modelos.preferencias"]
    assert len(avisos) == 2


# region Atualizar metadados e capas


class _FilaFalsa:
    """No lugar da `FilaDeAvisos`: guarda o que entrou e o que foi dispensado."""

    def __init__(self):
        self.textos, self.chamadas, self.dispensados = [], [], []

    def adicionar(self, texto, botao="", ao_clicar=None, segundos=5, chave=None):
        self.textos.append(texto)
        self.chamadas.append({"texto": texto, "segundos": segundos})
        return len(self.textos)

    def dispensar(self, id_):
        self.dispensados.append(id_)


def _capas(store, make_game, n=2, **manager):
    from cartridges.store.managers.sgdb_manager import SgdbManager  # noqa: PLC0415

    jogos = [make_game(game_id=f"j{i}") for i in range(n)]
    for jogo in jogos:
        store.add_game(jogo, {})
    store.managers[SgdbManager] = gerente = _ManagerDeCapas(**manager)
    return jogos, gerente


def _modelo_de_atualizacoes(fila):
    from cartridges.modelos.preferencias import AtualizacoesDaBiblioteca  # noqa: PLC0415

    return AtualizacoesDaBiblioteca(fila)


def test_m8_lote_de_capas_nao_repinta_jogo_apagado(app_qt, store, make_game):
    jogos, gerente = _capas(store, make_game, n=1)
    _modelo_de_atualizacoes(_FilaFalsa()).atualizarCapas()

    store.clear()  # o reset chegou com o lote em voo
    for callback in gerente.callbacks:
        callback(gerente)

    assert jogos[0].updates == 0


def test_m8_tarefa_enfileirada_ve_o_cancelamento_do_reset(monkeypatch, make_game):
    from cartridges.store.managers import sgdb_manager  # noqa: PLC0415
    from cartridges.store.managers.async_manager import AsyncManager  # noqa: PLC0415

    enfileiradas = []
    monkeypatch.setattr(
        AsyncManager,
        "process_game",
        lambda _self, game, data, _callback: enfileiradas.append((game, data)),
    )
    ajudas = []
    monkeypatch.setattr(sgdb_manager, "SgdbHelper", lambda: ajudas.append(1))

    manager = sgdb_manager.SgdbManager()
    manager.process_game(make_game(), {}, lambda _m: None)
    manager.cancel_tasks()
    manager.reset_cancellable()
    game, data = enfileiradas[0]
    manager.main(game, data)

    assert ajudas == []


def test_sem_jogos_avisa_e_nao_pergunta(app_qt, store):
    fila, perguntas = _FilaFalsa(), []
    modelo = _modelo_de_atualizacoes(fila)
    modelo.perguntar.connect(perguntas.append)

    modelo.atualizarMetadados()

    assert fila.textos == ["Nenhum jogo na biblioteca"]
    assert not perguntas


def _completo(make_game, **extra):
    from cartridges.utils.steam import STEAM_METADATA_VERSION  # noqa: PLC0415

    return make_game(
        steam_appid="1", steam_checked=STEAM_METADATA_VERSION, developer="D", release_date="2020", genre="G",
        has_hltb_times=True, **extra,
    )  # fmt: skip


def test_pergunta_com_a_contagem_dos_incompletos(app_qt, store, make_game):
    store.add_game(_completo(make_game, game_id="a"), {})
    store.add_game(make_game(game_id="b", has_hltb_times=True), {})
    store.add_game(make_game(game_id="c", has_hltb_times=False), {})
    store.add_game(make_game(game_id="d", removed=True, has_hltb_times=False), {})  # fora da biblioteca
    perguntas = []
    modelo = _modelo_de_atualizacoes(_FilaFalsa())
    modelo.perguntar.connect(perguntas.append)

    modelo.atualizarMetadados()

    assert perguntas == [
        "Buscar o que falta atualiza 2 de 3 jogos, consultando somente os campos ausentes. "
        "Buscar tudo preenche todos os campos, podendo levar mais tempo."
    ]


def test_recusa_por_ja_estar_rodando_avisa(app_qt, store, make_game, monkeypatch):
    from cartridges import metadata_refresh  # noqa: PLC0415

    store.add_game(make_game(game_id="b", has_hltb_times=False), {})
    refresh = metadata_refresh.MetadataRefresh()
    refresh.running = True
    monkeypatch.setattr(metadata_refresh, "get_metadata_refresh", lambda: refresh)
    fila = _FilaFalsa()

    _modelo_de_atualizacoes(fila).buscarMetadados(True)

    assert fila.textos == ["Uma atualização de metadados já está em andamento"]


def test_recusa_por_nada_a_buscar_avisa(app_qt, store, make_game, monkeypatch):
    from cartridges import metadata_refresh  # noqa: PLC0415

    store.add_game(_completo(make_game, game_id="a"), {})
    monkeypatch.setattr(metadata_refresh, "get_metadata_refresh", lambda: metadata_refresh.MetadataRefresh())
    fila = _FilaFalsa()

    _modelo_de_atualizacoes(fila).buscarMetadados(True)

    assert fila.textos == ["Todos os jogos já estão com os metadados completos"]


def test_resposta_vale_para_a_lista_da_hora_da_pergunta(app_qt, store, make_game, monkeypatch):
    """Guarda os jogos da pergunta; um jogo que entra depois não entra na busca."""
    from cartridges import metadata_refresh  # noqa: PLC0415

    faltando = make_game(game_id="b", has_hltb_times=False)
    store.add_game(faltando, {})
    chamadas = []

    class Falso(metadata_refresh.MetadataRefresh):
        def start(self, games, only_missing=False):
            chamadas.append((games, only_missing))
            return True

    monkeypatch.setattr(metadata_refresh, "get_metadata_refresh", lambda: Falso())
    perguntas = []
    modelo = _modelo_de_atualizacoes(_FilaFalsa())
    modelo.perguntar.connect(perguntas.append)
    modelo.atualizarMetadados()
    assert perguntas[0].startswith("Buscar o que falta atualiza 1 de 1 jogos")
    store.add_game(make_game(game_id="c", has_hltb_times=False), {})  # chega depois da pergunta
    modelo.buscarMetadados(True)
    assert chamadas == [([faltando], True)]


def test_buscar_metadados_comeca_pelos_jogos_certos(app_qt, store, make_game, monkeypatch):
    from cartridges import metadata_refresh  # noqa: PLC0415

    completo = _completo(make_game, game_id="a")
    faltando = make_game(game_id="b", has_hltb_times=False)
    store.add_game(completo, {})
    store.add_game(faltando, {})
    chamadas = []

    class Falso(metadata_refresh.MetadataRefresh):
        def start(self, games, only_missing=False):
            chamadas.append((games, only_missing))
            return True

    falso = Falso()
    monkeypatch.setattr(metadata_refresh, "get_metadata_refresh", lambda: falso)
    modelo = _modelo_de_atualizacoes(_FilaFalsa())
    modelo.buscarMetadados(True)
    modelo.buscarMetadados(False)

    assert chamadas == [([faltando], True), ([completo, faltando], False)]


def test_baixando_capas_usa_o_tempo_padrao_do_aviso(app_qt, store, make_game):
    # O aviso comum sai sozinho; só o fim do lote o dispensa antes.
    _capas(store, make_game)
    fila = _FilaFalsa()
    _modelo_de_atualizacoes(fila).atualizarCapas()
    assert fila.chamadas == [{"texto": "Baixando capas…", "segundos": 5}]


def test_capas_dispensam_o_baixando_e_avisam_o_fim(app_qt, store, make_game):
    jogos, gerente = _capas(store, make_game)
    fila = _FilaFalsa()
    modelo = _modelo_de_atualizacoes(fila)

    modelo.atualizarCapas()

    assert gerente.resets == 1
    assert fila.chamadas == [{"texto": "Baixando capas…", "segundos": 5}]
    assert modelo.baixandoCapas is True
    gerente.callbacks[0](gerente)
    assert modelo.baixandoCapas is True and not fila.dispensados
    gerente.callbacks[1](gerente)
    assert fila.dispensados == [1]
    assert fila.textos == ["Baixando capas…", "Capas atualizadas"]
    assert modelo.baixandoCapas is False
    assert [jogo.updates for jogo in jogos] == [1, 1]


def test_erro_amigavel_das_capas_vira_dialogo_uma_vez(app_qt, store, make_game, monkeypatch):
    from cartridges import shared  # noqa: PLC0415
    from cartridges.errors.friendly_error import FriendlyError  # noqa: PLC0415

    dialogos = []
    monkeypatch.setattr(
        shared, "aplicativo", types.SimpleNamespace(pedir_dialogo=lambda *a, **k: dialogos.append(a)), raising=False
    )
    erros = [FriendlyError("Título 1", "Corpo 1"), FriendlyError("Título 2", "Corpo 2")]
    _, gerente = _capas(store, make_game, erros=erros)
    _modelo_de_atualizacoes(_FilaFalsa()).atualizarCapas()

    for callback in gerente.callbacks:
        callback(gerente)

    assert [d[:3] for d in dialogos] == [("Título 1", "Corpo 1", [])]


def test_capas_sem_jogos_nao_faz_nada(app_qt, store):
    fila = _FilaFalsa()
    modelo = _modelo_de_atualizacoes(fila)
    modelo.atualizarCapas()
    assert not fila.textos and modelo.baixandoCapas is False


def test_fechar_as_preferencias_nao_cancela_os_metadados(app_qt, monkeypatch):
    from cartridges import metadata_refresh  # noqa: PLC0415

    refresh = metadata_refresh.MetadataRefresh()
    refresh.running = True
    monkeypatch.setattr(metadata_refresh, "get_metadata_refresh", lambda: refresh)
    modelo = Preferencias(None, lambda: True)
    assert modelo.abrir()

    modelo.fechar()

    assert refresh.running is True and refresh.cancelled is False


# endregion


# region Personalização: monitores, papel de parede


def _abrir(stored=""):
    shared.schema.set_string("session-monitor", stored)
    modelo = Preferencias(None, lambda: True)
    assert modelo.abrir()
    return modelo


def test_principal_nunca_entra_na_lista(p):
    assert p.estado["monitores"] == ["Monitor 2", "Monitor 3"]
    assert not p.estado["semSegundoMonitor"]


def test_escolha_antiga_pelo_nome_e_regravada_pelo_caminho(app_qt, monitores):  # noqa: ARG001
    modelo = _abrir(TERCEIRO.device)
    try:
        assert modelo.estado["monitorEscolhido"] == 1
        assert shared.schema.get_string("session-monitor") == TERCEIRO.path
    finally:
        modelo.fechar()


def test_monitor_escolhido_desligado_cai_no_primeiro_e_grava(app_qt, monitores):  # noqa: ARG001
    modelo = _abrir(r"\\?\DISPLAY#SUMIU#9")
    try:
        assert modelo.estado["monitorEscolhido"] == 0
        assert shared.schema.get_string("session-monitor") == SEGUNDO.path
    finally:
        modelo.fechar()


def test_escolher_monitor_grava_o_caminho(p):
    p.escolherMonitor(1)
    assert shared.schema.get_string("session-monitor") == TERCEIRO.path
    assert p.estado["monitorEscolhido"] == 1


def test_escolha_fora_da_faixa_nao_grava(p):
    antes = shared.schema.get_string("session-monitor")
    for indice in (-1, 2, 99):
        p.escolherMonitor(indice)
    assert shared.schema.get_string("session-monitor") == antes


def test_sem_segundo_monitor_desliga_as_duas_e_explica(app_qt, monitores):  # noqa: ARG001
    shared.schema.set_boolean("session-move-window", True)
    shared.schema.set_boolean("session-wallpaper", True)
    monitores[:] = [PRINCIPAL]
    modelo = _abrir()
    try:
        assert modelo.estado["semSegundoMonitor"] is True
        assert modelo.estado["monitores"] == []
        assert not shared.schema.get_boolean("session-move-window")
        assert not shared.schema.get_boolean("session-wallpaper")
        assert modelo.valores["session-move-window"] is False
    finally:
        modelo.fechar()


def test_identificar_cria_uma_placa_por_monitor_no_centro(p, monkeypatch):
    criadas = []
    monkeypatch.setattr(window_geometry, "_criar_placa", lambda monitor, lado: criadas.append((monitor, lado)))
    monkeypatch.setattr(window_geometry.QTimer, "singleShot", lambda *_a: None)
    p.identificarMonitores()
    assert criadas == [(PRINCIPAL, 270), (SEGUNDO, 200), (TERCEIRO, 270)]


def test_placa_no_centro_do_monitor(app_qt, monkeypatch):  # noqa: ARG001
    postas = []
    monkeypatch.setattr(window_geometry, "_place", lambda _janela, geometria: postas.append(geometria) or True)
    for monitor, lado, esperado in (
        (PRINCIPAL, 270, window_geometry.Geometry(825, 405, 270, 270, False)),
        (SEGUNDO, 200, window_geometry.Geometry(2220, 200, 200, 200, False)),
        (TERCEIRO, 270, window_geometry.Geometry(-1095, 405, 270, 270, False)),
    ):
        placa = _CRIAR_PLACA_REAL(monitor, lado)
        try:
            assert postas[-1] == esperado
            assert placa.rootObject().property("numero") == monitor.number
        finally:
            placa.close()
            placa.deleteLater()


def test_placa_e_janela_comum_que_recebe_foco_e_aparece_na_barra_de_tarefas(app_qt, monkeypatch):  # noqa: ARG001
    """A janela é comum: sem `Tool`, `DoesNotAcceptFocus` nem `TransparentForInput`."""
    monkeypatch.setattr(window_geometry, "_place", lambda _janela, _geometria: True)
    placa = _CRIAR_PLACA_REAL(SEGUNDO, 200)
    try:
        flags = placa.flags()
        assert flags & Qt.WindowType.FramelessWindowHint
        assert flags & Qt.WindowType.WindowType_Mask == Qt.WindowType.Window  # `Tool` tira da barra de tarefas
        for tirada in (
            Qt.WindowType.WindowDoesNotAcceptFocus,
            Qt.WindowType.WindowTransparentForInput, Qt.WindowType.WindowStaysOnTopHint,
        ):
            assert not flags & tirada, tirada
    finally:
        placa.close()
        placa.deleteLater()


def test_placas_fecham_sozinhas_mesmo_com_as_preferencias_fechadas(p, monkeypatch):
    class Placa:
        fechadas = 0

        def close(self):
            Placa.fechadas += 1

        def deleteLater(self):  # noqa: N802
            pass

    fios = []
    monkeypatch.setattr(window_geometry, "_criar_placa", lambda _m, _l: Placa())
    monkeypatch.setattr(window_geometry.QTimer, "singleShot", lambda ms, f: fios.append((ms, f)))
    p.identificarMonitores()
    p.fechar()
    assert Placa.fechadas == 0
    assert len(window_geometry._placas) == 3  # noqa: SLF001 - seguradas até fechar
    assert [ms for ms, _f in fios] == [3000] * 3
    for _ms, fechar in fios:
        fechar()
    assert Placa.fechadas == 3
    assert window_geometry._placas == []  # noqa: SLF001


def test_window_geometry_sem_gtk_nas_funcoes_da_tela():
    import inspect  # noqa: PLC0415

    for nome in ("escolha_de_monitor", "identificar_monitores", "_criar_placa"):
        fonte = inspect.getsource(getattr(window_geometry, nome))
        assert "from gi" not in fonte
        assert "Gtk" not in fonte
    for velho in ("preencher_escolha_de_monitor", "identify_monitors", "_center_badge", "_close_badge"):
        assert not hasattr(window_geometry, velho)


def test_escolha_de_monitor_rotulos_e_indice():
    assert window_geometry.escolha_de_monitor([SEGUNDO, TERCEIRO], TERCEIRO.path) == (["Monitor 2", "Monitor 3"], 1)
    assert window_geometry.escolha_de_monitor([SEGUNDO, TERCEIRO], "nada") == (["Monitor 2", "Monitor 3"], 0)
