"""A janela do aviso de conquista: um `QQuickView` sem moldura que mostra o `CartaoDoAviso.qml`."""

import weakref
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtCore import QTimer, QUrl, Qt
from PySide6.QtGui import QColor
from PySide6.QtQuick import QQuickView

from cartridges import shared
from cartridges.conquistas import icones
from cartridges.modelos.provedor_de_icones import ProvedorDeIcones
from cartridges.utils import janela_por_cima

_CARTAO = Path(__file__).resolve().parent / "qml" / "CartaoDoAviso.qml"

_FLAGS = (
    Qt.WindowType.Tool
    | Qt.WindowType.FramelessWindowHint
    | Qt.WindowType.WindowStaysOnTopHint
    | Qt.WindowType.WindowDoesNotAcceptFocus
    | Qt.WindowType.WindowTransparentForInput
)


def _icone_chegou(ref: "weakref.ref[JanelaDoAviso]", caminho: Path) -> None:
    """O arquivo do ícone chega na thread principal; a janela pode já ter fechado."""
    janela = ref()
    if janela is not None and not janela._destruida:  # pylint: disable=protected-access
        janela.cartao.setProperty("icone", QUrl.fromLocalFile(str(caminho)).toString())


class JanelaDoAviso(QQuickView):
    """O contrato do `conquista_aviso`: `titulo`, `entrar(canto)`, `sair(ao_terminar)` e `fechar()`."""

    def __init__(self, aviso) -> None:  # noqa: ANN001 - o `Aviso` do conquista_aviso (import circular)
        super().__init__()
        self.titulo = aviso.titulo
        self._destruida = False
        self._ao_terminar: Optional[Callable[[], None]] = None
        self.setTitle("Kyron — aviso")
        self.setFlags(_FLAGS)
        opaco = not janela_por_cima.FUNDO_TRANSPARENTE
        if opaco:
            self.setColor(QColor("#1c1b22"))
        else:
            formato = self.format()
            formato.setAlphaBufferSize(8)
            self.setFormat(formato)
            self.setColor(QColor(Qt.GlobalColor.transparent))
        self.setResizeMode(QQuickView.ResizeMode.SizeRootObjectToView)
        self.engine().addImageProvider("icone", ProvedorDeIcones())
        # A estrela é só do aviso sem ícone; com ele a caminho (ou que falhou), fica o quadrado vazio.
        animar = getattr(shared.aplicativo, "animacoesDoSistema", True) is not False
        self.setInitialProperties(
            {
                "rotulo": aviso.rotulo, "titulo": aviso.titulo, "descricao": aviso.descricao, "opaco": opaco,
                "semIcone": not aviso.icone, "animar": animar,
            }
        )
        self.setSource(QUrl.fromLocalFile(str(_CARTAO)))
        self.cartao = self.rootObject()
        if self.cartao is None:
            erros = "; ".join(erro.toString() for erro in self.errors())
            self._destruida = True
            self.deleteLater()
            raise RuntimeError(f"o cartão do aviso não carregou: {erros}")
        self.resize(round(self.cartao.implicitWidth()), round(self.cartao.implicitHeight()))
        self.cartao.terminou.connect(self._terminou)
        if aviso.icone:
            ref = weakref.ref(self)
            icones.carregar(aviso.icone, lambda caminho: _icone_chegou(ref, caminho))

    def entrar(self, canto: str) -> None:
        self.create()
        if not janela_por_cima.preparar(self):
            # Sem os estilos o cartão ativaria e tiraria o jogo da tela cheia: quem chama descarta a janela, que nunca
            # chegou a ser mostrada.
            raise RuntimeError("a janela do aviso não pôde ser preparada")
        self.cartao.setProperty("opacidade", 0.0)
        janela_por_cima.mostrar_sem_tomar_o_foco(self)
        janela_por_cima.por_no_canto(self, canto)
        self.cartao.setProperty("mostrado", True)

    def sair(self, ao_terminar: Callable[[], None]) -> None:
        """Some com o cartão (opacidade 1 → 0) e chama ``ao_terminar`` no fim."""
        if self._destruida:
            return
        self._ao_terminar = ao_terminar
        self.cartao.setProperty("mostrado", False)

    def _terminou(self) -> None:
        if self._destruida or self._ao_terminar is None or self.cartao.property("mostrado"):
            return
        ao_terminar, self._ao_terminar = self._ao_terminar, None
        ref = weakref.ref(self)

        def chamar() -> None:
            janela = ref()
            if janela is not None and not janela._destruida:  # pylint: disable=protected-access
                ao_terminar()

        # Fora do sinal da animação: quem recebe fecha esta janela, e o cartão não pode ser apagado no meio da própria
        # emissão.
        QTimer.singleShot(0, chamar)

    def fechar(self) -> None:
        if self._destruida:
            return
        self._destruida = True
        self._ao_terminar = None
        try:
            self.destroy()
        finally:
            self.deleteLater()

