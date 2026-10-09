"""O cartão que aparece por cima do jogo quando uma conquista é desbloqueada.

Ícone, rótulo ("Conquista desbloqueada", ou "Todas as conquistas
desbloqueadas" na que fecha 100%, com "★ Rara" quando for o caso), título e
descrição. Fica 5 s na tela; várias de uma vez entram em fila e aparecem uma
depois da outra. A janela nunca pega o foco (`utils/janela_por_cima.py`).
Cada cartão toca um som ao entrar, se "Tocar som com o aviso" estiver ligado.
"""

import logging
import threading
import winsound
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable, Optional

from gi.repository import Adw, Gio, GLib, Gtk

from cartridges import shared
from cartridges.conquistas import icones, progresso
from cartridges.utils import janela_por_cima

DURACAO = 5
_ENTRADA_MS = 250
_LIMITE_DA_SAIDA = 1  # segundos até a saída ser dada por terminada, com ou sem animação


def _agendar(segundos: int, funcao: Callable[[], Any]) -> int:
    return GLib.timeout_add_seconds(segundos, funcao)


def _em_segundo_plano(funcao: Callable[..., Any], *args: Any) -> None:
    threading.Thread(target=funcao, args=args, daemon=True).start()


def _tocar_som() -> None:
    """Toca o som do aviso sem travar a tela. Nunca levanta: sem som, o cartão aparece igual."""
    try:
        if not shared.schema.get_boolean("conquistas-aviso-som"):
            return
        dados = Gio.resources_lookup_data(
            shared.PREFIX + "/sons/conquista.wav", Gio.ResourceLookupFlags.NONE
        ).get_data()
        _em_segundo_plano(_reproduzir, dados)
    except Exception:  # pylint: disable=broad-exception-caught
        logging.warning("Não foi possível tocar o som do aviso de conquista", exc_info=True)


def _reproduzir(dados: bytes) -> None:
    # SND_MEMORY não aceita SND_ASYNC: por isso a thread. SND_NODEFAULT: se não
    # der para tocar, silêncio, e não o som padrão do Windows por cima do jogo.
    try:
        winsound.PlaySound(dados, winsound.SND_MEMORY | winsound.SND_NODEFAULT)
    except Exception:  # pylint: disable=broad-exception-caught
        logging.warning("Falha ao tocar o som do aviso de conquista", exc_info=True)


@dataclass(frozen=True)
class Aviso:
    rotulo: str
    titulo: str
    descricao: str
    icone: str

    @classmethod
    def de(cls, desbloqueada: Any) -> Optional["Aviso"]:
        info = desbloqueada.info
        if info is None:
            return None
        rotulo = (
            _("Todas as conquistas desbloqueadas")
            if desbloqueada.completou
            else _("Conquista desbloqueada")
        )
        if info.rara and info.porcentagem is not None:
            # A variável é a porcentagem de jogadores, como "4,1%"
            rotulo += " · " + _("★ Rara, {}").format(
                progresso.porcentagem_em_texto(info.porcentagem)
            )
        return cls(rotulo, info.titulo, info.descricao, info.icone)

    @classmethod
    def exemplo(cls) -> "Aviso":
        return cls(
            _("Conquista desbloqueada")
            + " · "
            + _("★ Rara, {}").format(progresso.porcentagem_em_texto(4.1)),
            _("Conquista de exemplo"),
            _("Assim o aviso aparece durante o jogo."),
            "",
        )


class _JanelaDoAviso(Gtk.Window):
    def __init__(self, aviso: Aviso) -> None:
        super().__init__(decorated=False, resizable=False, title="Cartridges — aviso")
        self.add_css_class("conquista-aviso")
        if not janela_por_cima.FUNDO_TRANSPARENTE:
            self.add_css_class("conquista-aviso-opaco")
        self.titulo = aviso.titulo
        self._destruida = False
        self._animacao: Optional[Adw.TimedAnimation] = None

        cartao = Gtk.Box(spacing=12, css_classes=["conquista-aviso-cartao"])
        self._imagem = Gtk.Image(pixel_size=48, css_classes=["conquistas-icone"])
        if aviso.icone:
            icones.carregar(aviso.icone, self._icone_chegou)
        else:
            self._imagem.set_from_icon_name("starred-symbolic")
        cartao.append(self._imagem)

        textos = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
        for texto, classes in (
            (aviso.rotulo, ["caption", "conquista-aviso-rotulo"]),
            (aviso.titulo, ["heading"]),
            (aviso.descricao, ["caption", "dim-label"]),
        ):
            if texto:
                rotulo = Gtk.Label(
                    label=texto,
                    xalign=0,
                    wrap=True,
                    max_width_chars=36,
                    use_markup=False,
                    css_classes=classes,
                )
                textos.append(rotulo)
        cartao.append(textos)
        self.cartao = cartao
        self.set_child(cartao)

    def _icone_chegou(self, textura: Any) -> None:
        """O ícone chega depois, na thread principal; a janela pode já ter fechado."""
        if not self._destruida:
            self._imagem.set_from_paintable(textura)

    def entrar(self, canto: str) -> None:
        self.realize()
        if not janela_por_cima.preparar(self):
            # Sem os estilos o cartão ativaria e tiraria o jogo da tela cheia:
            # quem chama descarta a janela, que nunca chegou a ser mostrada.
            raise RuntimeError("a janela do aviso não pôde ser preparada")
        self.cartao.set_opacity(0)
        self.set_visible(True)
        janela_por_cima.por_no_canto(self, canto)
        self._animar(0, 1)

    def sair(self, ao_terminar: Callable[[], None]) -> None:
        """Some com o cartão (opacidade 1 → 0) e chama ``ao_terminar`` no fim."""
        if not self._destruida:
            self._animar(1, 0, ao_terminar)

    def _animar(
        self, de: float, para: float, ao_terminar: Optional[Callable[[], None]] = None
    ) -> None:
        animacao = Adw.TimedAnimation(
            widget=self.cartao,
            value_from=de,
            value_to=para,
            duration=_ENTRADA_MS,
            target=Adw.PropertyAnimationTarget.new(self.cartao, "opacity"),
        )
        if ao_terminar is not None:
            animacao.connect("done", lambda _a: None if self._destruida else ao_terminar())
        self._animacao = animacao
        animacao.play()

    def fechar(self) -> None:
        self._destruida = True
        self._animacao = None
        self.destroy()


_fila: deque[Aviso] = deque()
_atual: Optional[_JanelaDoAviso] = None
_vez = 0  # muda a cada aviso: o temporizador de um aviso já fechado não fecha o seguinte


def na_tela() -> Optional[str]:
    """O título do aviso visível agora (para teste e diagnóstico)."""
    return _atual.titulo if _atual is not None else None


def mostrar(aviso: Aviso) -> None:
    """Põe o aviso na fila; aparece já se não houver outro na tela."""
    _fila.append(aviso)
    if _atual is None:
        _proximo()


def _proximo() -> bool:
    global _atual, _vez  # pylint: disable=global-statement
    if _atual is not None or not _fila:
        return False
    aviso = _fila.popleft()
    _vez += 1
    vez = _vez
    janela: Optional[_JanelaDoAviso] = None
    try:
        janela = _JanelaDoAviso(aviso)
        janela.entrar(shared.schema.get_string("conquistas-aviso-posicao"))
        _atual = janela
        _tocar_som()
        _agendar(DURACAO, lambda: _esconder(vez))
    except Exception:  # pylint: disable=broad-exception-caught
        logging.warning("Não foi possível mostrar o aviso de conquista", exc_info=True)
        _atual = None
        _destruir(janela)
        if _fila:
            # Fora desta chamada, para uma falha repetida não empilhar recursão
            GLib.idle_add(_proximo)
    return False


def _destruir(janela: Optional[_JanelaDoAviso]) -> None:
    if janela is None:
        return
    try:
        janela.fechar()
    except Exception:  # pylint: disable=broad-exception-caught
        logging.warning("Falha ao fechar o aviso de conquista", exc_info=True)


def _esconder(vez: int) -> bool:
    """O tempo do aviso acabou: ele sai animado; o próximo só entra depois."""
    try:
        if vez != _vez or _atual is None:
            return False
        janela = _atual
        # Se a animação nunca terminar (janela encoberta, sem quadros), a fila não pode travar.
        _agendar(_LIMITE_DA_SAIDA, lambda: _forcar_saida(vez, janela))
        try:
            janela.sair(lambda: _saiu(vez, janela))
        except Exception:  # pylint: disable=broad-exception-caught
            logging.warning("Falha na saída do aviso de conquista", exc_info=True)
            _saiu(vez, janela)
    except Exception:  # pylint: disable=broad-exception-caught
        logging.warning("Falha ao fechar o aviso de conquista", exc_info=True)
    return False


def _forcar_saida(vez: int, janela: _JanelaDoAviso) -> bool:
    _saiu(vez, janela)
    return False


def _saiu(vez: int, janela: _JanelaDoAviso) -> None:
    """A saída terminou: a janela se vai e o próximo aviso entra."""
    global _atual  # pylint: disable=global-statement
    try:
        if vez != _vez or _atual is not janela:
            return  # `fechar` (ou outra troca) já cuidou desta janela
        _atual = None
        _destruir(janela)
        _proximo()
    except Exception:  # pylint: disable=broad-exception-caught
        logging.warning("Falha ao fechar o aviso de conquista", exc_info=True)


def fechar() -> None:
    """Fim da sessão ou do app: nada na fila, nada na tela. Nunca levanta."""
    global _atual, _vez  # pylint: disable=global-statement
    _fila.clear()
    _vez += 1
    janela, _atual = _atual, None
    _destruir(janela)
