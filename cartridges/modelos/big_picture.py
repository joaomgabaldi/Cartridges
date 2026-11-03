# big_picture.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O que a tela do Big Picture lê: a lista de jogos, o jogo central e o fundo.

`BigPicture` segue o `ModeloDaBiblioteca` (a mesma lista que a grade mostra, ordenada do jogado
mais recentemente ao mais antigo) e guarda o índice do jogo central; o QML só lê as propriedades e
chama os slots de navegação. `ProvedorDoFundo` entrega o degradê pontilhado em pixels reais.
"""

import logging
import weakref

from collections.abc import Callable

from PySide6.QtCore import (
    Property, QEasingCurve, QModelIndex, QObject, QSize, Qt, QTimer, QVariantAnimation, Signal, Slot,
)  # fmt: skip
from PySide6.QtGui import QColor, QImage, QWindow
from PySide6.QtQuick import QQuickImageProvider, QSGRendererInterface

from cartridges import shared
from cartridges.modelos import regras_do_big_picture as regras
from cartridges.modelos.biblioteca import ModeloDaBiblioteca
from cartridges.modelos.ordem import Linha
from cartridges.utils.cortina_monitor import CortinaMonitor

_SO_CAPA = {ModeloDaBiblioteca.Papel.Capa, ModeloDaBiblioteca.Papel.CapaAnimada}

# Fade do monitor (valores da `main`): escurece em 300 ms (entrada) ou 250 ms (saída), troca no
# escuro, espera 120 ms e clareia em 350 ms, InOutCubic.
ESCURECER_ENTRADA_MS = 300
ESCURECER_SAIDA_MS = 250
PAUSA_NO_ESCURO_MS = 120
CLAREAR_MS = 350
# P1: no escuro, a troca espera as capas da fila decodificadas, mas não mais que isto.
ESPERA_MAXIMA_DAS_CAPAS_MS = 700


class ProvedorDoFundo(QQuickImageProvider):
    """`image://fundo/LxA`: o degradê pontilhado no tamanho em pixels reais."""

    def __init__(self) -> None:
        super().__init__(QQuickImageProvider.ImageType.Image)

    def requestImage(self, id_: str, size: QSize, requested_size: QSize) -> QImage:  # noqa: ARG002, N802
        try:
            largura, altura = (max(1, int(v)) for v in id_.split("x"))
            dados = regras.bytes_do_fundo(largura, altura)  # vivo até o .copy(): o QImage não copia
            imagem = QImage(dados, largura, altura, largura * 3, QImage.Format.Format_RGB888).copy()
        except Exception:
            logging.warning("Falha ao gerar o fundo do Big Picture", exc_info=True)
            imagem = QImage(1, 1, QImage.Format.Format_RGB888)
            imagem.fill(QColor("black"))
        size.setWidth(imagem.width())
        size.setHeight(imagem.height())
        return imagem


def tem_3d(janela: QWindow) -> bool:
    """Sem renderizador, ou com o de software, o Cover Flow não roda bem."""
    renderizador = janela.rendererInterface()
    return renderizador is not None and renderizador.graphicsApi() != QSGRendererInterface.GraphicsApi.Software


def _dados(linha: Linha) -> dict[str, str]:
    return {
        "jogoId": linha.jogo_id,
        "nome": linha.nome,
        "desenvolvedora": linha.desenvolvedora,
        "capa": linha.capa,
        "capaAnimada": linha.capa_animada,
    }


class BigPicture(QObject):
    """A lista do Big Picture e o jogo central. Só na thread principal."""

    alterado = Signal()  # índice, rótulos, vazia, ocupada
    jogosMudaram = Signal()  # noqa: N815  # só a lista (um passo do carrossel não a notifica)
    animarCentralMudou = Signal()  # noqa: N815
    filaPedida = Signal(bool)  # noqa: N815  # True: a fila de entrada; False: a de saída (o QML a anima)
    saiu = Signal(str)  # o jogo central na saída: o foco volta ao cartão dele na grade
    prepararCapas = Signal()  # noqa: N815  # P1: o QML decodifica as capas da fila e responde `capasProntas`
    aberturaPedida = Signal(float, float)  # noqa: N815  # (de, para): o QML anima `progressoAbertura` e responde `aberturaTerminou`
    focoPedido = Signal()  # noqa: N815  # o bloqueio do jogo levou o foco: a camada o retoma

    def __init__(
        self,
        modelo: ModeloDaBiblioteca,
        parent: QObject | None = None,
        *,
        animacoes_do_sistema: bool = True,
        fabrica_da_cortina: Callable[[int], CortinaMonitor | None] = CortinaMonitor,
    ) -> None:
        super().__init__(parent)
        # Fade do monitor (ADR 0003): a cortina, a animação do alfa, a etapa e a troca em curso.
        self._fabrica_da_cortina = fabrica_da_cortina
        self._cortina: CortinaMonitor | None = None
        self._animacao_cortina: QVariantAnimation | None = None
        self._etapa = ""  # "escurecendo", "esperando capas", "trocando", "pausa", "clareando"
        self._trocar: Callable[[], None] | None = None
        self._depois: Callable[[], None] | None = None
        self._em_fade = False
        self._na_fila = False
        self._capas_prontas = True
        self._pausa = QTimer(self, singleShot=True, interval=PAUSA_NO_ESCURO_MS)
        self._pausa.timeout.connect(self._clarear)
        self._espera_das_capas = QTimer(self, singleShot=True, interval=ESPERA_MAXIMA_DAS_CAPAS_MS)
        self._espera_das_capas.timeout.connect(self._trocar_agora)
        # As animações do Windows: lidas pelo `Aplicativo` e relidas a cada `WM_SETTINGCHANGE` (D88, `definir_animacoes_do_sistema`).
        self._animacoes_do_sistema = animacoes_do_sistema
        self._animar_central = self._ler_animar_central()
        eu = weakref.ref(self)
        shared.schema.connect("changed::cover-autoplay", lambda *_: (b := eu()) and b._religar_animar_central())
        self._modelo = modelo
        self._carrossel = regras.Carrossel([])
        self._jogos: list[dict[str, str]] = []
        self._agendado = False
        self._ocupada = False  # a fila de entrada e saída
        self._visivel = False
        self._montada = False  # a lista existe: da entrada (antes de escurecer) ao fim da saída
        self._saindo = False
        self._ja_saiu = False
        self._disponivel = True
        self._janela: QWindow | None = None
        self._estava_maximizada = False
        self._pendente = False
        self._centro_pendente = ""
        self._jogo_aberto = ""  # o jogo que a abertura em curso inicia
        self._indo = False  # a animação de ida (a volta não lança nada)
        self._esperando_ativacao = False
        modelo.rowsInserted.connect(self._agendar)
        modelo.rowsRemoved.connect(self._agendar)
        modelo.modelReset.connect(self._agendar)
        modelo.dataChanged.connect(self._dados_mudaram)

    # --- propriedades ---
    @Property("QVariantList", notify=jogosMudaram)
    def jogos(self) -> list[dict[str, str]]:
        return self._jogos

    @Property(int, notify=alterado)
    def indice(self) -> int:
        return self._carrossel.indice

    def _central(self) -> dict[str, str] | None:
        return self._jogos[self._carrossel.indice] if self._jogos else None

    @Property(str, notify=alterado)
    def nome(self) -> str:
        return (self._central() or {}).get("nome", "")

    @Property(str, notify=alterado)
    def desenvolvedora(self) -> str:
        return (self._central() or {}).get("desenvolvedora", "")

    @Property(str, constant=True)
    def placeholder(self) -> str:
        """A imagem da capa que falta: a mesma da grade."""
        return self._modelo.placeholder

    @Property(bool, notify=alterado)
    def vazia(self) -> bool:
        return not self._jogos

    @Property(bool, notify=alterado)
    def ocupada(self) -> bool:
        return self._ocupada

    @Property(int, constant=True)
    def jogosNaFila(self) -> int:  # noqa: N802
        return regras.JOGOS_NA_FILA

    @Property(bool, notify=alterado)
    def animacoes(self) -> bool:
        """As animações do Windows estão ativas: sem elas a fila e o passo vão direto ao fim."""
        return self._animacoes_do_sistema

    @Property(bool, notify=alterado)
    def visivel(self) -> bool:
        return self._visivel

    @Property(bool, notify=alterado)
    def disponivel(self) -> bool:
        return self._disponivel

    @Property(bool, notify=alterado)
    def jaSaiu(self) -> bool:  # noqa: N802
        """O usuário saiu do Big Picture nesta sessão: a entrada automática não volta."""
        return self._ja_saiu

    def definir_animacoes_do_sistema(self, ligadas: bool) -> None:
        """O ajuste do Windows mudou com o app aberto (D88): a fila e o passo seguem."""
        if ligadas == self._animacoes_do_sistema:
            return
        self._animacoes_do_sistema = ligadas
        self.alterado.emit()  # a capa central não muda com isto: só a preferência manda nela (BP-15)

    def _ler_animar_central(self) -> bool:
        # Só a preferência (`big_picture.py:288` da `main`); as animações do sistema valem para a grade.
        return shared.schema.get_boolean("cover-autoplay")

    def _religar_animar_central(self) -> None:
        animar = self._ler_animar_central()
        if animar != self._animar_central:
            self._animar_central = animar
            self.animarCentralMudou.emit()

    @Property(bool, notify=animarCentralMudou)
    def animarCentral(self) -> bool:  # noqa: N802
        """A capa animada do jogo central toca: `cover-autoplay` ligado."""
        return self._animar_central

    # --- a lista segue o modelo ---
    def _refazer(self, centro: str = "") -> None:
        linhas = regras.jogos_da_biblioteca(self._modelo.linhas())
        self._carrossel.trocar_lista([linha.jogo_id for linha in linhas], centro or None)
        self._jogos = [_dados(linha) for linha in linhas]
        self.jogosMudaram.emit()
        self.alterado.emit()

    @Slot()
    @Slot(str)
    def atualizar(self, centro: str = "") -> None:
        """Refaz a lista mantendo o jogo central (ou `centro`); se ele sumiu, fica o vizinho.

        Só vale com a lista montada e fora da saída; durante a fila e o fade fica pendente (só o
        centro mais recente) e roda quando a página destrava.
        """
        if not self._montada or self._saindo:
            return
        if self._ocupada:
            self._pendente, self._centro_pendente = True, centro
            return
        self._refazer(centro)

    def _agendar(self, *_args: object) -> None:
        """Várias mudanças seguidas (uma importação) viram um só `atualizar` no próximo ciclo."""
        if self._montada and not self._agendado:
            self._agendado = True
            QTimer.singleShot(0, self, self._rodar_agendado)

    def _rodar_agendado(self) -> None:
        self._agendado = False
        self.atualizar()

    def _dados_mudaram(self, topo: QModelIndex, base: QModelIndex, papeis: list[int]) -> None:
        if not papeis or not set(papeis) <= _SO_CAPA:
            self._agendar()
            return
        # O `soltar_copia` manda o `DeferredDelete` logo depois do sinal: a capa animada precisa
        # sair daqui já (D39), sem esperar o ciclo.
        por_id = {jogo["jogoId"]: jogo for jogo in self._jogos}
        for i in range(topo.row(), base.row() + 1):
            linha = self._modelo.linha(i)
            if (jogo := por_id.get(linha.jogo_id)) is not None:
                jogo.update(capa=linha.capa, capaAnimada=linha.capa_animada)
        self.jogosMudaram.emit()

    # --- navegação ---
    def _foi_para(self, mudou: bool) -> bool:  # noqa: FBT001
        if mudou:
            regras.tocar_tique()
            self.alterado.emit()
        return mudou

    @Slot(int, result=bool)
    def mover(self, delta: int) -> bool:
        return not self._ocupada and self._foi_para(self._carrossel.mover(delta))

    @Slot(int, result=bool)
    def irPara(self, indice: int) -> bool:  # noqa: N802
        return not self._ocupada and self._foi_para(self._carrossel.ir_para(indice))

    @Slot(result=bool)
    def inicio(self) -> bool:
        return not self._ocupada and self._foi_para(self._carrossel.inicio())

    @Slot(result=bool)
    def fim(self) -> bool:
        return not self._ocupada and self._foi_para(self._carrossel.fim())

    # --- entrar e sair ---
    def definir_janela(self, janela: QWindow) -> None:
        """A janela que vai à tela cheia; o Big Picture só fica disponível com renderizador 3D."""
        self._janela = janela
        self._rever_3d()
        sinal = getattr(janela, "sceneGraphInitialized", None)
        if sinal is not None:  # o renderizador só existe depois do primeiro quadro (na thread de render)
            sinal.connect(self._rever_3d, Qt.ConnectionType.QueuedConnection)

    @Slot()
    def _rever_3d(self) -> None:
        janela = self._janela
        if janela is None or janela.rendererInterface() is None:  # ainda sem renderizador: segue disponível
            return
        disponivel = tem_3d(janela)
        if disponivel != self._disponivel:
            self._disponivel = disponivel
            self.alterado.emit()


    @Slot()
    def entrar(self) -> None:
        if self._visivel or self._ocupada or not self._disponivel:
            return
        self._carrossel = regras.Carrossel([])  # sem centro a manter
        self._montada = True
        self._refazer()  # o jogado mais recentemente no centro
        self._pendente = False
        self._ocupada = self._em_fade = True
        self._capas_prontas = not self._jogos
        self.alterado.emit()
        if self._jogos:
            self.prepararCapas.emit()  # antes de escurecer: o QML decodifica enquanto a cortina desce (P1)
        self._trocar_no_escuro(self._entrar_de_fato, ESCURECER_ENTRADA_MS, self._fim_da_entrada)

    def _entrar_de_fato(self) -> None:
        self._visivel = True
        if self._janela is not None:
            self._estava_maximizada = self._janela.visibility() == QWindow.Visibility.Maximized
            self._janela.showFullScreen()  # o Windows não devolve o estado maximizado sozinho (na saída)
        self._na_fila = bool(self._jogos)
        self.alterado.emit()
        if self._na_fila:
            self.filaPedida.emit(True)  # noqa: FBT003  # corre no escuro e enquanto clareia

    def _fim_da_entrada(self) -> None:
        self._em_fade = False
        self._destravar()

    def _destravar(self) -> None:
        """Fila e fade acabaram: a página volta a aceitar entrada e aplica o `atualizar` pendente."""
        if self._na_fila or self._em_fade:
            return
        self._ocupada = False
        pendente, centro = self._pendente, self._centro_pendente
        self._pendente = False
        self.alterado.emit()
        if pendente:
            self.atualizar(centro)

    @Slot()
    def sair(self) -> None:
        if self._ocupada or not self._visivel:
            return
        self._saindo = self._ocupada = True
        self._capas_prontas = True  # a saída não espera capas
        self._na_fila = bool(self._jogos)
        self.alterado.emit()
        if self._na_fila:
            self.filaPedida.emit(False)  # noqa: FBT003
        else:
            self._trocar_no_escuro(self._sair_de_fato, ESCURECER_SAIDA_MS, self._fim_da_saida)

    @Slot()
    def filaTerminou(self) -> None:  # noqa: N802
        """O QML avisa que a fila (de entrada ou de saída) chegou ao fim."""
        if not self._na_fila:
            return
        self._na_fila = False
        if self._saindo:
            self._trocar_no_escuro(self._sair_de_fato, ESCURECER_SAIDA_MS, self._fim_da_saida)
        else:
            self._destravar()

    def _sair_de_fato(self) -> None:
        jogo = (self._central() or {}).get("jogoId", "")
        try:
            if self._janela is not None:
                if self._estava_maximizada:
                    self._janela.showMaximized()
                else:
                    self._janela.showNormal()
        finally:
            # Mesmo com a troca falhando a camada some: o QML repõe o quadro ao esconder.
            self._visivel = self._montada = False
            self._ja_saiu = True
            self._carrossel, self._jogos = regras.Carrossel([]), []  # fora da tela nada decodifica capa (D39)
            self.jogosMudaram.emit()
            self.alterado.emit()
            self.saiu.emit(jogo)  # o foco volta à grade mesmo se a troca levantou

    def _fim_da_saida(self) -> None:
        self._saindo = self._ocupada = self._pendente = False
        self.alterado.emit()

    # --- entrada automática ---
    @Slot(bool)
    def controleConectado(self, grade_a_vista: bool) -> None:  # noqa: FBT001, N802
        """Um controle foi conectado: entra sozinho se a preferência e o momento permitirem."""
        if regras.pode_entrar_sozinho(
            preferencia=shared.schema.get_boolean("big-picture-ao-conectar"),
            controle_ligado=shared.schema.get_boolean("gamepad"),
            tem_3d=self._disponivel,
            grade_a_vista=grade_a_vista,
            ja_saiu=self._ja_saiu,
        ):
            self.entrar()

    # --- abrir o jogo ---
    @Slot()
    def abrirJogo(self) -> None:  # noqa: N802
        if (central := self._central()) is not None:
            self._abrir(central["jogoId"])

    def _abrir(self, jogo_id: str) -> None:
        if self._ocupada or not self._visivel:
            return
        self._ocupada = self._indo = True
        self._jogo_aberto = jogo_id
        self.alterado.emit()
        self.aberturaPedida.emit(0.0, 1.0)

    def _janela_normal(self) -> None:
        # Só sai da tela cheia (`unfullscreen()` da `main`): a maximização volta na saída do Big Picture.
        if self._janela is not None:
            self._janela.showNormal()

    def _voltar_a_tela_cheia(self) -> None:
        if self._janela is not None:
            # Minimizada pelo "Jogar", a janela precisa ser restaurada antes: pedir a tela cheia a uma janela
            # minimizada a devolvia em modo janela, com o Big Picture aberto.
            if self._janela.visibility() == QWindow.Visibility.Minimized:
                self._janela.showNormal()
            self._janela.showFullScreen()

    @Slot()
    def aberturaTerminou(self) -> None:  # noqa: N802
        """O QML avisa que a capa terminou de crescer: sai da tela cheia e inicia o jogo."""
        if not self._indo:
            return  # o fim da volta
        self._indo = False
        self._janela_normal()
        jogo = shared.store.get(self._jogo_aberto) if shared.store is not None else None
        try:
            # Confirmado o comando de um jogo restaurado, abre pelo mesmo caminho. Referência fraca: o
            # callback fica na ponte, que sobrevive a este objeto.
            eu, jogo_id = weakref.ref(self), self._jogo_aberto
            aberto = jogo is not None and jogo.launch(ao_confirmar=lambda: (b := eu()) and b._abrir(jogo_id))
        except Exception:
            self._desistir_da_abertura()
            raise
        if not aberto:
            self._desistir_da_abertura()
        elif shared.sessao is None or not shared.sessao.jogoId:
            self._voltar_sem_sessao()
        # Com sessão, o `ModeloDaSessao` chama `voltouDoJogo` quando ela termina.

    def _desistir_da_abertura(self) -> None:
        """O jogo não abriu (comando a conferir, erro, sumiu): a capa volta e a tela cheia também."""
        self.aberturaPedida.emit(1.0, 0.0)
        self._voltar_a_tela_cheia()
        self._destravar()

    def _reabrir(self) -> None:
        self._pendente, self._centro_pendente = True, self._jogo_aberto  # o jogado agora vai ao centro
        self.aberturaPedida.emit(1.0, 0.0)
        self._destravar()
        self.focoPedido.emit()  # o bloqueio do jogo levou o foco; sem ele o teclado não chega aqui

    @Slot()
    def voltouDoJogo(self) -> None:  # noqa: N802
        # Uma entrada ou saída em curso não é a espera do jogo: ela segue com o próprio `depois`, que uma
        # sequência nova descartaria (`_fechar_cortina`).
        if not self._ocupada or self._em_fade or self._na_fila or self._saindo:
            return
        self._voltar_a_tela_cheia()
        self._reabrir()

    def _voltar_sem_sessao(self) -> None:
        # Com "minimizar ao abrir" o `launch` acabou de minimizar a janela, e `isActive` só muda no
        # ciclo seguinte: não dá para decidir pelo foco. Põe a tela cheia quando ela voltar a ficar ativa.
        self._reabrir()
        if not shared.schema.get_boolean("minimize-after-launch"):
            self._voltar_a_tela_cheia()
        elif self._janela is not None and not self._esperando_ativacao:
            self._esperando_ativacao = True
            self._janela.activeChanged.connect(self._ao_ativar)

    @Slot()
    def _ao_ativar(self) -> None:
        janela = self._janela
        if janela is None or not janela.isActive():
            return
        janela.activeChanged.disconnect(self._ao_ativar)
        self._esperando_ativacao = False
        if self._visivel:
            self._voltar_a_tela_cheia()

    # --- fade do monitor (ADR 0003) ---
    def _hwnd(self) -> int:
        return int(self._janela.winId()) if self._janela is not None else 0

    def _trocar_no_escuro(
        self, trocar: Callable[[], None], ms_escurecer: int, depois: Callable[[], None] | None
    ) -> None:
        """Escurece o monitor, troca, espera um instante e clareia. Sem cortina, só troca.

        Na entrada, a troca no escuro espera `capasProntas` (ou `ESPERA_MAXIMA_DAS_CAPAS_MS`).
        """
        self._fechar_cortina()  # nunca deixa uma cortina anterior órfã
        cortina = None
        hwnd = self._hwnd()
        if hwnd:
            try:
                cortina = self._fabrica_da_cortina(hwnd)
            except Exception:
                logging.warning("Não foi possível criar a cortina do monitor", exc_info=True)
        if cortina is None:
            try:
                trocar()
            finally:
                if depois is not None:
                    depois()
            return
        self._cortina, self._trocar, self._depois = cortina, trocar, depois
        self._animar_cortina(0.0, 1.0, ms_escurecer, "escurecendo")

    def _animar_cortina(self, de: float, para: float, ms: int, etapa: str) -> None:
        self._etapa = etapa
        if not self._animacoes_do_sistema:  # direto ao fim, como a `Adw.TimedAnimation`
            self._alfa_cortina(para)
            self._animacao_terminou()
            return
        animacao = QVariantAnimation(self)
        animacao.setStartValue(de)
        animacao.setEndValue(para)
        animacao.setDuration(ms)
        animacao.setEasingCurve(QEasingCurve.Type.InOutCubic)
        animacao.valueChanged.connect(self._alfa_cortina)
        animacao.finished.connect(self._animacao_terminou)
        self._animacao_cortina = animacao
        self._alfa_cortina(de)
        animacao.start()

    def _animacao_terminou(self) -> None:
        animacao, self._animacao_cortina = self._animacao_cortina, None
        if animacao is not None:
            animacao.deleteLater()
        if self._etapa == "escurecendo":
            if self._capas_prontas:
                self._trocar_agora()
            else:
                self._etapa = "esperando capas"
                self._espera_das_capas.start()
        elif self._etapa == "clareando":
            depois = self._depois
            self._fechar_cortina()
            if depois is not None:
                depois()

    @Slot()
    def capasProntas(self) -> None:  # noqa: N802
        """O QML decodificou as capas da fila (ou não tinha o que decodificar)."""
        self._capas_prontas = True
        if self._etapa == "esperando capas":
            self._trocar_agora()

    def _trocar_agora(self) -> None:
        if self._etapa not in {"escurecendo", "esperando capas"}:
            return  # a espera venceu depois de a sequência acabar
        self._espera_das_capas.stop()
        self._etapa = "trocando"
        trocar, self._trocar = self._trocar, None
        try:
            if trocar is not None:
                trocar()
        except BaseException:
            # A cortina preta não pode ficar no monitor nem a página travada (Review Focus 1).
            depois = self._depois
            self._fechar_cortina()
            if depois is not None:
                depois()
            raise
        self._etapa = "pausa"
        self._pausa.start()

    def _clarear(self) -> None:
        if self._etapa == "pausa":
            self._animar_cortina(1.0, 0.0, CLAREAR_MS, "clareando")

    def _alfa_cortina(self, valor: object) -> None:
        if self._cortina is None:
            return
        try:
            self._cortina.alfa(float(valor))
        except OSError:
            logging.warning("Não foi possível mudar a cortina do monitor", exc_info=True)

    def _fechar_cortina(self) -> None:
        self._pausa.stop()
        self._espera_das_capas.stop()
        animacao, self._animacao_cortina = self._animacao_cortina, None
        if animacao is not None:
            animacao.stop()  # parar antes do fim não emite `finished`
            animacao.deleteLater()
        self._etapa = ""
        self._trocar = self._depois = None
        cortina, self._cortina = self._cortina, None
        if cortina is not None:
            cortina.fechar()

    @Slot()
    def encerrar(self) -> None:
        """O app fecha (`aboutToQuit`): nenhuma cortina fica no monitor, em qualquer etapa do fade."""
        self._fechar_cortina()
        self._em_fade = False
