"""O cartão de conquistas na página do jogo e a lista completa."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from gi.repository import GLib, Gtk
from requests.exceptions import ConnectionError as ErroDeConexao

from cartridges import conquistas_sessao
from cartridges.conquistas import catalogo, historico, icones
from cartridges.conquistas.catalogo import Catalogo, ConquistaInfo
from cartridges.conquistas.formatos import Desbloqueio
from cartridges.conquistas.xbox import conta
from tests.apoio_conquistas import com_fonte
from tests.test_zerados import jogo

# A fixture abaixo troca `icones.carregar` por um no-op; os testes do próprio
# módulo de ícones precisam da função de verdade.
carregar_de_verdade = icones.carregar

CAT = Catalogo(
    (
        ConquistaInfo("A", "Primeira", "Faça algo.", "", "", False, 55.0),
        ConquistaInfo("B", "Rara", "Difícil.", "", "", False, 4.1),
        ConquistaInfo("C", "Segredo", "Spoiler.", "", "", True, 20.0),
    ),
    0,
    True,
)

URL = "https://cdn.exemplo.com/a.jpg?key=SEGREDO"


@pytest.fixture(autouse=True)
def sem_icones(monkeypatch):
    monkeypatch.setattr(icones, "carregar", lambda _origem, _entregar: None)


@pytest.fixture
def executor_proprio(monkeypatch):
    """Um executor novo por teste: ``encerrar`` não pode vazar para os outros."""
    executor = ThreadPoolExecutor(max_workers=2)
    monkeypatch.setattr(icones, "_trabalhadores", executor)
    yield executor
    executor.shutdown(wait=False, cancel_futures=True)


@pytest.fixture
def com_conquistas(store):
    catalogo.guardar("570", CAT)
    game = jogo(store, 1, steam_appid="570")
    historico.registrar(game.game_id, [Desbloqueio("A", 100), Desbloqueio("B", 200)])
    com_fonte(game, "steam:570")
    return game


def test_cartao_mostra_o_progresso(real_window, com_conquistas):
    real_window.update_conquistas_block(com_conquistas)
    assert real_window.details_view_conquistas_box.get_visible()
    assert real_window.details_view_conquistas_count.get_label() == "2 de 3"
    assert real_window.details_view_conquistas_percent.get_label() == "66%"  # para baixo
    assert real_window.details_view_conquistas_bar.get_fraction() == pytest.approx(2 / 3)


def test_cartao_nao_arredonda_para_cima_ate_o_fim(real_window, store):
    """999 de 1000 é 99%: 100% só quando está tudo desbloqueado."""
    grande = Catalogo(
        tuple(ConquistaInfo(f"N{n}", f"N{n}", "", "", "", False) for n in range(1000)), 0, True
    )
    catalogo.guardar("570", grande)
    game = jogo(store, 1, steam_appid="570")
    historico.registrar(game.game_id, [Desbloqueio(f"N{n}", 1) for n in range(999)])
    com_fonte(game, "steam:570")
    real_window.update_conquistas_block(game)
    assert real_window.details_view_conquistas_count.get_label() == "999 de 1000"
    assert real_window.details_view_conquistas_percent.get_label() == "99%"

    historico.registrar(game.game_id, [Desbloqueio("N999", 1)])
    real_window.update_conquistas_block(game)
    assert real_window.details_view_conquistas_percent.get_label() == "100%"


def test_cartao_some_sem_catalogo_ou_desligado(real_window, store, com_conquistas):
    com_conquistas.conquistas = False
    real_window.update_conquistas_block(com_conquistas)
    assert not real_window.details_view_conquistas_box.get_visible()

    sem_catalogo = jogo(store, 2, steam_appid="999")
    com_fonte(sem_catalogo, "steam:999")
    real_window.update_conquistas_block(sem_catalogo)
    assert not real_window.details_view_conquistas_box.get_visible()


def test_historico_antigo_sem_fonte_fica_oculto_ate_a_varredura(real_window, store):
    catalogo.guardar("570", CAT)
    game = jogo(store, 1, steam_appid="570")
    historico.registrar(game.game_id, [Desbloqueio("A", 1)])
    real_window.update_conquistas_block(game)
    assert not real_window.details_view_conquistas_box.get_visible()
    com_fonte(game, "steam:570")
    real_window.update_conquistas_block(game)
    assert real_window.details_view_conquistas_box.get_visible()


def test_xbox_some_ao_sair_da_conta(real_window, store, monkeypatch):
    catalogo.guardar("xbox-7", CAT)
    game = jogo(store, 1)
    com_fonte(game, "xbox:7")
    monkeypatch.setattr(conta, "conectada", lambda: True)
    real_window.update_conquistas_block(game)
    assert real_window.details_view_conquistas_box.get_visible()
    monkeypatch.setattr(conta, "conectada", lambda: False)
    real_window.update_conquistas_block(game)
    assert not real_window.details_view_conquistas_box.get_visible()


def test_fonte_gravada_manda_mais_que_o_appid_atual(real_window, store):
    catalogo.guardar("570", CAT)
    game = jogo(store, 1, steam_appid="999")
    com_fonte(game, "steam:570")
    real_window.update_conquistas_block(game)
    assert real_window.details_view_conquistas_box.get_visible()


def test_icone_baixado_vai_para_o_cache(monkeypatch):
    chamadas = []

    def baixar(url, timeout, max_bytes):
        chamadas.append(url)
        return b"dados"

    monkeypatch.setattr(icones, "download_bytes", baixar)
    primeiro = icones.arquivo_local(URL)
    assert primeiro is not None and primeiro.read_bytes() == b"dados"
    assert icones.arquivo_local(URL) == primeiro
    assert len(chamadas) == 1
    assert not list(primeiro.parent.glob("*.tmp"))


def test_downloads_simultaneos_do_mesmo_icone_nao_se_atropelam(monkeypatch):
    ambas_baixando = threading.Barrier(2, timeout=5)

    def baixar(url, timeout, max_bytes):
        ambas_baixando.wait()  # as duas já passaram pela checagem do cache
        return b"dados"

    monkeypatch.setattr(icones, "download_bytes", baixar)
    resultados = []
    threads = [
        threading.Thread(target=lambda: resultados.append(icones.arquivo_local(URL)))
        for _ in range(2)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)

    assert len(resultados) == 2 and all(r is not None for r in resultados)
    assert resultados[0] == resultados[1]
    assert resultados[0].read_bytes() == b"dados"
    assert not list(resultados[0].parent.glob("*.tmp"))


@pytest.mark.parametrize(
    "erro", [OSError("disco"), RuntimeError("rede"), RecursionError()]
)
def test_icone_nunca_levanta(monkeypatch, erro):
    def baixar(url, timeout, max_bytes):
        raise erro

    monkeypatch.setattr(icones, "download_bytes", baixar)
    assert icones.arquivo_local(URL) is None


def test_erro_de_rede_com_a_url_no_texto_nao_vaza_a_chave(monkeypatch, caplog):
    def baixar(url, timeout, max_bytes):
        raise ErroDeConexao(f"Falha ao conectar em {url}")

    monkeypatch.setattr(icones, "download_bytes", baixar)
    with caplog.at_level("DEBUG"):
        assert icones.arquivo_local(URL) is None
    assert "SEGREDO" not in caplog.text
    assert "cdn.exemplo.com/a.jpg" in caplog.text


def test_erro_inesperado_leva_traceback_sem_a_chave_na_mensagem(monkeypatch, caplog):
    def baixar(url, timeout, max_bytes):
        raise ValueError("defeito nosso")

    monkeypatch.setattr(icones, "download_bytes", baixar)
    with caplog.at_level("DEBUG"):
        assert icones.arquivo_local(URL) is None
    registro = next(r for r in caplog.records if r.levelname == "WARNING")
    assert registro.exc_info is not None
    assert "SEGREDO" not in registro.getMessage()


def test_icone_local_inexistente_ou_vazio(tmp_path):
    assert icones.arquivo_local("") is None
    assert icones.arquivo_local(str(tmp_path / "nao_existe.png")) is None


@pytest.mark.parametrize(
    "origem", [r"\\servidor\pasta\x.png", "//servidor/pasta/x.png", r"\\?\UNC\srv\x.png"]
)
def test_icone_em_caminho_de_rede_nao_toca_no_disco(monkeypatch, origem):
    tocou = []

    def is_file(self, *_a, **_k):
        # `_resolver` engole qualquer exceção: o registro é o que prova o acesso.
        tocou.append(str(self))
        return False

    monkeypatch.setattr(Path, "is_file", is_file)
    assert icones.arquivo_local(origem) is None
    assert icones._textura(origem) is None
    assert tocou == []


def test_arquivo_ilegivel_no_cache_e_apagado(monkeypatch):
    monkeypatch.setattr(
        icones, "download_bytes", lambda *_a, **_k: b"<html>portal</html>"
    )
    arquivo = icones.arquivo_local(URL)
    assert arquivo is not None and arquivo.is_file()

    assert icones._textura(URL) is None
    assert not arquivo.exists()


def test_arquivo_local_ilegivel_nao_e_apagado(tmp_path):
    arquivo = tmp_path / "icone.png"
    arquivo.write_bytes(b"nao e imagem")
    assert icones._textura(str(arquivo)) is None
    assert arquivo.exists()


def test_carregar_depois_de_encerrar_nao_faz_nada(executor_proprio, monkeypatch):
    baixou = []
    monkeypatch.setattr(
        icones, "download_bytes", lambda *_a, **_k: baixou.append(1) or b""
    )
    entregues = []

    icones.encerrar()
    carregar_de_verdade(URL, entregues.append)

    assert not baixou
    assert not entregues


def test_encerrar_nunca_levanta(executor_proprio, monkeypatch):
    def quebrar(*_a, **_k):
        raise RuntimeError("falha")

    with monkeypatch.context() as parcial:
        parcial.setattr(executor_proprio, "shutdown", quebrar)
        icones.encerrar()


def _titulos(linhas):
    return [linha.get_title() for linha in linhas]


def test_lista_em_duas_secoes(real_window, com_conquistas):
    from cartridges.conquistas_dialog import ConquistasDialog  # noqa: PLC0415

    dialogo = ConquistasDialog(com_conquistas)
    assert _titulos(dialogo.linhas_desbloqueadas) == ["Rara", "Primeira"]  # recente primeiro
    assert _titulos(dialogo.linhas_bloqueadas) == ["Conquista oculta"]
    assert dialogo.linhas_bloqueadas[0].get_subtitle() == (
        "Os detalhes aparecem depois do desbloqueio."
    )


def test_ocultas_reveladas_pela_preferencia(real_window, com_conquistas, schema):
    from cartridges.conquistas_dialog import ConquistasDialog  # noqa: PLC0415

    schema.set_boolean("conquistas-mostrar-ocultas", True)
    dialogo = ConquistasDialog(com_conquistas)
    assert _titulos(dialogo.linhas_bloqueadas) == ["Segredo"]


def test_oculta_desbloqueada_aparece_sempre(real_window, com_conquistas):
    from cartridges.conquistas_dialog import ConquistasDialog  # noqa: PLC0415

    historico.registrar(com_conquistas.game_id, [Desbloqueio("C", 300)])
    dialogo = ConquistasDialog(com_conquistas)
    assert _titulos(dialogo.linhas_desbloqueadas) == ["Segredo", "Rara", "Primeira"]
    assert dialogo.linhas_bloqueadas == []


def _rotulos(widget):
    """Os textos de todos os Gtk.Label dentro de ``widget``."""
    textos = []
    filho = widget.get_first_child()
    while filho is not None:
        if isinstance(filho, Gtk.Label):
            textos.append(filho.get_label())
        textos.extend(_rotulos(filho))
        filho = filho.get_next_sibling()
    return textos


def _imagens(widget):
    """Todos os Gtk.Image dentro de ``widget``."""
    achadas = []
    filho = widget.get_first_child()
    while filho is not None:
        if isinstance(filho, Gtk.Image):
            achadas.append(filho)
        achadas.extend(_imagens(filho))
        filho = filho.get_next_sibling()
    return achadas


def test_bloqueada_sem_icone_cinza_usa_o_icone_apagado(real_window, store, monkeypatch):
    from cartridges.conquistas_dialog import ConquistasDialog  # noqa: PLC0415

    carregados = []
    monkeypatch.setattr(icones, "carregar", lambda origem, _entregar: carregados.append(origem))
    cat = Catalogo((ConquistaInfo("XBOX:1", "T", "D", "https://x/1.png", "", False),), 0, False)
    catalogo.guardar("xbox-7", cat)
    game = jogo(store, 1)
    com_fonte(game, "xbox:7")
    monkeypatch.setattr(conta, "conectada", lambda: True)
    dialogo = ConquistasDialog(game)
    assert carregados == ["https://x/1.png"]
    imagens = [i for fileira in dialogo.linhas_bloqueadas for i in _imagens(fileira)]
    assert any(i.has_css_class("conquistas-icone-bloqueada") for i in imagens)


def test_bloqueada_com_icone_cinza_nao_ganha_filtro(real_window, store, monkeypatch):
    from cartridges.conquistas_dialog import ConquistasDialog  # noqa: PLC0415

    carregados = []
    monkeypatch.setattr(icones, "carregar", lambda origem, _entregar: carregados.append(origem))
    cat = Catalogo(
        (ConquistaInfo("A", "T", "D", "https://x/cor.png", "https://x/cinza.png", False),), 0, False
    )
    catalogo.guardar("570", cat)
    game = jogo(store, 1, steam_appid="570")
    com_fonte(game, "steam:570")
    dialogo = ConquistasDialog(game)
    assert carregados == ["https://x/cinza.png"]
    imagens = [i for fileira in dialogo.linhas_bloqueadas for i in _imagens(fileira)]
    assert imagens and not any(i.has_css_class("conquistas-icone-bloqueada") for i in imagens)


def test_data_da_conquista_comeca_com_maiuscula(real_window, com_conquistas):
    from cartridges.conquistas_dialog import ConquistasDialog, _data  # noqa: PLC0415

    assert _data(int(time.time())) == "Hoje"
    assert _data(int(time.time()) - 86400) == "Ontem"
    assert _data(2**62) is None

    historico.registrar(com_conquistas.game_id, [Desbloqueio("C", int(time.time()))])
    dialogo = ConquistasDialog(com_conquistas)
    textos = [texto for fileira in dialogo.linhas_desbloqueadas for texto in _rotulos(fileira)]
    assert "Hoje" in textos
    assert "hoje" not in textos


@pytest.mark.parametrize("quando", [2**62, -(2**62), -1, 2**63 - 1, -(2**63)])
def test_data_absurda_nao_derruba_a_lista(real_window, com_conquistas, quando):
    from cartridges.conquistas_dialog import ConquistasDialog  # noqa: PLC0415

    historico.registrar(com_conquistas.game_id, [Desbloqueio("C", quando)])
    dialogo = ConquistasDialog(com_conquistas)
    assert "Segredo" in _titulos(dialogo.linhas_desbloqueadas)


# -- Cartão da tela de sessão --------------------------------------------------


def _cartao(real_window):
    filhos = []
    filho = real_window.session_blocker_conquistas.get_first_child()
    while filho is not None:
        filhos.append(filho)
        filho = filho.get_next_sibling()
    return next(f for f in filhos if isinstance(f, conquistas_sessao.CartaoDaSessao))


def _icones(cartao):
    caixas = []
    filho = cartao.icones.get_first_child()
    while filho is not None:
        caixas.append(filho.get_child())
        filho = filho.get_next_sibling()
    return caixas


def _filhos_do_cartao(cartao):
    filho = cartao.icones.get_first_child()
    while filho is not None:
        yield filho
        filho = filho.get_next_sibling()


def test_cartao_da_sessao_mostra_progresso_e_todos_os_icones(real_window, com_conquistas, sessao_sem_efeitos):
    real_window.show_session_blocker(com_conquistas)
    cartao = _cartao(real_window)
    assert cartao.get_visible()
    assert cartao.contagem.get_label() == "2 de 3"
    assert cartao.porcentagem.get_label() == "66%"
    imagens = _icones(cartao)
    assert len(imagens) == 3  # A, B e a oculta C, na ordem do catálogo
    assert imagens[0].get_tooltip_markup().startswith("<b>Primeira</b>")
    assert imagens[2].get_tooltip_markup() == (
        "<b>Conquista oculta</b>\nOs detalhes aparecem depois do desbloqueio."
    )


def test_cartao_da_sessao_some_sem_conquistas(real_window, store, sessao_sem_efeitos):
    real_window.show_session_blocker(jogo(store, 9, steam_appid="999"))
    assert not _cartao(real_window).get_visible()


def test_cartao_da_sessao_esvazia_no_fim(real_window, com_conquistas, sessao_sem_efeitos):
    real_window.show_session_blocker(com_conquistas)
    real_window.hide_session_blocker()
    cartao = _cartao(real_window)
    assert not cartao.get_visible() and _icones(cartao) == []


def test_cartao_da_sessao_atualiza_ao_vivo(real_window, com_conquistas, sessao_sem_efeitos):
    real_window.show_session_blocker(com_conquistas)
    historico.registrar(com_conquistas.game_id, [Desbloqueio("C", 300)])
    real_window.update_conquistas_sessao(com_conquistas)
    assert _cartao(real_window).contagem.get_label() == "3 de 3"


def test_atualizar_outro_jogo_nao_mexe_no_cartao(real_window, com_conquistas, store, sessao_sem_efeitos):
    real_window.show_session_blocker(com_conquistas)
    real_window.update_conquistas_sessao(jogo(store, 9, steam_appid="999"))
    assert _cartao(real_window).contagem.get_label() == "2 de 3"


def test_muitas_conquistas_rolam_dentro_do_cartao(real_window, store, sessao_sem_efeitos):
    grande = Catalogo(
        tuple(ConquistaInfo(f"N{n}", f"N{n}", "", "", "", False) for n in range(157)), 0, True
    )
    catalogo.guardar("570", grande)
    game = jogo(store, 1, steam_appid="570")
    com_fonte(game, "steam:570")
    real_window.show_session_blocker(game)
    cartao = _cartao(real_window)
    assert cartao.rolagem.get_max_content_height() == conquistas_sessao.ALTURA_MAXIMA
    assert cartao.rolagem.get_propagate_natural_height() is True
    assert cartao.rolagem.get_policy()[0] == Gtk.PolicyType.NEVER
    assert len(_icones(cartao)) == 157


def _catalogo_de(quantas):
    return Catalogo(
        tuple(ConquistaInfo(f"N{n}", f"N{n}", "", "", "", False) for n in range(quantas)), 0, True
    )


def _apresentar_e_mostrar(real_window, game):
    """A janela de verdade, do tamanho de um monitor, com o bloqueador aberto e
    o layout resolvido: é a alocação real que diz se os ícones se espalham."""
    real_window.set_default_size(1280, 800)
    real_window.present()
    real_window.show_session_blocker(game)
    contexto = GLib.MainContext.default()
    for _ in range(300):
        contexto.iteration(False)


def test_icones_se_espalham_para_os_lados_antes_de_quebrar(real_window, store, sessao_sem_efeitos):
    catalogo.guardar("570", _catalogo_de(12))
    game = jogo(store, 1, steam_appid="570")
    com_fonte(game, "steam:570")
    _apresentar_e_mostrar(real_window, game)
    cartao = _cartao(real_window)
    assert cartao.icones.get_max_children_per_line() == 12
    assert cartao.rolagem.get_propagate_natural_width() is True
    linhas = {filho.compute_bounds(cartao.icones)[1].get_y() for filho in _filhos_do_cartao(cartao)}
    assert len(linhas) == 1, "12 ícones cabem numa linha só"
    assert cartao.get_width() < real_window.get_width()


def test_com_157_conquistas_o_cartao_rola_e_o_botao_continua_na_janela(real_window, store, sessao_sem_efeitos):
    catalogo.guardar("570", _catalogo_de(157))
    game = jogo(store, 1, steam_appid="570")
    com_fonte(game, "steam:570")
    _apresentar_e_mostrar(real_window, game)
    cartao = _cartao(real_window)
    assert 0 < cartao.rolagem.get_height() <= conquistas_sessao.ALTURA_MAXIMA
    # O cartão cresce até a janela e não passa dela
    assert cartao.get_width() <= real_window.get_width()
    assert real_window.get_width() == 1280
    ok, limites = real_window.session_blocker_button.compute_bounds(real_window)
    assert ok
    assert limites.get_y() >= 0
    assert limites.get_y() + limites.get_height() <= real_window.get_height()


def test_falha_no_cartao_nao_derruba_o_bloqueador(real_window, com_conquistas, sessao_sem_efeitos, monkeypatch):
    def quebrar(_self, _game):
        raise RuntimeError("falha de teste")

    monkeypatch.setattr(conquistas_sessao.CartaoDaSessao, "mostrar", quebrar)
    real_window.show_session_blocker(com_conquistas)
    assert real_window.session_blocker.get_visible()
    assert real_window.session_blocker_button.get_sensitive()
    assert not _cartao(real_window).get_visible()


def test_slot_do_cartao_acompanha_a_visibilidade_do_cartao(real_window, com_conquistas, store, sessao_sem_efeitos):
    slot = real_window.session_blocker_conquistas
    assert not slot.get_visible()  # sem sessão, o slot não ocupa espaço
    real_window.show_session_blocker(jogo(store, 9, steam_appid="999"))
    assert not slot.get_visible()  # jogo sem conquistas: a tela fica como era
    real_window.hide_session_blocker()
    real_window.show_session_blocker(com_conquistas)
    assert slot.get_visible()
    real_window.hide_session_blocker()
    assert not slot.get_visible()


def test_slot_do_cartao_some_quando_o_cartao_falha(real_window, com_conquistas, sessao_sem_efeitos, monkeypatch):
    def quebrar(_self, _game):
        raise RuntimeError("falha de teste")

    monkeypatch.setattr(conquistas_sessao.CartaoDaSessao, "mostrar", quebrar)
    real_window.show_session_blocker(com_conquistas)
    assert not real_window.session_blocker_conquistas.get_visible()


def test_icones_do_cartao_sao_passivos(real_window, com_conquistas, sessao_sem_efeitos):
    real_window.show_session_blocker(com_conquistas)
    cartao = _cartao(real_window)
    assert cartao.icones.has_css_class("no-hover")
    filhos = list(_filhos_do_cartao(cartao))
    assert len(filhos) == 3
    # Ícones só com tooltip: nada no cartão pode entrar na ordem do Tab
    assert not cartao.icones.get_can_focus()
    assert not cartao.rolagem.get_can_focus()


def _foco_dentro_de(real_window, ancestral):
    """O foco pode estar num filho interno (o MenuButton foca o botão de dentro)."""
    foco = real_window.get_focus()
    while foco is not None:
        if foco is ancestral:
            return True
        foco = foco.get_parent()
    return False


@pytest.mark.parametrize(
    ("origem", "direcao"),
    [
        ("session_blocker_notes_button", Gtk.DirectionType.TAB_FORWARD),
        ("session_blocker_button", Gtk.DirectionType.TAB_BACKWARD),
    ],
)
def test_tab_atravessa_o_cartao_sem_perder_o_foco(real_window, store, sessao_sem_efeitos, origem, direcao):
    catalogo.guardar("570", _catalogo_de(12))
    game = jogo(store, 1, steam_appid="570")
    com_fonte(game, "steam:570")
    _apresentar_e_mostrar(real_window, game)
    botao = getattr(real_window, origem)
    botao.grab_focus()
    assert _foco_dentro_de(real_window, botao)
    assert real_window.child_focus(direcao)
    assert real_window.get_focus() is not None
    assert not _foco_dentro_de(real_window, botao)
    assert not _foco_dentro_de(real_window, _cartao(real_window))
