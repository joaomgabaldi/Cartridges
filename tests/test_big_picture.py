# test_big_picture.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Big Picture: lógica pura (lista, entrada automática, repetição, carrossel), CoverFlow e página."""

import math
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from gi.repository import Adw, GObject, Graphene, Gsk, Gtk

from cartridges import big_picture, shared
from cartridges.utils import restauracao


def _jogo(game_id, last_played=0, removed=False, blacklisted=False, name=None):
    return SimpleNamespace(
        game_id=game_id,
        name=name or game_id,
        last_played=last_played,
        removed=removed,
        blacklisted=blacklisted,
    )


def test_lista_so_tem_jogos_da_biblioteca_do_mais_recente(monkeypatch):
    jogos = [
        _jogo("a", 10),
        _jogo("b", 30),
        _jogo("c", 50, removed=True),
        _jogo("d", 60, blacklisted=True),
        _jogo("e", 70),
    ]
    monkeypatch.setattr(restauracao, "e_pendente", lambda game_id: game_id == "e")
    assert [j.game_id for j in big_picture.jogos_da_biblioteca(jogos)] == ["b", "a"]


def test_empate_de_last_played_vai_por_nome(monkeypatch):
    monkeypatch.setattr(restauracao, "e_pendente", lambda game_id: False)
    jogos = [_jogo("1", 0, name="beta"), _jogo("2", 0, name="Alfa")]
    assert [j.name for j in big_picture.jogos_da_biblioteca(jogos)] == ["Alfa", "beta"]


@pytest.mark.parametrize(
    "campo", ["preferencia", "controle_ligado", "tem_3d", "grade_a_vista"]
)
def test_cada_condicao_bloqueia_a_entrada_automatica(campo):
    args = dict(
        preferencia=True,
        controle_ligado=True,
        tem_3d=True,
        grade_a_vista=True,
        ja_saiu=False,
    )
    assert big_picture.pode_entrar_sozinho(**args)
    args[campo] = False
    assert not big_picture.pode_entrar_sozinho(**args)


def test_ja_ter_saido_bloqueia_a_entrada_automatica():
    assert not big_picture.pode_entrar_sozinho(
        preferencia=True,
        controle_ligado=True,
        tem_3d=True,
        grade_a_vista=True,
        ja_saiu=True,
    )


def test_sem_renderizador_ou_com_cairo_nao_tem_3d():
    assert not big_picture.tem_3d(SimpleNamespace(get_renderer=lambda: None))
    assert not big_picture.tem_3d(
        SimpleNamespace(get_renderer=lambda: Gsk.CairoRenderer.new())
    )
    assert big_picture.tem_3d(SimpleNamespace(get_renderer=lambda: object()))


def test_repeticao_acelera_depois_de_um_segundo():
    assert big_picture.intervalo_de_repeticao_us(0) == 120_000
    assert big_picture.intervalo_de_repeticao_us(999_999) == 120_000
    assert big_picture.intervalo_de_repeticao_us(1_000_000) == 40_000


def test_mover_fica_preso_nas_pontas():
    c = big_picture.Carrossel(["a", "b", "c"])
    assert c.indice == 0 and c.atual == "a"
    assert not c.mover(-1) and c.indice == 0
    assert c.mover(+1) and c.atual == "b"
    assert c.mover(+10) and c.indice == 2
    assert not c.mover(+1)


def test_inicio_e_fim():
    c = big_picture.Carrossel(["a", "b", "c"])
    assert not c.inicio()
    assert c.fim() and c.indice == 2
    assert not c.fim()
    assert c.inicio() and c.indice == 0


def test_lista_vazia_nao_move():
    c = big_picture.Carrossel([])
    assert c.atual is None and not c.mover(1) and not c.fim()


def test_trocar_lista_mantem_o_jogo_central():
    c = big_picture.Carrossel(["a", "b", "c"])
    c.ir_para(1)
    c.trocar_lista(["x", "a", "b", "c"])
    assert c.atual == "b"


def test_trocar_lista_cai_no_vizinho_quando_o_central_some():
    c = big_picture.Carrossel(["a", "b", "c"])
    c.ir_para(2)
    c.trocar_lista(["a", "b"])
    assert c.indice == 1


def test_trocar_lista_com_centro_explicito():
    c = big_picture.Carrossel(["a", "b", "c"])
    c.trocar_lista(["a", "b", "c"], centro="c")
    assert c.atual == "c"


def test_trocar_para_lista_vazia_zera_o_indice():
    c = big_picture.Carrossel(["a", "b"])
    c.ir_para(1)
    c.trocar_lista([])
    assert c.indice == 0 and c.atual is None


# --- CoverFlow e o motivo de animação da capa central ---------------------

from gi.repository import Graphene  # noqa: E402

from cartridges.game_cover import GameCover  # noqa: E402


@pytest.fixture
def cover_flow_5_jogos():
    jogos = [
        SimpleNamespace(game_cover=GameCover(set()), name=f"J{i}", developer="D")
        for i in range(5)
    ]
    fluxo = big_picture.CoverFlow()
    fluxo.size_allocate(Graphene_rect_gdk(1280, 720), -1)
    fluxo.definir_jogos(jogos, 2)
    return fluxo, jogos


def Graphene_rect_gdk(largura, altura):
    from gi.repository import Gdk

    r = Gdk.Rectangle()
    r.x, r.y, r.width, r.height = 0, 0, largura, altura
    return r


def test_capa_em_acha_a_central_no_meio(cover_flow_5_jogos):
    fluxo, _ = cover_flow_5_jogos
    assert fluxo.capa_em(640, 360) == 2


def test_capa_em_acha_a_lateral_considerando_a_rotacao(cover_flow_5_jogos):
    fluxo, _ = cover_flow_5_jogos
    largura, altura = fluxo._medidas()
    area = fluxo._transformacao(3).transform_bounds(
        Graphene.Rect().init(0, 0, largura, altura)
    )
    x = area.get_x() + area.get_width() / 2
    y = area.get_y() + area.get_height() / 2
    assert fluxo.capa_em(x, y) == 3


def test_capa_em_fora_de_tudo_e_none(cover_flow_5_jogos):
    fluxo, _ = cover_flow_5_jogos
    assert fluxo.capa_em(5, 5) is None


def test_trocar_a_central_troca_o_motivo_de_animacao(cover_flow_5_jogos, schema):
    schema.set_boolean("cover-autoplay", True)
    fluxo, jogos = cover_flow_5_jogos
    fluxo.animar_para(3)
    fluxo._animacao.skip()
    assert jogos[3].game_cover._big_picture_active
    assert not jogos[2].game_cover._big_picture_active
    assert fluxo.posicao == 3


def test_sem_cover_autoplay_a_central_nao_anima(cover_flow_5_jogos, schema):
    schema.set_boolean("cover-autoplay", False)
    fluxo, jogos = cover_flow_5_jogos
    fluxo.animar_para(3)
    fluxo._animacao.skip()
    assert not jogos[3].game_cover._big_picture_active


def test_nova_animacao_recomeca_da_posicao_em_que_esta(cover_flow_5_jogos):
    fluxo, _ = cover_flow_5_jogos
    fluxo.animar_para(4)
    fluxo.posicao = 2.5
    fluxo.animar_para(0)
    assert fluxo._animacao.get_value_from() == 2.5
    assert fluxo._animacao.get_value_to() == 0


def _com_textura_grande(jogos):
    from pathlib import Path

    for j in jogos:
        capa = j.game_cover
        capa.path = Path("capa.png")
        capa._load_display_texture = lambda path, tamanho=None: object()


def test_so_a_central_estatica_ganha_a_textura_grande():
    jogos = [
        SimpleNamespace(game_cover=GameCover(set()), name=f"J{i}", developer="D")
        for i in range(5)
    ]
    _com_textura_grande(jogos)
    fluxo = big_picture.CoverFlow()
    fluxo.definir_jogos(jogos, 2)
    assert jogos[2].game_cover._textura_grande is not None
    assert fluxo._textura_de(2) is jogos[2].game_cover._textura_grande
    assert fluxo._textura_de(3) is not jogos[2].game_cover._textura_grande
    assert all(jogos[i].game_cover._textura_grande is None for i in (0, 1, 3, 4))


def test_new_cover_na_central_atualiza_a_textura_desenhada():
    jogos = [SimpleNamespace(game_cover=GameCover(set()), name="J", developer="D")]
    _com_textura_grande(jogos)
    capa = jogos[0].game_cover
    fluxo = big_picture.CoverFlow()
    fluxo.definir_jogos(jogos, 0)
    antiga = fluxo._textura_de(0)
    assert antiga is capa._textura_grande
    nova = GameCover.placeholder_small
    capa._load_display_texture = lambda path, tamanho=None: nova
    capa.new_cover(capa.path)
    assert fluxo._textura_de(0) is nova
    capa.new_cover(None)
    assert fluxo._textura_de(0) is GameCover.placeholder


def test_central_animada_nao_ganha_textura_grande():
    jogos = [SimpleNamespace(game_cover=GameCover(set()), name="J", developer="D")]
    _com_textura_grande(jogos)
    jogos[0].game_cover._animated_path = jogos[0].game_cover.path
    fluxo = big_picture.CoverFlow()
    fluxo.definir_jogos(jogos, 0)
    assert jogos[0].game_cover._textura_grande is None


def test_trocar_de_central_solta_a_textura_grande_anterior():
    jogos = [
        SimpleNamespace(game_cover=GameCover(set()), name=f"J{i}", developer="D")
        for i in range(3)
    ]
    _com_textura_grande(jogos)
    fluxo = big_picture.CoverFlow()
    fluxo.definir_jogos(jogos, 0)
    fluxo._trocar_central(1)
    assert jogos[0].game_cover._textura_grande is None
    assert jogos[1].game_cover._textura_grande is not None
    fluxo.do_unroot()
    assert jogos[1].game_cover._textura_grande is None


def _fluxo_com_jogos(quantos, indice):
    jogos = [
        SimpleNamespace(game_cover=GameCover(set()), name=f"J{i}", developer="D")
        for i in range(quantos)
    ]
    fluxo = big_picture.CoverFlow()
    fluxo.definir_jogos(jogos, indice)
    redesenhos = []
    fluxo.queue_draw = lambda: redesenhos.append(1)
    return fluxo, jogos, redesenhos


def test_capa_lateral_visivel_que_troca_a_textura_pede_redesenho():
    fluxo, jogos, redesenhos = _fluxo_com_jogos(30, 10)
    jogos[12].game_cover.set_texture(GameCover.placeholder_small)
    assert redesenhos


def test_capa_fora_da_tela_nao_pede_redesenho():
    fluxo, jogos, redesenhos = _fluxo_com_jogos(30, 10)
    assert not jogos[25].game_cover.pictures
    jogos[25].game_cover.set_texture(GameCover.placeholder_small)
    assert not redesenhos


def test_lateral_nova_nao_liga_animacao(monkeypatch):
    from cartridges.utils import tocador_capas

    chamadas = []

    class Espiao:
        def tocar(self, dono, *args, **kwargs):
            chamadas.append(("tocar", dono))

        def parar(self, dono):
            chamadas.append(("parar", dono))

        def posicao_ms(self, dono):
            return 0

    monkeypatch.setattr(tocador_capas, "tocador", Espiao())
    jogos = [
        SimpleNamespace(game_cover=GameCover(set()), name=f"J{i}", developer="D")
        for i in range(30)
    ]
    laterais = [j.game_cover for i, j in enumerate(jogos) if i != 10]
    for capa in laterais:
        capa._animated_path = Path("a.gif")
    fluxo = big_picture.CoverFlow()
    fluxo.definir_jogos(jogos, 10)
    fluxo.posicao = 12
    fluxo._trocar_central(12)
    donos_tocados = {d for nome, d in chamadas if nome == "tocar"}
    # A central pode tocar (depende de cover-autoplay); nenhuma lateral toca.
    central = jogos[12].game_cover
    assert all(capa is central or capa not in donos_tocados for capa in laterais)
    assert jogos[11].game_cover.pictures  # estava registrada, e não tocou


def _visiveis_ingenuo(fluxo):
    return sorted(
        (
            i
            for i in range(len(fluxo._jogos))
            if abs(i - fluxo._posicao) < big_picture.CAPAS_DE_CADA_LADO
        ),
        key=lambda i: abs(i - fluxo._posicao),
    )


@pytest.mark.parametrize("quantos", [0, 1, 5, 40])
def test_visiveis_igual_a_versao_ingenua(quantos):
    fluxo = big_picture.CoverFlow()
    fluxo._jogos = [None] * quantos
    for p in (0, 0.3, 0.5, 1, 7.5, 8, 8.2, 19.9, 20, quantos - 1, quantos - 0.5):
        fluxo._posicao = max(0, p) if quantos else 0
        assert fluxo._visiveis() == _visiveis_ingenuo(fluxo), (quantos, p)


def test_mover_o_carrossel_solta_as_capas_que_sairam_da_tela():
    fluxo, jogos, redesenhos = _fluxo_com_jogos(30, 10)
    assert jogos[3].game_cover.pictures
    fluxo.posicao = 20
    fluxo._trocar_central(20)
    assert not jogos[3].game_cover.pictures
    assert not jogos[10].game_cover.pictures
    assert jogos[25].game_cover.pictures
    redesenhos.clear()
    jogos[3].game_cover.set_texture(GameCover.placeholder_small)
    assert not redesenhos
    jogos[22].game_cover.set_texture(GameCover.placeholder_small)
    assert redesenhos


def test_unroot_e_definir_jogos_soltam_todas_as_capas():
    fluxo, jogos, _ = _fluxo_com_jogos(30, 10)
    fluxo.do_unroot()
    assert not any(j.game_cover.pictures for j in jogos)
    fluxo, jogos, _ = _fluxo_com_jogos(30, 10)
    fluxo.definir_jogos([], 0)
    assert not any(j.game_cover.pictures for j in jogos)


def test_capa_ilegivel_nao_e_decodificada_de_novo():
    from pathlib import Path

    capa = GameCover(set())
    capa.path = Path("capa.png")
    chamadas = []

    def falha(path, tamanho=None):
        chamadas.append(path)
        return None

    capa._load_display_texture = falha
    assert capa.textura_grande() is None
    assert capa.textura_grande() is None
    assert len(chamadas) == 1
    # Capa nova: vale tentar de novo.
    capa.new_cover(Path("outra.png"))
    chamadas.clear()
    assert capa.textura_grande() is None
    assert len(chamadas) == 1


def test_motivo_big_picture_entra_em_active():
    cover = GameCover(set())
    cover.set_big_picture_animation(True)
    assert cover.active
    cover.desligar_animacao()
    assert not cover._big_picture_active


# --- PaginaBigPicture: entrar, navegar, abrir o jogo, sair ----------------

class _Espiao:
    def __init__(self, devolve=True):
        self.chamadas = 0
        self.devolve = devolve
        self.efeito = None

    def __call__(self, *_args):
        self.chamadas += 1
        if self.efeito:
            self.efeito()
        return self.devolve


def _jogo_falso(game_id, last_played):
    return SimpleNamespace(
        game_id=game_id,
        name=game_id,
        developer="Desenvolvedora",
        last_played=last_played,
        removed=False,
        blacklisted=False,
        game_cover=GameCover(set()),
        launch=_Espiao(),
    )


@pytest.fixture
def jogos(monkeypatch):
    monkeypatch.setattr(restauracao, "e_pendente", lambda game_id: False)
    return [_jogo_falso("a", 10), _jogo_falso("b", 30), _jogo_falso("c", 20)]


class _JanelaFalsa(GObject.Object):
    """O que a página usa da janela; `is-active` é uma propriedade de verdade."""

    __gproperties__ = {
        "is-active": (bool, "is-active", "is-active", True, GObject.ParamFlags.READWRITE)
    }

    def do_get_property(self, pspec):
        return self.ativa

    def do_set_property(self, pspec, valor):
        self.ativa = valor

    @property
    def ativa(self):
        return self._ativa

    @ativa.setter
    def ativa(self, valor):
        if valor != self._ativa:
            self._ativa = valor
            self.notify("is-active")

    def __init__(self):
        self._ativa = True
        super().__init__()
        nav = Adw.NavigationView()
        nav.push(Adw.NavigationPage.new(Gtk.Label(), "Biblioteca"))
        self.navigation_view = nav
        self.fullscreen = _Espiao()
        self.unfullscreen = _Espiao()
        self.maximize = _Espiao()
        self.maximizada = False
        self.session_game = None
        self.session_overlay = Gtk.Overlay()

    def is_active(self):
        return self.ativa

    def is_maximized(self):
        return self.maximizada


@pytest.fixture
def janela():
    return _JanelaFalsa()


def _pagina(janela, jogos, monkeypatch):
    monkeypatch.setattr(shared, "store", jogos, raising=False)
    return big_picture.PaginaBigPicture(janela)


@pytest.fixture
def pagina(janela, jogos, monkeypatch):
    return _pagina(janela, jogos, monkeypatch)


@pytest.fixture
def pagina_vazia(janela, monkeypatch):
    return _pagina(janela, [], monkeypatch)


@pytest.fixture
def pagina_um_jogo(janela, jogos, monkeypatch):
    return _pagina(janela, jogos[:1], monkeypatch)


def concluir(pagina):
    for animacao in (pagina._animacao_abertura, pagina.cover_flow._animacao):
        if animacao is not None:
            animacao.skip()


def test_entrar_empilha_sem_animacao_e_pede_tela_cheia(pagina, janela):
    pagina.entrar()
    assert pagina.visivel and janela.fullscreen.chamadas == 1
    assert janela.navigation_view.get_animate_transitions()


def test_entrar_poe_o_ultimo_jogado_no_centro(pagina):
    pagina.entrar()
    assert pagina.carrossel.atual == "b"


def test_sair_desempilha_sai_da_tela_cheia_e_marca(pagina, janela):
    pagina.entrar()
    pagina.sair()
    assert not pagina.visivel and janela.unfullscreen.chamadas == 1
    assert pagina.ja_saiu


def test_maximizada_volta_maximizada_ao_sair(pagina, janela):
    janela.maximizada = True
    pagina.entrar()
    pagina.sair()
    assert janela.maximize.chamadas == 1


def test_nao_maximizada_nao_maximiza_ao_sair(pagina, janela):
    pagina.entrar()
    pagina.sair()
    assert janela.maximize.chamadas == 0


def test_maximizada_com_ida_e_volta_de_jogo_maximiza_uma_vez(pagina, jogos, janela):
    jogos[1].launch.efeito = lambda: setattr(janela, "session_game", jogos[1])
    janela.maximizada = True
    pagina.entrar()
    janela.maximizada = False  # a janela em tela cheia não conta como maximizada
    pagina.abrir_jogo()
    concluir(pagina)
    pagina.voltou_do_jogo()
    concluir(pagina)
    pagina.sair()
    assert janela.maximize.chamadas == 1


def test_dois_a_seguidos_abrem_o_jogo_uma_vez(pagina, jogos, janela):
    # Sem sessão a animação (síncrona nos testes) já devolveria a página ao
    # normal; com sessão ela fica ocupada, como no uso real.
    jogos[1].launch.efeito = lambda: setattr(janela, "session_game", jogos[1])
    pagina.entrar()
    pagina.abrir_jogo()
    pagina.abrir_jogo()
    concluir(pagina)
    assert jogos[1].launch.chamadas == 1


def test_launch_recusado_volta_ao_normal(pagina, jogos, janela):
    jogos[1].launch.devolve = False
    pagina.entrar()
    pagina.abrir_jogo()
    concluir(pagina)
    assert not pagina.ocupada and pagina.cover_flow.progresso_abertura == 0
    assert janela.fullscreen.chamadas == 2


def test_sem_sessao_volta_sozinho(pagina, janela):
    pagina.entrar()
    pagina.abrir_jogo()
    concluir(pagina)
    assert not pagina.ocupada and janela.fullscreen.chamadas == 2


def test_com_sessao_espera_o_fim_dela(pagina, janela, jogos):
    jogos[1].launch.efeito = lambda: setattr(janela, "session_game", jogos[1])
    pagina.entrar()
    pagina.abrir_jogo()
    concluir(pagina)
    assert pagina.ocupada
    pagina.voltou_do_jogo()
    concluir(pagina)
    assert not pagina.ocupada and pagina.cover_flow.progresso_abertura == 0


def test_voltou_do_jogo_devolve_o_foco_a_pagina(pagina, jogos, janela, monkeypatch):
    jogos[1].launch.efeito = lambda: setattr(janela, "session_game", jogos[1])
    pagina.entrar()
    pagina.abrir_jogo()
    concluir(pagina)
    foco = _Espiao()
    monkeypatch.setattr(pagina, "grab_focus", foco)
    pagina.voltou_do_jogo()
    assert foco.chamadas == 1


def test_entrada_ignorada_enquanto_ocupada(pagina):
    pagina.entrar()
    pagina.ocupada = True
    assert not pagina.mover(1) and not pagina.inicio() and not pagina.fim()
    pagina.sair()
    assert pagina.visivel and pagina.carrossel.atual == "b"


def test_atualizar_quando_o_central_some_cai_no_vizinho(pagina, jogos):
    pagina.entrar()
    pagina.mover(1)
    assert pagina.carrossel.atual == "c"
    jogos[2].removed = True
    pagina.atualizar()
    assert pagina.carrossel.atual == "a"


def test_lista_vazia_mostra_aviso_e_a_nao_faz_nada(pagina_vazia):
    pagina_vazia.entrar()
    pagina_vazia.abrir_jogo()
    assert pagina_vazia.vazio.get_visible() and not pagina_vazia.ocupada
    pagina_vazia.sair()
    assert not pagina_vazia.visivel


def test_um_jogo_so_nao_move(pagina_um_jogo):
    pagina_um_jogo.entrar()
    assert not pagina_um_jogo.mover(1) and not pagina_um_jogo.mover(-1)


def test_rotulos_mostram_o_central(pagina):
    pagina.entrar()
    assert pagina.rotulo_nome.get_label() == "b"
    pagina.mover(1)
    assert pagina.rotulo_nome.get_label() == "c"


def test_pagina_nao_desempilha_por_fora_de_sair(pagina):
    assert not pagina.get_can_pop()


def test_atualizar_fora_da_tela_nao_liga_animacao_da_capa(pagina, jogos, schema):
    schema.set_boolean("cover-autoplay", True)
    pagina.atualizar()
    assert not any(j.game_cover._big_picture_active for j in jogos)


def test_dois_a_seguidos_na_janela_da_animacao(pagina, jogos, monkeypatch):
    guardados = []
    monkeypatch.setattr(
        pagina, "_animar_abertura", lambda de, para, ao_fim=None: guardados.append(ao_fim)
    )
    pagina.entrar()
    pagina.abrir_jogo()
    pagina.abrir_jogo()
    guardados[0]()
    assert jogos[1].launch.chamadas == 1


def test_voltou_do_jogo_sem_estar_ocupada_nao_faz_nada(pagina, janela):
    pagina.entrar()
    pagina.voltou_do_jogo()
    assert janela.fullscreen.chamadas == 1


def test_launch_que_levanta_volta_ao_normal_e_propaga(
    pagina, jogos, janela, monkeypatch
):
    # A exceção sai de um handler de sinal: o PyGObject a entrega ao excepthook
    # (é o caminho do log), não ao chamador de abrir_jogo.
    levantadas = []
    monkeypatch.setattr(sys, "excepthook", lambda tipo, *_: levantadas.append(tipo))
    def estoura():
        raise RuntimeError("falhou")

    jogos[1].launch.efeito = estoura
    pagina.entrar()
    pagina.abrir_jogo()
    concluir(pagina)
    assert levantadas == [RuntimeError]
    assert not pagina.ocupada and pagina.cover_flow.progresso_abertura == 0
    assert janela.fullscreen.chamadas == 2


def _abrir_sem_sessao(pagina, schema, minimiza=True):
    schema.set_boolean("minimize-after-launch", minimiza)
    pagina.entrar()
    pagina.abrir_jogo()
    concluir(pagina)


def test_sem_sessao_minimizando_espera_a_janela_ativar(pagina, janela, schema):
    # is_active() ainda diz True (o WM_ACTIVATE não foi processado): não vale.
    _abrir_sem_sessao(pagina, schema)
    assert not pagina.ocupada and pagina.cover_flow.progresso_abertura == 0
    assert janela.fullscreen.chamadas == 1


def test_sem_sessao_tela_cheia_volta_quando_a_janela_fica_ativa(
    pagina, janela, schema
):
    _abrir_sem_sessao(pagina, schema)
    janela.ativa = False
    janela.ativa = True
    assert janela.fullscreen.chamadas == 2
    janela.ativa = False
    janela.ativa = True
    assert janela.fullscreen.chamadas == 2  # desconectou


def test_sem_sessao_sem_minimizar_poe_tela_cheia_na_hora(pagina, janela, schema):
    _abrir_sem_sessao(pagina, schema, minimiza=False)
    assert janela.fullscreen.chamadas == 2


def test_pagina_fora_da_tela_nao_ganha_tela_cheia_ao_ativar(pagina, janela, schema):
    _abrir_sem_sessao(pagina, schema)
    pagina.sair()
    janela.ativa = False
    janela.ativa = True
    assert janela.fullscreen.chamadas == 1


def test_duas_aberturas_sem_ativacao_dao_uma_tela_cheia(pagina, janela, schema):
    _abrir_sem_sessao(pagina, schema)
    pagina.abrir_jogo()
    concluir(pagina)
    janela.ativa = False
    janela.ativa = True
    assert janela.fullscreen.chamadas == 2


# --- janela: entrada automática ao conectar o controle ---


def _janela_falsa(*, pagina_visivel="biblioteca", dialogo=None, bloqueio=False, ja_saiu=False):
    from cartridges.window import CartridgesWindow

    chamadas = []
    biblioteca = object()
    outra = object()
    falsa = SimpleNamespace(
        library_page=biblioteca,
        navigation_view=SimpleNamespace(
            get_visible_page=lambda: biblioteca if pagina_visivel == "biblioteca" else outra
        ),
        get_visible_dialog=lambda: dialogo,
        session_blocker=SimpleNamespace(get_visible=lambda: bloqueio),
        pagina_big_picture=SimpleNamespace(
            entrar=lambda: chamadas.append("entrar"), ja_saiu=ja_saiu
        ),
    )
    return CartridgesWindow, falsa, chamadas


@pytest.mark.parametrize(
    "opcoes, preferencia, entra",
    [
        ({}, True, True),
        ({}, False, False),
        ({"ja_saiu": True}, True, False),
        ({"pagina_visivel": "detalhes"}, True, False),
        ({"dialogo": object()}, True, False),
        ({"bloqueio": True}, True, False),
    ],
)
def test_controle_conectado_entra_so_com_tudo_permitindo(
    monkeypatch, schema, opcoes, preferencia, entra
):
    classe, falsa, chamadas = _janela_falsa(**opcoes)
    schema.set_boolean("big-picture-ao-conectar", preferencia)
    schema.set_boolean("gamepad", True)
    monkeypatch.setattr(big_picture, "tem_3d", lambda _janela: True)
    classe.on_controle_conectado(falsa)
    assert chamadas == (["entrar"] if entra else [])


def test_fechar_em_tela_cheia_nao_grava_a_geometria(monkeypatch, state_schema):
    from cartridges import main as main_module
    from cartridges.utils import window_geometry

    def nao_le(*_args):
        raise AssertionError("não se lê a geometria de uma janela em tela cheia")

    monkeypatch.setattr(window_geometry, "session_geometry", nao_le)
    monkeypatch.setattr(window_geometry, "read", nao_le)
    monkeypatch.setattr(
        shared, "win", SimpleNamespace(is_fullscreen=lambda: True), raising=False
    )
    antes = dict(state_schema._values)
    assert main_module.CartridgesApplication.save_window_geometry(object()) is False
    assert state_schema._values == antes


# --- Fundo com degradê pontilhado -----------------------------------------


def test_fundo_tem_o_tamanho_certo():
    assert len(big_picture.bytes_do_fundo(64, 32)) == 64 * 32 * 3


def test_fundo_topo_e_base():
    b = big_picture.bytes_do_fundo(64, 100)
    topo = b[: 64 * 3]
    base = b[-64 * 3 :]
    assert all(abs(v - a) <= 1 for v, a in zip(topo, (28, 28, 30) * 64))
    assert max(base) <= 1


def test_pontilhado_nunca_passa_de_um_tom():
    w, h = 128, 256
    b = big_picture.bytes_do_fundo(w, h)
    for y in range(h):
        k = (1 - y / (h - 1)) ** 1.6
        exatos = (28 * k, 28 * k, 30 * k)
        for x in range(0, w, 7):
            for c in range(3):
                assert abs(b[(y * w + x) * 3 + c] - exatos[c]) < 1.0 + 1e-9


def test_linha_8_abaixo_nunca_e_mais_clara():
    w, h = 64, 300
    b = big_picture.bytes_do_fundo(w, h)
    for y in range(h - 8):
        for i in range(w * 3):
            assert b[(y + 8) * w * 3 + i] <= b[y * w * 3 + i]


def test_limiares_sem_padrao_de_hachura():
    m = big_picture._LIMIARES
    assert not any(m[1] == m[0][k:] + m[0][:k] for k in range(8))
    por_xor = {}
    for y in range(8):
        for x in range(8):
            por_xor.setdefault(x ^ y, set()).add(m[y][x])
    assert any(len(v) > 1 for v in por_xor.values())


def test_fundo_rapido():
    inicio = time.perf_counter()
    big_picture.bytes_do_fundo(2560, 1440)
    assert time.perf_counter() - inicio < 0.1


def test_fundo_usa_pixels_reais(monkeypatch):
    pedidos = []
    original = big_picture.bytes_do_fundo
    monkeypatch.setattr(
        big_picture,
        "bytes_do_fundo",
        lambda w, h: pedidos.append((w, h)) or original(w, h),
    )
    fluxo = big_picture.CoverFlow()
    monkeypatch.setattr(fluxo, "get_width", lambda: 800)
    monkeypatch.setattr(fluxo, "get_height", lambda: 600)
    monkeypatch.setattr(fluxo, "_escala", lambda: 1.5)
    textura = fluxo._textura_do_fundo()
    assert pedidos == [(1200, 900)]
    assert (textura.get_width(), textura.get_height()) == (1200, 900)
    # Mesmo tamanho: reaproveita a textura, não gera outra.
    assert fluxo._textura_do_fundo() is textura
    assert pedidos == [(1200, 900)]


def test_fundo_com_falha_nao_levanta(monkeypatch):
    def quebra(w, h):
        raise MemoryError

    monkeypatch.setattr(big_picture, "bytes_do_fundo", quebra)
    fluxo = big_picture.CoverFlow()
    monkeypatch.setattr(fluxo, "get_width", lambda: 100)
    monkeypatch.setattr(fluxo, "get_height", lambda: 100)
    assert fluxo._textura_do_fundo() is None


class _SnapshotFalso:
    def __init__(self):
        self.texturas = []

    def append_scaled_texture(self, textura, *_):
        self.texturas.append(textura)

    def __getattr__(self, nome):
        return lambda *a, **k: None


def _fluxo_com_fundo(monkeypatch, fundo):
    fluxo = big_picture.CoverFlow()
    monkeypatch.setattr(fluxo, "get_width", lambda: 800)
    monkeypatch.setattr(fluxo, "get_height", lambda: 600)
    monkeypatch.setattr(fluxo, "_textura_do_fundo", lambda: fundo)
    fluxo._jogos = [SimpleNamespace(game_cover=GameCover(set()))]
    fluxo._central = 0
    return fluxo


def test_fundo_e_desenhado_antes_das_capas(monkeypatch):
    fundo = object()
    fluxo = _fluxo_com_fundo(monkeypatch, fundo)
    snap = _SnapshotFalso()
    fluxo.do_snapshot(snap)
    assert len(snap.texturas) > 1
    assert snap.texturas[0] is fundo
    assert all(t is not fundo for t in snap.texturas[1:])


def test_sem_fundo_nada_de_fundo_e_desenhado(monkeypatch):
    fluxo = _fluxo_com_fundo(monkeypatch, None)
    snap = _SnapshotFalso()
    fluxo.do_snapshot(snap)
    assert snap.texturas and None not in snap.texturas


# --- Arranjo da fila (virada e opacidade das capas) -------------------------


def test_virada_1_nao_muda_nada(cover_flow_5_jogos):
    fluxo, _ = cover_flow_5_jogos
    largura, _ = fluxo._medidas()
    # Arranjo normal: a central de frente, as laterais de perfil e recuadas.
    assert fluxo.virada == 1.0
    assert fluxo._arranjo(2) == (0.0, 0.0, 0.0)
    x, angulo, profundidade = fluxo._arranjo(4)
    assert x == pytest.approx(
        largura * (big_picture.ESPACO_CENTRAL + big_picture.ESPACO_LATERAL)
    )
    assert angulo == -big_picture.ANGULO_LATERAL
    assert profundidade == -big_picture.PROFUNDIDADE_LATERAL
    assert fluxo._arranjo(0)[1] == big_picture.ANGULO_LATERAL


def test_virada_0_todas_de_perfil(cover_flow_5_jogos):
    fluxo, _ = cover_flow_5_jogos
    fluxo.virada = 0.0
    for i in range(5):
        _, angulo, profundidade = fluxo._arranjo(i)
        assert angulo == -big_picture.ANGULO_LATERAL
        assert profundidade == -big_picture.PROFUNDIDADE_LATERAL


def test_virada_0_espacamento_uniforme(cover_flow_5_jogos):
    fluxo, _ = cover_flow_5_jogos
    fluxo.virada = 0.0
    largura, altura = fluxo._medidas()
    retangulo = Graphene.Rect().init(0, 0, largura, altura)
    centros = []
    for i in range(5):
        area = fluxo._transformacao(i).transform_bounds(retangulo)
        centros.append(area.get_x() + area.get_width() / 2)
    passos = [b - a for a, b in zip(centros, centros[1:])]
    assert all(p == pytest.approx(passos[0], rel=1e-3) for p in passos)
    assert passos[0] > 0


def test_opacidade_capas_pede_redesenho(cover_flow_5_jogos, monkeypatch):
    fluxo, _ = cover_flow_5_jogos
    pedidos = []
    monkeypatch.setattr(fluxo, "queue_draw", lambda: pedidos.append(1))
    fluxo.opacidade_capas = 0.5
    fluxo.virada = 0.3
    assert fluxo.opacidade_capas == 0.5 and len(pedidos) == 2


def test_transformacao_com_virada_1_igual_a_formula_antiga(cover_flow_5_jogos):
    fluxo, _ = cover_flow_5_jogos
    fluxo.posicao = 1.4
    fluxo.virada = 1
    largura, altura = fluxo._medidas()
    for i in (0, 1, 2, 3, 4):
        d = i - 1.4
        a = min(abs(d), 1.0)
        lado = math.copysign(1, d)
        if abs(d) <= 1:
            x = d * largura * big_picture.ESPACO_CENTRAL
        else:
            x = lado * (
                largura * big_picture.ESPACO_CENTRAL
                + (abs(d) - 1) * largura * big_picture.ESPACO_LATERAL
            )
        t = Gsk.Transform()
        t = t.translate(
            Graphene.Point().init(fluxo.get_width() / 2, fluxo.get_height() * 0.40)
        )
        t = t.perspective(big_picture.PERSPECTIVA)
        t = t.translate_3d(
            Graphene.Point3D().init(x, 0, -a * big_picture.PROFUNDIDADE_LATERAL)
        )
        t = t.rotate_3d(-lado * a * big_picture.ANGULO_LATERAL, Graphene.Vec3.y_axis())
        t = t.scale(1, 1)
        t = t.translate(Graphene.Point().init(-largura / 2, -altura / 2))
        esperada = t.to_matrix().to_float()
        obtida = fluxo._transformacao(i).to_matrix().to_float()
        assert list(obtida) == pytest.approx(list(esperada))


# --- Animação da fila na página ---------------------------------------------


def test_quadro_entrada_comeco_e_fim():
    assert big_picture.quadro_da_fila(0.0, 30, 0) == pytest.approx((30, 0.0, 0.0, 0.0))
    assert big_picture.quadro_da_fila(1.0, 30, 0) == pytest.approx((0, 1.0, 1.0, 1.0))


def test_quadro_virada_ultrapassa():
    assert max(big_picture.quadro_da_fila(t / 100, 30, 0)[1] for t in range(100)) > 1.0


def test_quadro_saida_parte_da_capa_atual():
    assert big_picture.quadro_da_fila(1.0, 30, 10)[0] == pytest.approx(10)


def test_quadro_um_jogo():
    for t in (0.0, 0.3, 0.7, 1.0):
        assert big_picture.quadro_da_fila(t, 0, 0)[0] == 0


@pytest.fixture
def fila_parada(monkeypatch):
    """A animação da fila não toca sozinha: o teste a conclui com `concluir_fila`."""
    monkeypatch.setattr(Adw.TimedAnimation, "play", lambda self: None)


def concluir_fila(pagina):
    pagina._animacao_fila.skip()


def test_entrada_ignora_esc_a_e_setas(pagina, fila_parada):
    pagina.entrar()
    assert pagina.ocupada
    pagina.sair()
    pagina.abrir_jogo()
    assert not pagina.mover(1) and not pagina.fim()
    assert pagina.visivel and pagina.carrossel.atual == "b"
    assert pagina._jogo_aberto is None


def test_entrada_termina_no_estado_normal(pagina, fila_parada):
    pagina.entrar()
    assert pagina.cover_flow.virada == 0.0 and pagina.cover_flow.opacidade_capas == 0.0
    concluir_fila(pagina)
    assert not pagina.ocupada
    assert pagina.cover_flow.virada == 1.0 and pagina.cover_flow.opacidade_capas == 1.0
    assert pagina.cover_flow.posicao == 0 and pagina.rodape.get_opacity() == 1.0


def test_saida_comeca_na_capa_atual(pagina, fila_parada):
    pagina.entrar()
    concluir_fila(pagina)
    pagina.ir_para(2)
    pagina.cover_flow._animacao.skip()
    pagina.sair()
    assert pagina.cover_flow.posicao == 2 and pagina.ocupada


def test_saida_no_meio_do_passo_parte_da_posicao_visual(pagina, fila_parada):
    pagina.entrar()
    concluir_fila(pagina)
    pagina.mover(1)
    pagina.cover_flow.posicao = 0.4  # o passo corre; a posição visual é fracionária
    animacao_do_passo = pagina.cover_flow._animacao
    pagina.sair()
    assert pagina.cover_flow._animacao is None and animacao_do_passo is not None
    assert pagina.cover_flow.posicao == pytest.approx(0.4)


def test_saida_termina_desempilhando(pagina, janela, fila_parada):
    pagina.entrar()
    concluir_fila(pagina)
    pagina.sair()
    assert pagina.visivel and janela.unfullscreen.chamadas == 0
    concluir_fila(pagina)
    assert not pagina.visivel and janela.unfullscreen.chamadas == 1
    assert pagina.ja_saiu and not pagina.ocupada


def test_atualizar_durante_a_animacao_fica_pendente(pagina, jogos, fila_parada):
    pagina.entrar()
    posicao = pagina.cover_flow.posicao
    jogos[0].removed = True
    pagina.atualizar()
    assert pagina.cover_flow.posicao == posicao
    assert len(pagina._jogos) == 3
    concluir_fila(pagina)
    assert len(pagina._jogos) == 2


def test_atualizar_pendente_guarda_so_o_ultimo_centro(pagina, fila_parada):
    pagina.entrar()
    pagina.atualizar("a")
    pagina.atualizar("c")
    concluir_fila(pagina)
    assert pagina.carrossel.atual == "c"


def test_atualizar_pendente_some_se_a_pagina_saiu(pagina, jogos, fila_parada):
    pagina.entrar()
    concluir_fila(pagina)
    pagina.sair()
    jogos[0].removed = True
    pagina.atualizar()
    concluir_fila(pagina)
    assert not pagina.visivel and len(pagina._jogos) == 3


def test_biblioteca_vazia_entra_sem_fila(pagina_vazia, janela):
    pagina_vazia.entrar()
    assert not pagina_vazia.ocupada and pagina_vazia.visivel
    pagina_vazia.sair()
    assert not pagina_vazia.visivel and janela.unfullscreen.chamadas == 1


# --- fade do monitor (cortina) ---
class _CortinaFalsa:
    """Registra a sequência do fade numa lista compartilhada."""

    registro: list = []
    falha = False

    def __init__(self, hwnd):
        if _CortinaFalsa.falha:
            raise OSError("sem cortina")
        _CortinaFalsa.registro.append(f"abriu {hwnd}")

    def alfa(self, valor):
        _CortinaFalsa.registro.append(f"alfa {round(valor)}")

    def fechar(self):
        _CortinaFalsa.registro.append("fechou")


@pytest.fixture
def fade(monkeypatch, fila_parada):
    """Cortina falsa, HWND falso e a pausa de 120 ms disparada à mão."""
    _CortinaFalsa.registro = []
    _CortinaFalsa.falha = False
    pausas = []
    monkeypatch.setattr(big_picture.PaginaBigPicture, "_fabrica_cortina", _CortinaFalsa)
    monkeypatch.setattr(big_picture.janela_por_cima, "handle", lambda janela: 42)
    monkeypatch.setattr(
        big_picture.GLib, "timeout_add", lambda ms, f: pausas.append((ms, f)) or len(pausas)
    )
    monkeypatch.setattr(big_picture.GLib, "source_remove", lambda _id: pausas.clear())
    return SimpleNamespace(registro=_CortinaFalsa.registro, pausas=pausas, classe=_CortinaFalsa)


def concluir_cortina(pagina):
    pagina._animacao_cortina.skip()


def test_entrar_escurece_troca_e_clareia(pagina, janela, fade):
    pagina.entrar()
    assert fade.registro == ["abriu 42", "alfa 0"] and pagina.ocupada
    assert not pagina.visivel
    concluir_cortina(pagina)
    assert pagina.visivel and fade.registro[-1] == "alfa 1" and janela.fullscreen.chamadas == 1
    assert [ms for ms, _ in fade.pausas] == [120]
    fade.pausas[0][1]()
    concluir_cortina(pagina)
    assert fade.registro[-2:] == ["alfa 0", "fechou"] and pagina._cortina is None
    assert pagina.ocupada  # a fila ainda corre
    concluir_fila(pagina)
    assert not pagina.ocupada


def test_entrar_fica_ocupada_ate_o_fim_do_fade_sem_fila(pagina_vazia, fade):
    pagina_vazia.entrar()
    concluir_cortina(pagina_vazia)
    assert pagina_vazia.ocupada
    fade.pausas[0][1]()
    concluir_cortina(pagina_vazia)
    assert not pagina_vazia.ocupada


def test_entrar_com_a_pagina_visivel_nao_faz_nada(pagina, janela, fade):
    pagina.entrar()
    concluir_cortina(pagina)
    fade.pausas[0][1]()
    concluir_cortina(pagina)
    concluir_fila(pagina)
    antes = list(fade.registro)
    pagina.entrar()
    assert fade.registro == antes and janela.fullscreen.chamadas == 1


def test_sair_faz_a_fila_e_depois_o_fade(pagina, janela, fade):
    pagina.entrar()
    concluir_cortina(pagina)
    fade.pausas[0][1]()
    concluir_cortina(pagina)
    concluir_fila(pagina)
    fade.registro.clear()
    pagina.sair()
    assert fade.registro == [] and pagina.ocupada  # primeiro a fila
    concluir_fila(pagina)
    assert fade.registro == ["abriu 42", "alfa 0"] and pagina.visivel
    # escurecendo: o carrossel não pode reaparecer
    assert pagina.cover_flow.opacidade_capas == 0.0 and pagina.rodape.get_opacity() == 0.0
    assert pagina.ocupada and not pagina.mover(1)
    concluir_cortina(pagina)
    assert not pagina.visivel and janela.unfullscreen.chamadas == 1 and pagina.ocupada
    fade.pausas[0][1]()
    concluir_cortina(pagina)
    assert fade.registro[-1] == "fechou" and not pagina.ocupada and pagina.ja_saiu
    assert pagina.cover_flow.opacidade_capas == 1.0


def test_sem_hwnd_troca_sem_fade(pagina, janela, fade, monkeypatch):
    monkeypatch.setattr(big_picture.janela_por_cima, "handle", lambda janela: None)
    pagina.entrar()
    assert pagina.visivel and fade.registro == []
    concluir_fila(pagina)
    pagina.sair()
    concluir_fila(pagina)
    assert not pagina.visivel and not pagina.ocupada and fade.registro == []


def test_cortina_que_falha_troca_sem_fade(pagina, fade):
    fade.classe.falha = True
    pagina.entrar()
    assert pagina.visivel and pagina._cortina is None
    concluir_fila(pagina)
    pagina.sair()
    concluir_fila(pagina)
    assert not pagina.visivel and not pagina.ocupada


def test_pagina_fora_da_arvore_no_meio_do_fade_fecha_a_cortina(pagina, janela, fade):
    pagina.entrar()
    concluir_cortina(pagina)
    assert pagina._cortina is not None
    pagina.do_unroot()
    assert fade.registro[-1] == "fechou" and pagina._cortina is None and not fade.pausas


def test_animacao_da_cortina_nao_e_presa_a_pagina(pagina, janela, fade):
    pagina.entrar()
    dono = pagina._animacao_cortina.get_widget()
    assert dono is not pagina and dono.get_parent() is janela.session_overlay


def test_entrar_durante_a_pausa_da_saida_nao_cria_outra_cortina(pagina, janela, fade):
    pagina.entrar()
    concluir_cortina(pagina)
    fade.pausas[0][1]()
    concluir_cortina(pagina)
    concluir_fila(pagina)
    pagina.sair()
    concluir_fila(pagina)
    concluir_cortina(pagina)
    assert fade.pausas  # na pausa de 120 ms, com a página já desempilhada
    abertas = fade.registro.count("abriu 42")
    pagina.entrar()
    assert fade.registro.count("abriu 42") == abertas and not pagina.visivel
    fade.pausas[0][1]()
    concluir_cortina(pagina)
    assert fade.registro[-1] == "fechou" and not pagina.ocupada


def test_entrar_duas_vezes_no_escurecimento_cria_uma_cortina(pagina, fade):
    pagina.entrar()
    pagina.entrar()
    assert fade.registro.count("abriu 42") == 1


def test_nova_sequencia_fecha_a_cortina_anterior(pagina, fade):
    pagina.entrar()
    pagina._trocar_no_escuro(lambda: None, 100, None)
    assert fade.registro.count("fechou") == 1 and fade.registro.count("abriu 42") == 2


def test_cortina_que_levanta_qualquer_erro_troca_sem_fade(pagina, fade, monkeypatch):
    def explode(hwnd):
        raise RuntimeError("x")

    monkeypatch.setattr(big_picture.PaginaBigPicture, "_fabrica_cortina", explode)
    pagina.entrar()
    assert pagina.visivel


def test_unroot_no_meio_do_fade_destrava_a_pagina(pagina, fade):
    pagina.entrar()
    concluir_cortina(pagina)
    pagina.do_unroot()
    assert not pagina.ocupada and not pagina._em_fade and not pagina._saindo


def test_troca_que_levanta_sem_cortina_destrava_a_pagina(pagina, fade, monkeypatch):
    monkeypatch.setattr(big_picture.janela_por_cima, "handle", lambda janela: None)
    depois = []
    with pytest.raises(RuntimeError):
        pagina._trocar_no_escuro(
            lambda: (_ for _ in ()).throw(RuntimeError("x")), 300, lambda: depois.append(1)
        )
    assert depois == [1]
    pagina.ocupada = True
    pagina._fim_da_entrada()
    assert not pagina.ocupada
    pagina.entrar()
    assert pagina.visivel


def test_sair_repoe_o_quadro_mesmo_se_a_troca_falhar(pagina, fade, monkeypatch):
    pagina.cover_flow.opacidade_capas = 0.0
    monkeypatch.setattr(
        pagina, "_trocar_ao_sair", lambda: (_ for _ in ()).throw(RuntimeError("x"))
    )
    with pytest.raises(RuntimeError):
        pagina._sair_de_fato()
    assert pagina.cover_flow.opacidade_capas == 1.0


def test_esconder_e_mostrar_ponteiro(monkeypatch):
    from cartridges import window
    from cartridges.window import CartridgesWindow

    monkeypatch.setattr(window, "_posicao_do_ponteiro", lambda: None)

    cursores = []
    falsa = SimpleNamespace(
        _ponteiro_escondido=False,
        _ultima_posicao_ponteiro=None,
        set_cursor_from_name=lambda nome: cursores.append(nome),
        set_cursor=lambda c: cursores.append(c),
    )
    mover = CartridgesWindow._ao_mover_ponteiro
    mover(falsa, None, 10, 10)  # já visível: nada a fazer
    assert cursores == []
    CartridgesWindow.esconder_ponteiro(falsa)
    assert cursores == ["none"]
    mover(falsa, None, 10, 10)  # reemissão na mesma posição
    mover(falsa, None, 11, 10)  # 1 px de folga
    assert cursores == ["none"]
    mover(falsa, None, 10, 30)
    assert cursores == ["none", None]
    mover(falsa, None, 10, 50)  # já visível: não repete
    assert cursores == ["none", None]


# --- tique ao trocar de capa ---
class _Tiques(list):
    relogio = None


@pytest.fixture(autouse=True)
def tiques(monkeypatch, schema):
    """Registra os tiques sem tocar de verdade; a thread roda direto e o relógio é controlado."""
    tocados = _Tiques()
    monkeypatch.setattr(
        big_picture.winsound, "PlaySound", lambda dados, flags: tocados.append((dados, flags))
    )
    monkeypatch.setattr(
        big_picture.threading,
        "Thread",
        lambda target, args=(), daemon=None: SimpleNamespace(start=lambda: target(*args)),
    )
    monkeypatch.setattr(big_picture, "_ultimo_tique", -1000.0)
    agora = [100.0]
    monkeypatch.setattr(big_picture.time, "monotonic", lambda: agora[0])
    tocados.relogio = agora
    return tocados


def test_troca_de_capa_toca(pagina, tiques):
    pagina.entrar()
    concluir(pagina)
    tiques.clear()
    assert pagina.mover(1)
    assert len(tiques) == 1
    dados, flags = tiques[0]
    assert dados[:4] == b"RIFF"
    assert flags == big_picture.winsound.SND_MEMORY | big_picture.winsound.SND_NODEFAULT


def test_duas_trocas_em_menos_de_70ms_tocam_uma_vez(pagina, tiques):
    pagina.entrar()
    concluir(pagina)
    tiques.clear()
    pagina.mover(1)
    tiques.relogio[0] += 0.069
    concluir(pagina)
    pagina.mover(-1)
    assert len(tiques) == 1
    tiques.relogio[0] += 0.001
    concluir(pagina)
    pagina.mover(1)
    assert len(tiques) == 2


def test_preferencia_desligada_nao_toca(pagina, tiques, schema):
    schema.set_boolean("big-picture-som", False)
    pagina.entrar()
    concluir(pagina)
    pagina.mover(1)
    assert tiques == []


def test_animacao_de_entrada_nao_toca(pagina, tiques):
    pagina.entrar()
    concluir(pagina)
    pagina.sair()
    concluir(pagina)
    assert tiques == []


def test_falha_ao_tocar_nao_levanta(pagina, tiques, monkeypatch):
    def falha(*_args):
        raise RuntimeError("sem placa de som")

    monkeypatch.setattr(big_picture.winsound, "PlaySound", falha)
    pagina.entrar()
    concluir(pagina)
    assert pagina.mover(1)


def test_som_e_o_aprovado():
    from gi.repository import Gio  # noqa: PLC0415

    embutido = Gio.resources_lookup_data(
        shared.PREFIX + "/sons/tique.wav", Gio.ResourceLookupFlags.NONE
    ).get_data()
    assert embutido == (Path(__file__).parent.parent / "data" / "sons" / "tique.wav").read_bytes()


def _falsa_ponteiro(monkeypatch, tela):
    from cartridges import window  # noqa: PLC0415

    cursores = []
    falsa = SimpleNamespace(
        _ponteiro_escondido=False,
        _ultima_posicao_ponteiro=None,
        set_cursor_from_name=lambda nome: cursores.append(nome),
        set_cursor=lambda c: cursores.append(c),
    )
    monkeypatch.setattr(window, "_posicao_do_ponteiro", lambda: tela[0])
    return falsa, cursores


def test_ponteiro_usa_a_posicao_de_tela(monkeypatch):
    from cartridges.window import CartridgesWindow  # noqa: PLC0415

    tela = [(500, 400)]
    falsa, cursores = _falsa_ponteiro(monkeypatch, tela)
    CartridgesWindow._ao_mover_ponteiro(falsa, None, 10, 10)
    CartridgesWindow.esconder_ponteiro(falsa)
    # a origem da janela mudou (tela cheia): coordenadas locais diferentes, mouse parado
    CartridgesWindow._ao_mover_ponteiro(falsa, None, 80, 90)
    assert cursores == ["none"]
    tela[0] = (520, 400)
    CartridgesWindow._ao_mover_ponteiro(falsa, None, 100, 90)
    assert cursores == ["none", None]


def test_ponteiro_sem_posicao_de_tela_usa_as_coordenadas_locais(monkeypatch):
    from cartridges.window import CartridgesWindow  # noqa: PLC0415

    falsa, cursores = _falsa_ponteiro(monkeypatch, [None])
    CartridgesWindow._ao_mover_ponteiro(falsa, None, 10, 10)
    CartridgesWindow.esconder_ponteiro(falsa)
    CartridgesWindow._ao_mover_ponteiro(falsa, None, 10, 10)
    assert cursores == ["none"]
    CartridgesWindow._ao_mover_ponteiro(falsa, None, 10, 30)
    assert cursores == ["none", None]


def test_esconder_ponteiro_ja_escondido_nao_repete():
    from cartridges.window import CartridgesWindow  # noqa: PLC0415

    cursores = []
    falsa = SimpleNamespace(
        _ponteiro_escondido=True, set_cursor_from_name=lambda nome: cursores.append(nome)
    )
    CartridgesWindow.esconder_ponteiro(falsa)
    assert cursores == []
