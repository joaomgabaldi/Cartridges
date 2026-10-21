# big_picture.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Big Picture: modo de tela cheia, feito para controle, com os jogos em Cover Flow.

Este módulo guarda a lógica pura (quais jogos entram, quando o modo abre sozinho,
o ritmo da repetição ao segurar a direção e o carrossel), o widget `CoverFlow`
que desenha as capas e a `PaginaBigPicture`, que junta tudo e trata a entrada.
Spec: docs/superpowers/specs/2026-10-19-big-picture-design.md
"""

import logging
import math
import threading
import time
from typing import Callable, Iterable, Optional

import winsound
from gi.repository import Adw, Gdk, Gio, GLib, GObject, Graphene, Gsk, Gtk

from cartridges import shared
from cartridges.game_cover import GameCover
from cartridges.utils import janela_por_cima, restauracao
from cartridges.utils.cortina_monitor import CortinaMonitor

DURACAO_ABERTURA_MS = 400
DURACAO_FILA_ENTRADA_MS = 1700
DURACAO_FILA_SAIDA_MS = 1100
JOGOS_NA_FILA = 30
INTERVALO_NORMAL_US = 120_000
ACELERAR_APOS_US = 1_000_000
INTERVALO_ACELERADO_US = 40_000

# Calibração do Cover Flow (ajustar no app real). Distâncias em múltiplos da
# largura da capa, exceto a profundidade, em pixels.
PERSPECTIVA = 900
ANGULO_LATERAL = 65
ESPACO_CENTRAL = 1.15  # do centro até a primeira lateral
ESPACO_LATERAL = 0.45  # entre laterais
PROFUNDIDADE_LATERAL = 220
CAPAS_DE_CADA_LADO = 8
DURACAO_PASSO_MS = 350
ESCALA_NA_ABERTURA = 1.6
FAIXAS_DO_REFLEXO = 24
REFLEXO_ALCANCE = 0.55  # o reflexo some a esta fração da altura da capa
REFLEXO_OPACIDADE = 0.35

# Fundo: degradê vertical do topo à base, pontilhado em no máximo 1 tom.
FUNDO_TOPO = (28, 28, 30)  # #1c1c1e
FUNDO_EXPOENTE = 1.6
_BAYER_8 = (
    (0, 32, 8, 40, 2, 34, 10, 42),
    (48, 16, 56, 24, 50, 18, 58, 26),
    (12, 44, 4, 36, 14, 46, 6, 38),
    (60, 28, 52, 20, 62, 30, 54, 22),
    (3, 35, 11, 43, 1, 33, 9, 41),
    (51, 19, 59, 27, 49, 17, 57, 25),
    (15, 47, 7, 39, 13, 45, 5, 37),
    (63, 31, 55, 23, 61, 29, 53, 21),
)
_LIMIARES = tuple(tuple((v + 0.5) / 64 for v in linha) for linha in _BAYER_8)


def bytes_do_fundo(largura: int, altura: int) -> bytes:
    """O fundo em RGB de 8 bits (`largura·altura·3` bytes, linha a linha).

    Cada linha tem um valor exato por canal; o arredondamento usa os limiares
    da matriz Bayer 8×8 completa, então nenhum pixel difere do exato em mais de 1 tom.
    A linha é montada com 8 pixels que se repetem (sem laço por pixel).
    """
    repeticoes = -(-largura // 8)
    linhas = []
    for y in range(altura):
        k = (1 - y / (altura - 1)) ** FUNDO_EXPOENTE if altura > 1 else 1.0
        limiares = _LIMIARES[y % 8]
        exatos = [c * k for c in FUNDO_TOPO]
        base = [int(e) for e in exatos]
        fracao = [e - b for e, b in zip(exatos, base)]
        padrao = bytes(
            b + (f > limiar)
            for limiar in limiares
            for b, f in zip(base, fracao)
        )
        linhas.append((padrao * repeticoes)[: largura * 3])
    return b"".join(linhas)


def jogos_da_biblioteca(jogos: Iterable) -> list:
    """Os jogos que aparecem na biblioteca, do jogado mais recentemente ao mais antigo."""
    visiveis = [
        j
        for j in jogos
        if not (j.blacklisted or j.removed or restauracao.e_pendente(j.game_id))
    ]
    # Duas ordenações estáveis: nome crescente primeiro, depois last_played decrescente.
    visiveis.sort(key=lambda j: j.name.casefold())
    visiveis.sort(key=lambda j: j.last_played, reverse=True)
    return visiveis


def pode_entrar_sozinho(
    *,
    preferencia: bool,
    controle_ligado: bool,
    tem_3d: bool,
    grade_a_vista: bool,
    ja_saiu: bool,
) -> bool:
    return (
        preferencia and controle_ligado and tem_3d and grade_a_vista and not ja_saiu
    )


def tem_3d(janela) -> bool:
    """Sem renderizador, ou com o de Cairo (por software), o Cover Flow não roda bem."""
    renderizador = janela.get_renderer()
    return renderizador is not None and not isinstance(
        renderizador, Gsk.CairoRenderer
    )


def intervalo_de_repeticao_us(segurando_us: int) -> int:
    if segurando_us >= ACELERAR_APOS_US:
        return INTERVALO_ACELERADO_US
    return INTERVALO_NORMAL_US


def _limitar(x: float) -> float:
    return max(0.0, min(1.0, x))


def quadro_da_fila(t: float, n: float, base: float) -> tuple[float, float, float, float]:
    """(posição, virada, opacidade das capas, opacidade do rodapé) da fila no instante `t` (0 a 1)."""
    corrida = 1 - (1 - _limitar(t / 0.7)) ** 3  # ease_out_cubic
    x = _limitar((t - 0.65) / 0.35)
    c1 = 1.4
    # ease_out_back; a virada fica em 0 até `x` sair de 0
    virada = 1 + (c1 + 1) * (x - 1) ** 3 + c1 * (x - 1) ** 2 if x > 0 else 0.0
    return base + n * (1 - corrida), virada, min(1.0, 5 * t), _limitar((t - 0.8) / 0.2)


class Carrossel:
    """O jogo central do Cover Flow: um índice preso aos limites da lista de ids."""

    def __init__(self, ids: list[str]) -> None:
        self.ids = list(ids)
        self.indice = 0

    @property
    def atual(self) -> Optional[str]:
        return self.ids[self.indice] if self.ids else None

    def ir_para(self, indice: int) -> bool:
        """Vai para o índice (preso a [0, len-1]); devolve se o índice mudou."""
        novo = max(0, min(indice, len(self.ids) - 1))
        mudou = novo != self.indice
        self.indice = novo
        return mudou

    def mover(self, delta: int) -> bool:
        return self.ir_para(self.indice + delta)

    def inicio(self) -> bool:
        return self.ir_para(0)

    def fim(self) -> bool:
        return self.ir_para(len(self.ids) - 1)

    def trocar_lista(self, ids: list[str], centro: Optional[str] = None) -> None:
        """Troca a lista mantendo o jogo central (ou o `centro`, se dado)."""
        alvo = centro if centro is not None else self.atual
        self.ids = list(ids)
        if alvo in self.ids:
            self.indice = self.ids.index(alvo)
        else:
            self.indice = max(0, min(self.indice, len(self.ids) - 1))


class CoverFlow(Gtk.Widget):
    """As capas dos jogos em perspectiva, a central de frente e o reflexo embaixo."""

    __gtype_name__ = "CoverFlow"

    _posicao = 0.0
    _progresso_abertura = 0.0
    _virada = 1.0
    _opacidade_capas = 1.0

    def __init__(self) -> None:
        super().__init__(hexpand=True, vexpand=True)
        self._jogos: list = []
        self._central: Optional[int] = None
        self._animacao: Optional[Adw.TimedAnimation] = None
        # Fora da árvore: só existe para a capa central animada avisar de cada
        # quadro novo (notify::paintable) e o widget se redesenhar.
        self._figura_central = Gtk.Picture()
        self._figura_central.connect("notify::paintable", lambda *_: self.queue_draw())
        # Uma figura oculta por capa lateral visível: capa nova (download em
        # segundo plano, importação) redesenha na hora. Chave: índice do jogo.
        self._figuras: dict[int, Gtk.Picture] = {}
        # Fundo: a última textura gerada e o tamanho (em pixels reais) dela.
        self._fundo: Optional[Gdk.Texture] = None
        self._fundo_tamanho: tuple[int, int] = (0, 0)

    @GObject.Property(type=float)
    def posicao(self) -> float:
        return self._posicao

    @posicao.setter
    def posicao(self, valor: float) -> None:
        self._posicao = valor
        self._sincronizar_figuras()
        self.queue_draw()

    @GObject.Property(type=float)
    def progresso_abertura(self) -> float:
        return self._progresso_abertura

    @progresso_abertura.setter
    def progresso_abertura(self, valor: float) -> None:
        self._progresso_abertura = valor
        self.queue_draw()

    @property
    def virada(self) -> float:
        """1.0 = arranjo normal; 0.0 = todas de perfil em fila (passa de 1 na ultrapassagem)."""
        return self._virada

    @virada.setter
    def virada(self, valor: float) -> None:
        self._virada = valor
        self.queue_draw()

    @property
    def opacidade_capas(self) -> float:
        """Multiplica a opacidade de cada capa e do reflexo."""
        return self._opacidade_capas

    @opacidade_capas.setter
    def opacidade_capas(self, valor: float) -> None:
        self._opacidade_capas = valor
        self.queue_draw()

    # --- jogos e animação ---
    def definir_jogos(self, jogos: list, indice: int) -> None:
        self._parar_animacao()
        self._soltar_central()
        self._soltar_figuras()
        self._jogos = list(jogos)
        self.posicao = indice
        self._trocar_central(indice)

    def animar_para(self, indice: int) -> None:
        self._parar_animacao()
        animacao = Adw.TimedAnimation.new(
            self,
            self._posicao,
            indice,
            DURACAO_PASSO_MS,
            Adw.PropertyAnimationTarget.new(self, "posicao"),
        )
        animacao.set_easing(Adw.Easing.EASE_OUT_CUBIC)
        animacao.connect("done", lambda *_: self._trocar_central(indice))
        self._animacao = animacao
        animacao.play()

    def parar_passo(self, indice: int) -> None:
        """Interrompe o passo em curso; `posicao` fica onde está e `indice` vira a central."""
        self._parar_animacao()
        self._trocar_central(indice)

    def _parar_animacao(self) -> None:
        if self._animacao is not None:
            # `pause` não emite `done`: a nova recomeça de onde esta parou.
            self._animacao.pause()
            self._animacao = None

    def _trocar_central(self, indice: int) -> None:
        if indice == self._central:
            return
        self._soltar_central()
        if 0 <= indice < len(self._jogos):
            self._central = indice
            capa = self._jogos[indice].game_cover
            capa.add_picture(self._figura_central)
            capa.textura_grande()  # decodifica já, não no primeiro quadro
            capa.set_big_picture_animation(shared.schema.get_boolean("cover-autoplay"))
        self._sincronizar_figuras()

    def _soltar_central(self) -> None:
        if self._central is not None and self._central < len(self._jogos):
            capa = self._jogos[self._central].game_cover
            capa.set_big_picture_animation(False)
            capa.release_picture(self._figura_central)
            capa.soltar_textura_grande()
        self._central = None

    def _sincronizar_figuras(self) -> None:
        """Figuras só nas capas laterais visíveis (a central tem a sua)."""
        desejadas = set(self._visiveis()) - {self._central}
        for i in list(self._figuras):
            if i not in desejadas:
                self._soltar_figura(i)
        for i in desejadas - self._figuras.keys():
            figura = Gtk.Picture()
            figura.connect("notify::paintable", lambda *_: self.queue_draw())
            self._figuras[i] = figura
            self._jogos[i].game_cover.add_picture(figura)

    def _soltar_figura(self, i: int) -> None:
        figura = self._figuras.pop(i)
        if i < len(self._jogos):
            self._jogos[i].game_cover.release_picture(figura)

    def _soltar_figuras(self) -> None:
        for i in list(self._figuras):
            self._soltar_figura(i)

    def do_unroot(self) -> None:
        self._parar_animacao()
        self._soltar_central()
        self._soltar_figuras()
        Gtk.Widget.do_unroot(self)

    # --- geometria ---
    def _medidas(self) -> tuple[float, float]:
        altura = self.get_height() * 0.55
        return altura * 2 / 3, altura  # capas 2:3

    def _arranjo(self, i: int) -> tuple[float, float, float]:
        """(x, ângulo, profundidade) da capa `i`: a mistura, por `virada`, da fila e do normal."""
        largura, _ = self._medidas()
        d = i - self._posicao
        a = min(abs(d), 1.0)
        lado = math.copysign(1, d)
        if abs(d) <= 1:
            x = d * largura * ESPACO_CENTRAL
        else:
            x = lado * (
                largura * ESPACO_CENTRAL + (abs(d) - 1) * largura * ESPACO_LATERAL
            )
        angulo = -lado * a * ANGULO_LATERAL
        profundidade = -a * PROFUNDIDADE_LATERAL
        v = self._virada
        if v == 1.0:
            return x, angulo, profundidade
        x_fila = d * largura * ESPACO_LATERAL * 1.6
        return (
            x_fila + (x - x_fila) * v,
            -ANGULO_LATERAL + (angulo + ANGULO_LATERAL) * v,
            -PROFUNDIDADE_LATERAL + (profundidade + PROFUNDIDADE_LATERAL) * v,
        )

    def _transformacao(self, i: int) -> Gsk.Transform:
        """Do espaço da capa (0,0 a largura,altura) ao do widget.

        Serve ao desenho e a `capa_em`: o que se clica é o que se vê.
        """
        largura, altura = self._medidas()
        a = min(abs(i - self._posicao), 1.0)
        x, angulo, profundidade = self._arranjo(i)
        escala = 1 + (ESCALA_NA_ABERTURA - 1) * self._progresso_abertura * (1 - a)
        t = Gsk.Transform()
        t = t.translate(
            Graphene.Point().init(self.get_width() / 2, self.get_height() * 0.40)
        )
        t = t.perspective(PERSPECTIVA)
        t = t.translate_3d(Graphene.Point3D().init(x, 0, profundidade))
        t = t.rotate_3d(angulo, Graphene.Vec3.y_axis())
        t = t.scale(escala, escala)
        return t.translate(Graphene.Point().init(-largura / 2, -altura / 2))

    def _visiveis(self) -> list[int]:
        """Índices desenhados, do mais próximo do centro ao mais distante."""
        p = self._posicao
        k = CAPAS_DE_CADA_LADO
        # Só a janela em volta de `posicao`: não percorre a biblioteca toda.
        janela = range(
            max(0, math.floor(p - k) + 1), min(len(self._jogos), math.ceil(p + k))
        )
        return sorted(
            (i for i in janela if abs(i - p) < k), key=lambda i: abs(i - p)
        )

    def capa_em(self, x: float, y: float) -> Optional[int]:
        largura, altura = self._medidas()
        retangulo = Graphene.Rect().init(0, 0, largura, altura)
        ponto = Graphene.Point().init(x, y)
        for i in self._visiveis():
            area = self._transformacao(i).transform_bounds(retangulo)
            if area.contains_point(ponto):
                return i
        return None

    # --- desenho ---
    def _textura_de(self, i: int) -> Gdk.Texture:
        capa = self._jogos[i].game_cover
        # Lida da capa a cada quadro: um `new_cover` na central (capa nova ou
        # removida) vale já, sem cópia velha aqui.
        if i == self._central and (grande := capa.textura_grande()) is not None:
            return grande
        return capa.get_texture() or GameCover.placeholder

    def _escala(self) -> float:
        """Fator de escala (fracionário) da superfície; 1.0 sem janela."""
        nativo = self.get_native()
        superficie = nativo.get_surface() if nativo else None
        return superficie.get_scale() if superficie else 1.0

    def _textura_do_fundo(self) -> Optional[Gdk.Texture]:
        """O fundo no tamanho em pixels reais; guarda só o último tamanho."""
        escala = self._escala()
        tamanho = (
            round(self.get_width() * escala),
            round(self.get_height() * escala),
        )
        if tamanho[0] <= 0 or tamanho[1] <= 0:
            return None
        if tamanho != self._fundo_tamanho:
            self._fundo_tamanho = tamanho
            try:
                dados = bytes_do_fundo(*tamanho)
                self._fundo = Gdk.MemoryTexture.new(
                    tamanho[0],
                    tamanho[1],
                    Gdk.MemoryFormat.R8G8B8,
                    GLib.Bytes.new(dados),
                    tamanho[0] * 3,
                )
            except Exception:  # cosmético: o CSS deixa o fundo preto
                logging.exception("Big Picture: falha ao gerar o fundo")
                self._fundo = None
        return self._fundo

    def do_snapshot(self, snapshot: Gtk.Snapshot) -> None:
        if (fundo := self._textura_do_fundo()) is not None:
            snapshot.append_scaled_texture(
                fundo,
                Gsk.ScalingFilter.NEAREST,
                Graphene.Rect().init(0, 0, self.get_width(), self.get_height()),
            )
        largura, altura = self._medidas()
        retangulo = Graphene.Rect().init(0, 0, largura, altura)
        for i in reversed(self._visiveis()):
            textura = self._textura_de(i)
            snapshot.save()
            # Na abertura do jogo, tudo esmaece junto com a central crescendo.
            snapshot.push_opacity((1 - self._progresso_abertura) * self._opacidade_capas)
            snapshot.transform(self._transformacao(i))
            snapshot.append_scaled_texture(
                textura, Gsk.ScalingFilter.TRILINEAR, retangulo
            )
            # Reflexo: a mesma capa espelhada, sumindo em faixas. Um push_mask
            # com degradê some sob o rotate_3d (medido no Vulkan), então o
            # esmaecer é feito com faixas de opacidade decrescente.
            snapshot.save()
            snapshot.translate(Graphene.Point().init(0, 2 * altura + 4))
            snapshot.scale(1, -1)
            for k in range(FAIXAS_DO_REFLEXO):
                t = (k + 0.5) / FAIXAS_DO_REFLEXO  # 0 na ponta, 1 junto da capa
                topo = altura * (REFLEXO_ALCANCE + (1 - REFLEXO_ALCANCE) * k / FAIXAS_DO_REFLEXO)
                snapshot.push_opacity(REFLEXO_OPACIDADE * t)
                snapshot.push_clip(
                    Graphene.Rect().init(
                        0, topo, largura, altura * (1 - REFLEXO_ALCANCE) / FAIXAS_DO_REFLEXO
                    )
                )
                snapshot.append_scaled_texture(
                    textura, Gsk.ScalingFilter.TRILINEAR, retangulo
                )
                snapshot.pop()
                snapshot.pop()
            snapshot.restore()
            snapshot.pop()
            snapshot.restore()


INTERVALO_TIQUE_S = 0.07
_ultimo_tique = float("-inf")
_dados_tique: Optional[bytes] = None


def _tocar_dados(dados: bytes) -> None:
    # SND_MEMORY não aceita SND_ASYNC: por isso a thread. SND_NODEFAULT: sem som
    # padrão do Windows por cima do jogo se não der para tocar.
    try:
        winsound.PlaySound(dados, winsound.SND_MEMORY | winsound.SND_NODEFAULT)
    except Exception:  # pylint: disable=broad-exception-caught
        logging.warning("Falha ao tocar o tique do Big Picture", exc_info=True)


def tocar_tique() -> None:
    """Toca o tique de troca de capa, se ligado e passados 70 ms do anterior. Nunca levanta."""
    global _ultimo_tique, _dados_tique  # pylint: disable=global-statement
    try:
        if not shared.schema.get_boolean("big-picture-som"):
            return
        agora = time.monotonic()
        if agora - _ultimo_tique < INTERVALO_TIQUE_S:
            return
        if _dados_tique is None:
            _dados_tique = Gio.resources_lookup_data(
                shared.PREFIX + "/sons/tique.wav", Gio.ResourceLookupFlags.NONE
            ).get_data()
        _ultimo_tique = agora
        threading.Thread(target=_tocar_dados, args=(_dados_tique,), daemon=True).start()
    except Exception:  # pylint: disable=broad-exception-caught
        logging.warning("Não foi possível tocar o tique do Big Picture", exc_info=True)


class PaginaBigPicture(Adw.NavigationPage):
    """A página do Big Picture: o Cover Flow, o nome do jogo e a entrada própria."""

    # Atributo de classe para os testes trocarem a cortina por uma falsa.
    _fabrica_cortina = CortinaMonitor

    def __init__(self, janela) -> None:
        super().__init__(title=_("Big Picture"), tag="big-picture", can_pop=False)
        self.janela = janela
        self.ja_saiu = False
        self._estava_maximizada = False
        self.ocupada = False
        self.carrossel = Carrossel([])
        self._jogos: list = []
        self._jogo_aberto: Optional[str] = None
        self._animacao_abertura: Optional[Adw.TimedAnimation] = None
        self._animacao_fila: Optional[Adw.TimedAnimation] = None
        self._entrando_na_fila = True
        # Fade do monitor: a cortina, sua animação e a pausa entre escurecer e clarear.
        self._cortina: Optional[CortinaMonitor] = None
        self._animacao_cortina: Optional[Adw.TimedAnimation] = None
        self._pausa_cortina: Optional[int] = None
        self._em_fade = False
        self._saindo = False
        self._trocando = False
        self._dono_cortina: Optional[Gtk.Widget] = None
        # Pedido de `atualizar` feito durante a fila: só o centro mais recente vale.
        self._atualizar_pendente = False
        self._centro_pendente: Optional[str] = None
        self._passos_arrastados = 0
        self._espera_ativacao: Optional[int] = None
        self.add_css_class("big-picture")
        self.set_focusable(True)

        self.cover_flow = CoverFlow()
        self.rotulo_nome = Gtk.Label(wrap=True, justify=Gtk.Justification.CENTER)
        self.rotulo_nome.add_css_class("title-1")
        self.rotulo_desenvolvedora = Gtk.Label()
        self.rotulo_desenvolvedora.add_css_class("dim-label")
        self.rodape = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL,
            spacing=6,
            halign=Gtk.Align.CENTER,
            valign=Gtk.Align.END,
            margin_bottom=48,
        )
        self.rodape.append(self.rotulo_nome)
        self.rodape.append(self.rotulo_desenvolvedora)
        self.vazio = Adw.StatusPage(
            title=_("Nenhum jogo"),
            description=_("Pressione B ou Esc para voltar à biblioteca."),
            visible=False,
        )
        sobreposicao = Gtk.Overlay(child=self.cover_flow)
        sobreposicao.add_overlay(self.rodape)
        sobreposicao.add_overlay(self.vazio)
        self.set_child(sobreposicao)

        teclas = Gtk.EventControllerKey()
        teclas.connect("key-pressed", self._ao_apertar_tecla)
        self.add_controller(teclas)
        roda = Gtk.EventControllerScroll.new(
            Gtk.EventControllerScrollFlags.VERTICAL
            | Gtk.EventControllerScrollFlags.DISCRETE
        )
        roda.connect("scroll", self._ao_rolar)
        self.add_controller(roda)
        clique = Gtk.GestureClick()
        clique.connect("released", self._ao_clicar)
        self.add_controller(clique)
        arraste = Gtk.GestureDrag()
        arraste.connect(
            "drag-begin", lambda *_: setattr(self, "_passos_arrastados", 0)
        )
        arraste.connect("drag-update", self._ao_arrastar)
        self.add_controller(arraste)

    @property
    def visivel(self) -> bool:
        return self.janela.navigation_view.get_visible_page() is self

    def do_unroot(self) -> None:
        # A própria troca da sequência desempilha a página (sair): aí a cortina
        # continua. Fora disso é a janela fechando no meio do fade.
        if not self._trocando and self._cortina is not None:
            self._fechar_cortina()
            self._em_fade = self._saindo = self.ocupada = False
        Adw.NavigationPage.do_unroot(self)

    # --- entrar e sair ---
    def _sem_animacao(self, acao) -> None:
        nav = self.janela.navigation_view
        animado = nav.get_animate_transitions()
        nav.set_animate_transitions(False)
        try:
            acao()
        finally:
            nav.set_animate_transitions(animado)

    def entrar(self) -> None:
        if self.visivel or self.ocupada:
            return
        self.ocupada = self._em_fade = True
        self._trocar_no_escuro(self._entrar_de_fato, 300, self._fim_da_entrada)

    def _fim_da_entrada(self) -> None:
        self._em_fade = False
        self.ocupada = self._animacao_fila is not None

    def _entrar_de_fato(self) -> None:
        jogos = jogos_da_biblioteca(shared.store)
        self.carrossel = Carrossel([j.game_id for j in jogos])
        self._mostrar(jogos)
        self._sem_animacao(lambda: self.janela.navigation_view.push(self))
        # O unfullscreen() do GTK no Windows não devolve o estado maximizado.
        self._estava_maximizada = self.janela.is_maximized()
        self.janela.fullscreen()
        self.grab_focus()
        self.animar_fila(True)

    def sair(self) -> None:
        if self.ocupada or not self.visivel:
            return
        self.ocupada = self._saindo = True
        self.cover_flow.parar_passo(self.carrossel.indice)
        self.animar_fila(
            False,
            lambda: self._trocar_no_escuro(self._sair_de_fato, 250, self._fim_da_saida),
        )

    def _fim_da_saida(self) -> None:
        self._saindo = False
        self.ocupada = False

    def _sair_de_fato(self) -> None:
        try:
            self._trocar_ao_sair()
        finally:
            # só agora: antes disso o carrossel ficaria visível no escuro
            self._repor_quadro()

    def _trocar_ao_sair(self) -> None:
        jogo = self._jogo_central()
        self._sem_animacao(self.janela.navigation_view.pop)
        self.janela.unfullscreen()
        if self._estava_maximizada:
            self.janela.maximize()
        pai = getattr(jogo, "get_parent", lambda: None)()
        if isinstance(pai, Gtk.FlowBoxChild):
            pai.grab_focus()
        self.ja_saiu = True

    # --- fade do monitor ---
    def _trocar_no_escuro(
        self,
        trocar: Callable[[], None],
        ms_escurecer: int,
        depois: Optional[Callable[[], None]],
    ) -> None:
        """Escurece o monitor, troca, espera um instante e clareia. Sem cortina, só troca."""
        self._fechar_cortina()  # nunca deixa uma cortina anterior órfã
        cortina = None
        hwnd = janela_por_cima.handle(self.janela)
        if hwnd:
            try:
                cortina = self._fabrica_cortina(hwnd)
            except Exception:  # pylint: disable=broad-exception-caught
                logging.warning("Não foi possível criar a cortina do monitor", exc_info=True)
        if cortina is None:
            try:
                trocar()
            finally:
                if depois is not None:
                    depois()
            return
        self._cortina = cortina

        def escurecido() -> None:
            self._trocando = True
            try:
                trocar()
            finally:
                self._trocando = False
                self._pausa_cortina = GLib.timeout_add(120, clarear)

        def clarear() -> bool:
            self._pausa_cortina = None

            def claro() -> None:
                self._fechar_cortina()
                if depois is not None:
                    depois()

            self._animar_cortina(1.0, 0.0, 350, claro)
            return False

        self._animar_cortina(0.0, 1.0, ms_escurecer, escurecido)

    def _alfa_cortina(self, valor: float) -> None:
        if self._cortina is None:
            return
        try:
            self._cortina.alfa(valor)
        except OSError:
            logging.warning("Não foi possível mudar a cortina do monitor", exc_info=True)

    def _dono_da_animacao(self) -> Gtk.Widget:
        """Widget mapeado durante toda a troca. A página não serve: o libadwaita
        pula a animação de um widget desmapeado (antes do push, depois do pop)."""
        if self._dono_cortina is None:
            self._dono_cortina = Gtk.Box(can_target=False, opacity=0.0)
            self.janela.session_overlay.add_overlay(self._dono_cortina)
        return self._dono_cortina

    def _animar_cortina(
        self, de: float, para: float, ms: int, ao_fim: Callable[[], None]
    ) -> None:
        self._alfa_cortina(de)
        animacao = Adw.TimedAnimation.new(
            self._dono_da_animacao(),
            de,
            para,
            ms,
            Adw.CallbackAnimationTarget.new(self._alfa_cortina),
        )
        animacao.set_easing(Adw.Easing.EASE_IN_OUT_CUBIC)
        animacao.connect("done", lambda *_: ao_fim())
        self._animacao_cortina = animacao
        animacao.play()

    def _fechar_cortina(self) -> None:
        if self._pausa_cortina is not None:
            GLib.source_remove(self._pausa_cortina)
            self._pausa_cortina = None
        if self._animacao_cortina is not None:
            self._animacao_cortina.pause()
            self._animacao_cortina = None
        cortina, self._cortina = self._cortina, None
        if cortina is not None:
            cortina.fechar()

    # --- fila indiana ---
    def _aplicar_quadro(self, t: float, base: float) -> None:
        n = min(JOGOS_NA_FILA, max(0, len(self._jogos) - 1))
        posicao, virada, capas, rodape = quadro_da_fila(t, n, base)
        fluxo = self.cover_flow
        fluxo.posicao = posicao
        fluxo.virada = virada
        fluxo.opacidade_capas = capas
        self.rodape.set_opacity(rodape)

    def animar_fila(
        self, entrando: bool, ao_fim: Optional[Callable[[], None]] = None
    ) -> None:
        """A fila corre até a capa central (entrada) ou parte dela (saída); depois `ao_fim`."""
        if not self._jogos:
            if ao_fim is not None:
                ao_fim()
            return
        base = 0.0 if entrando else float(self.cover_flow.posicao)
        self._entrando_na_fila = entrando
        self.ocupada = True
        de, para, ms = (
            (0.0, 1.0, DURACAO_FILA_ENTRADA_MS)
            if entrando
            else (1.0, 0.0, DURACAO_FILA_SAIDA_MS)
        )
        self._aplicar_quadro(de, base)
        animacao = Adw.TimedAnimation.new(
            self,
            de,
            para,
            ms,
            Adw.CallbackAnimationTarget.new(lambda t: self._aplicar_quadro(t, base)),
        )
        animacao.set_easing(Adw.Easing.LINEAR)
        animacao.connect("done", lambda *_: self._terminou_fila(ao_fim))
        self._animacao_fila = animacao
        animacao.play()

    def _repor_quadro(self) -> None:
        """O estado normal do carrossel, depois da fila."""
        fluxo = self.cover_flow
        fluxo.posicao = self.carrossel.indice
        fluxo.virada = 1.0
        fluxo.opacidade_capas = 1.0
        self.rodape.set_opacity(1.0)

    def _terminou_fila(self, ao_fim) -> None:
        self._animacao_fila = None
        if self._entrando_na_fila:
            self._repor_quadro()
            self.ocupada = self._em_fade
        if ao_fim is not None:
            ao_fim()
        pendente, centro = self._atualizar_pendente, self._centro_pendente
        self._atualizar_pendente, self._centro_pendente = False, None
        if pendente:
            self.atualizar(centro)

    # --- lista e rótulos ---
    def _jogo_central(self):
        if 0 <= self.carrossel.indice < len(self._jogos):
            return self._jogos[self.carrossel.indice]
        return None

    def _mostrar(self, jogos: list) -> None:
        self._jogos = jogos
        self.cover_flow.definir_jogos(jogos, self.carrossel.indice)
        self.vazio.set_visible(not jogos)
        self.rodape.set_visible(bool(jogos))
        self._atualizar_rotulos()

    def _atualizar_rotulos(self) -> None:
        jogo = self._jogo_central()
        self.rotulo_nome.set_label(jogo.name if jogo else "")
        self.rotulo_desenvolvedora.set_label((jogo.developer if jogo else "") or "")

    def atualizar(self, centro: Optional[str] = None) -> None:
        if not self.visivel or self._saindo:
            return
        if self._animacao_fila is not None:
            self._atualizar_pendente, self._centro_pendente = True, centro
            return
        jogos = jogos_da_biblioteca(shared.store)
        self.carrossel.trocar_lista([j.game_id for j in jogos], centro)
        self._mostrar(jogos)

    # --- navegação ---
    def _foi_para(self, mudou: bool) -> bool:
        if mudou:
            tocar_tique()
            self.cover_flow.animar_para(self.carrossel.indice)
            self._atualizar_rotulos()
        return mudou

    def mover(self, delta: int) -> bool:
        return not self.ocupada and self._foi_para(self.carrossel.mover(delta))

    pular = mover

    def ir_para(self, indice: int) -> bool:
        return not self.ocupada and self._foi_para(self.carrossel.ir_para(indice))

    def inicio(self) -> bool:
        return not self.ocupada and self._foi_para(self.carrossel.inicio())

    def fim(self) -> bool:
        return not self.ocupada and self._foi_para(self.carrossel.fim())

    # --- abrir o jogo ---
    def _animar_abertura(self, de: float, para: float, ao_fim=None) -> None:
        if self._animacao_abertura is not None:
            self._animacao_abertura.pause()
        animacao = Adw.TimedAnimation.new(
            self.cover_flow,
            de,
            para,
            DURACAO_ABERTURA_MS,
            Adw.PropertyAnimationTarget.new(self.cover_flow, "progresso-abertura"),
        )
        if ao_fim is not None:
            animacao.connect("done", lambda *_: ao_fim())
        self._animacao_abertura = animacao
        animacao.play()

    def abrir_jogo(self) -> None:
        jogo = self._jogo_central()
        if self.ocupada or jogo is None:
            return
        self.ocupada = True
        self._jogo_aberto = jogo.game_id
        self._animar_abertura(0, 1, lambda: self._lancar(jogo))

    def _lancar(self, jogo) -> None:
        self.janela.unfullscreen()
        try:
            aberto = jogo.launch()
        except Exception:
            self._animar_abertura(1, 0)
            self.janela.fullscreen()
            self.ocupada = False
            raise
        if not aberto:
            self._animar_abertura(1, 0)
            self.janela.fullscreen()
            self.ocupada = False
        elif self.janela.session_game is None:
            self._voltar_sem_sessao()
        # Com sessão, a janela chama `voltou_do_jogo` quando ela termina.

    def voltou_do_jogo(self) -> None:
        if not self.ocupada:
            return
        self.janela.fullscreen()
        self._reabrir()

    def _reabrir(self) -> None:
        self.atualizar(self._jogo_aberto)
        self._animar_abertura(1, 0)
        self.ocupada = False
        # O bloqueio da sessão levou o foco; sem ele o teclado não chega aqui.
        self.grab_focus()

    def _voltar_sem_sessao(self) -> None:
        # Com "minimizar ao abrir" o `launch` acabou de minimizar a janela, e o
        # `is-active` só muda no ciclo seguinte: não dá para decidir pelo foco.
        # Põe a tela cheia quando a janela voltar a ficar ativa.
        self._reabrir()
        janela = self.janela
        if not shared.schema.get_boolean("minimize-after-launch"):
            janela.fullscreen()
            return
        if self._espera_ativacao is not None:
            return

        def ao_ativar(*_args) -> None:
            if not janela.is_active():
                return
            janela.disconnect(self._espera_ativacao)
            self._espera_ativacao = None
            if self.visivel:
                janela.fullscreen()

        self._espera_ativacao = janela.connect("notify::is-active", ao_ativar)

    # --- entrada ---
    def _ao_apertar_tecla(self, _controle, tecla, _codigo, _estado) -> bool:
        acoes = {
            Gdk.KEY_Left: lambda: self.mover(-1),
            Gdk.KEY_Right: lambda: self.mover(1),
            Gdk.KEY_Page_Up: lambda: self.pular(-10),
            Gdk.KEY_Page_Down: lambda: self.pular(10),
            Gdk.KEY_Home: self.inicio,
            Gdk.KEY_End: self.fim,
            Gdk.KEY_Return: self.abrir_jogo,
            Gdk.KEY_KP_Enter: self.abrir_jogo,
            Gdk.KEY_space: self.abrir_jogo,
            Gdk.KEY_Escape: self.sair,
        }
        acao = acoes.get(tecla)
        if acao is None:
            return False
        acao()
        return True

    def _ao_rolar(self, _controle, _dx, dy) -> bool:
        self.mover(1 if dy > 0 else -1)
        return True

    def _ao_clicar(self, _gesto, _n, x, y) -> None:
        if self._passos_arrastados or self.ocupada:
            return
        indice = self.cover_flow.capa_em(x, y)
        if indice == self.carrossel.indice:
            self.abrir_jogo()
        elif indice is not None:
            self.ir_para(indice)

    def _ao_arrastar(self, _gesto, desloc_x, _desloc_y) -> None:
        passo = ESPACO_LATERAL * self.cover_flow._medidas()[0]
        if passo <= 0:
            return
        alvo = -int(desloc_x / passo)
        if alvo != self._passos_arrastados:
            self.mover(alvo - self._passos_arrastados)
            self._passos_arrastados = alvo
