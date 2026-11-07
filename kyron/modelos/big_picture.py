# big_picture.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O que a tela do Big Picture lê: a lista de jogos, o jogo central e o fundo.

`BigPicture` segue o `ModeloDaBiblioteca` (a lista da grade, do jogado mais recentemente ao mais antigo) e guarda o índice do
jogo central; o QML só lê as propriedades e chama os slots de navegação. `ProvedorDoFundo` entrega o degradê pontilhado em
pixels reais.
"""

import logging
import weakref

from collections.abc import Callable

from PySide6.QtCore import (
    Property, QEasingCurve, QModelIndex, QObject, QSize, Qt, QTimer, QVariantAnimation, Signal, Slot,
)  # fmt: skip
from PySide6.QtGui import QColor, QImage, QWindow
from PySide6.QtQuick import QQuickImageProvider, QSGRendererInterface

from kyron import shared
from kyron.modelos import regras_do_big_picture as regras
from kyron.modelos.biblioteca import ModeloDaBiblioteca
from kyron.modelos.detalhes import DetalhesDoJogo
from kyron.modelos.ordem import Linha, _url_da_capa  # noqa: PLC2701
from kyron.utils import game_logo, window_geometry
from kyron.utils.cortina_monitor import CortinaMonitor

_SO_CAPA = {ModeloDaBiblioteca.Papel.Capa, ModeloDaBiblioteca.Papel.CapaAnimada}

# Fade do monitor: escurece em 300 ms (entrada) ou 250 ms (saída), troca no escuro, espera 120 ms e clareia em 350 ms, InOutCubic.
ESCURECER_ENTRADA_MS = 300
ESCURECER_SAIDA_MS = 250
PAUSA_NO_ESCURO_MS = 120
CLAREAR_MS = 350
# Quando a tela da entrada começa a aparecer: a pausa e o trecho do clarear (InOutCubic) até a cortina ficar 20% mais clara.
SOM_DA_ENTRADA_VISIVEL_MS = PAUSA_NO_ESCURO_MS + round(CLAREAR_MS * 0.05 ** (1 / 3))
# No escuro, a troca espera as capas da fila decodificadas, mas não mais que isto.
ESPERA_MAXIMA_DAS_CAPAS_MS = 700
# O painel de detalhes só segue o jogo central depois de o carrossel parar este tempo. Fica acima do atraso da primeira
# repetição do direcional (`REPEAT_DELAY_US`, 400 ms): senão segurar o direcional trocaria o fundo uma vez, contra o design.
ESPERA_DO_CENTRAL_MS = 450


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

    alterado = Signal()
    jogosMudaram = Signal()  # noqa: N815  # só a lista (um passo do carrossel não a notifica)
    animarCentralMudou = Signal()  # noqa: N815
    filaPedida = Signal(bool)  # noqa: N815  # True: a fila de entrada; False: a de saída (o QML a anima)
    saiu = Signal(str)  # o jogo central na saída: o foco volta ao cartão dele na grade
    prepararCapas = Signal()  # noqa: N815  # P1: o QML decodifica as capas da fila e responde `capasProntas`
    etapaPedida = Signal(str, str)  # noqa: N815  # (de, para): o QML anima a troca de etapa e responde `etapaTerminou`
    focoPedido = Signal()  # noqa: N815  # o bloqueio do jogo levou o foco: a camada o retoma

    def __init__(
        self,
        modelo: ModeloDaBiblioteca,
        parent: QObject | None = None,
        *,
        detalhes: DetalhesDoJogo | None = None,
        animacoes_do_sistema: bool = True,
        fabrica_da_cortina: Callable[[int], CortinaMonitor | None] = CortinaMonitor,
    ) -> None:
        super().__init__(parent)
        # Fade do monitor: a cortina, a animação do alfa, a etapa e a troca em curso.
        self._fabrica_da_cortina = fabrica_da_cortina
        self._cortina: CortinaMonitor | None = None
        self._animacao_cortina: QVariantAnimation | None = None
        self._etapa = ""
        self._trocar: Callable[[], None] | None = None
        self._depois: Callable[[], None] | None = None
        self._em_fade = False
        self._na_fila = False
        self._capas_prontas = True
        self._pausa = QTimer(self, singleShot=True, interval=PAUSA_NO_ESCURO_MS)
        self._pausa.timeout.connect(self._clarear)
        self._espera_das_capas = QTimer(self, singleShot=True, interval=ESPERA_MAXIMA_DAS_CAPAS_MS)
        self._espera_das_capas.timeout.connect(self._trocar_agora)
        # As animações do Windows: lidas pelo `Aplicativo` e relidas a cada `WM_SETTINGCHANGE` (`definir_animacoes_do_sistema`).
        self._animacoes_do_sistema = animacoes_do_sistema
        self._animar_central = self._ler_animar_central()
        eu = weakref.ref(self)
        shared.schema.connect("changed::cover-autoplay", lambda *_: (b := eu()) and b._religar_animar_central())
        self._modelo = modelo
        self._detalhes = detalhes
        self._etapa_bp = "carrossel"  # "carrossel", "detalhes" ou "sessao"
        self._transicao: tuple[str, str] | None = None  # a troca de etapa que o QML está animando
        self._espera_do_central = QTimer(self, singleShot=True, interval=ESPERA_DO_CENTRAL_MS)
        self._espera_do_central.timeout.connect(self._mostrar_central)
        if detalhes is not None:
            detalhes.sair.connect(self._detalhes_pediu_saida)
        self._carrossel = regras.Carrossel([])
        self._jogos: list[dict[str, str]] = []
        self._logos: dict[str, str] = {}  # jogo → URL do logo em disco ("" sem logo), lida uma vez por entrada
        self._agendado = False
        self._ocupada = False
        # Confirmação que chegou durante a volta da sessão aos detalhes: (jogo, .ini já conferidos).
        self._reabertura: tuple[str, bool] | None = None
        self._visivel = False
        self._montada = False  # a lista existe: da entrada (antes de escurecer) ao fim da saída
        self._saindo = False
        self._ja_saiu = False
        self._disponivel = True
        self._janela: QWindow | None = None
        self._estava_maximizada = False
        self._pendente = False
        self._centro_pendente = ""
        self._jogo_aberto = ""
        self._indo = False
        # A capa fica aberta esperando a conferência rápida dos .ini; e o relançamento que dela vem.
        self._esperando_inis = False
        self._inis_conferidos = False
        modelo.rowsInserted.connect(self._agendar)
        modelo.rowsRemoved.connect(self._agendar)
        modelo.modelReset.connect(self._agendar)
        modelo.dataChanged.connect(self._dados_mudaram)

    @Property("QVariantList", notify=jogosMudaram)
    def jogos(self) -> list[dict[str, str]]:
        return self._jogos

    @Slot(str, result=str)
    def logoDe(self, jogo_id: str) -> str:  # noqa: N802
        """O logo em disco de um jogo do carrossel: os logos seguem as capas, sem esperar o `detalhes` chegar ao central."""
        if jogo_id not in self._logos:
            jogo = shared.store.get(jogo_id) if shared.store is not None else None
            caminho = game_logo.cached_logo_path(jogo) if jogo is not None else None
            carregado = game_logo.load_logo(caminho) if caminho else None
            self._logos[jogo_id] = _url_da_capa(carregado[0]) if carregado else ""
        return self._logos[jogo_id]

    @Property(int, notify=alterado)
    def indice(self) -> int:
        return self._carrossel.indice

    def _central(self) -> dict[str, str] | None:
        return self._jogos[self._carrossel.indice] if self._jogos else None

    @Property(str, constant=True)
    def placeholder(self) -> str:
        """A imagem da capa que falta: a mesma da grade."""
        return self._modelo.placeholder

    @Property(str, notify=alterado)
    def etapa(self) -> str:
        return self._etapa_bp

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
        """O ajuste do Windows mudou com o app aberto: a fila e o passo seguem."""
        if ligadas == self._animacoes_do_sistema:
            return
        self._animacoes_do_sistema = ligadas
        self.alterado.emit()  # a capa central não muda com isto: só a preferência manda nela

    def _ler_animar_central(self) -> bool:
        # Só a preferência; as animações do sistema valem para a grade.
        return shared.schema.get_boolean("cover-autoplay")

    def _religar_animar_central(self) -> None:
        animar = self._ler_animar_central()
        if animar != self._animar_central:
            self._animar_central = animar
            self.animarCentralMudou.emit()

    @Property(bool, notify=animarCentralMudou)
    def animarCentral(self) -> bool:  # noqa: N802
        return self._animar_central

    def _refazer(self, centro: str = "") -> None:
        linhas = regras.jogos_da_biblioteca(self._modelo.linhas())
        self._carrossel.trocar_lista([linha.jogo_id for linha in linhas], centro or None)
        self._jogos = [_dados(linha) for linha in linhas]
        self.jogosMudaram.emit()
        self.alterado.emit()
        self._seguir_lista_refeita()

    def _seguir_lista_refeita(self) -> None:
        """Se o central da lista refeita não é o jogo dos detalhes, o logo, o fundo e o Iniciar não podem ficar com o antigo."""
        if self._detalhes is None or self._etapa_bp == "sessao":
            return
        central = self._central()
        if central is not None and central["jogoId"] == self._detalhes.jogoId:
            return
        if self._etapa_bp == "detalhes":
            self._pedir_etapa("carrossel")  # o Iniciar lançaria o vizinho, não o jogo mostrado
        elif central is not None:
            self._espera_do_central.start()

    @Slot()
    @Slot(str)
    def atualizar(self, centro: str = "") -> None:
        """Refaz a lista mantendo o jogo central (ou `centro`); se ele sumiu, fica o vizinho. Só vale com a lista montada e
        fora da saída; durante a fila e o fade fica pendente (só o centro mais recente) e roda quando a página destrava.
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
        # O `soltar_copia` manda o `DeferredDelete` logo depois do sinal: a capa animada precisa sair daqui já, sem esperar o ciclo.
        por_id = {jogo["jogoId"]: jogo for jogo in self._jogos}
        for i in range(topo.row(), base.row() + 1):
            linha = self._modelo.linha(i)
            if (jogo := por_id.get(linha.jogo_id)) is not None:
                jogo.update(capa=linha.capa, capaAnimada=linha.capa_animada)
        self.jogosMudaram.emit()

    def _foi_para(self, mudou: bool) -> bool:  # noqa: FBT001
        if mudou:
            regras.tocar_tique()
            self._espera_do_central.start()  # reinicia a cada passo
            self.alterado.emit()
        return mudou

    @Slot(int, result=bool)
    def mover(self, delta: int) -> bool:
        return self._etapa_bp == "carrossel" and not self._ocupada and self._foi_para(self._carrossel.mover(delta))

    @Slot(int, result=bool)
    def irPara(self, indice: int) -> bool:  # noqa: N802
        return self._etapa_bp == "carrossel" and not self._ocupada and self._foi_para(self._carrossel.ir_para(indice))

    @Slot(result=bool)
    def inicio(self) -> bool:
        return self._etapa_bp == "carrossel" and not self._ocupada and self._foi_para(self._carrossel.inicio())

    @Slot(result=bool)
    def fim(self) -> bool:
        return self._etapa_bp == "carrossel" and not self._ocupada and self._foi_para(self._carrossel.fim())

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
        if janela is None or janela.rendererInterface() is None:
            return
        disponivel = tem_3d(janela)
        if disponivel != self._disponivel:
            self._disponivel = disponivel
            self.alterado.emit()

    @Slot()
    def entrar(self) -> None:
        if self._visivel or self._ocupada or not self._disponivel:
            return
        self._carrossel = regras.Carrossel([])
        self._etapa_bp, self._transicao, self._indo = "carrossel", None, False
        self._logos = {}
        self._montada = True
        self._refazer()
        self._mostrar_central()
        self._pendente = False
        self._ocupada = self._em_fade = True
        self._capas_prontas = not self._jogos
        self.alterado.emit()
        if self._jogos:
            self.prepararCapas.emit()  # antes de escurecer: o QML decodifica enquanto a cortina desce
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
            self._embaralhar(entrar=True)

    def _embaralhar(self, *, entrar: bool) -> None:
        """O som da fila: um flip por capa que passa (as mesmas `n` do QML); sem animações, a fila não corre."""
        if self._animacoes_do_sistema:
            n = min(regras.JOGOS_NA_FILA, max(0, len(self._jogos) - 1))
            passam = None if entrar else len(self._jogos) - 1 - self._carrossel.indice
            # Na entrada com cortina a fila começa no preto: as capas que passam antes de a tela aparecer não soam.
            no_escuro = entrar and self._cortina is not None
            desde = SOM_DA_ENTRADA_VISIVEL_MS / regras.DURACAO_FILA_ENTRADA_MS if no_escuro else 0.0
            regras.tocar_embaralhar(n, entrar=entrar, passam=passam, desde=desde)

    def _fim_da_entrada(self) -> None:
        self._em_fade = False
        self._destravar()

    def _destravar(self) -> None:
        """Fila e fade acabaram: a página volta a aceitar entrada e aplica o `atualizar` pendente."""
        if self._na_fila or self._em_fade or self._transicao is not None:
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
        self._reabertura = None
        self._capas_prontas = True
        self._na_fila = bool(self._jogos)
        self.alterado.emit()
        if self._na_fila:
            self.filaPedida.emit(False)  # noqa: FBT003
            self._embaralhar(entrar=False)
        else:
            self._trocar_no_escuro(self._sair_de_fato, ESCURECER_SAIDA_MS, self._fim_da_saida)

    @Slot()
    def filaTerminou(self) -> None:  # noqa: N802
        if not self._na_fila:
            return
        self._na_fila = False
        if self._saindo:
            self._trocar_no_escuro(self._sair_de_fato, ESCURECER_SAIDA_MS, self._fim_da_saida)
        else:
            self._destravar()

    def _sair_de_fato(self) -> None:
        jogo = (self._central() or {}).get("jogoId", "")
        self._espera_do_central.stop()
        if self._detalhes is not None:
            self._detalhes.esquecer()
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
            self._carrossel, self._jogos = regras.Carrossel([]), []  # fora da tela nada decodifica capa
            self.jogosMudaram.emit()
            self.alterado.emit()
            self.saiu.emit(jogo)  # o foco volta à grade mesmo se a troca levantou

    def _fim_da_saida(self) -> None:
        self._saindo = self._ocupada = self._pendente = False
        self.alterado.emit()

    @Slot(bool)
    def controleConectado(self, grade_a_vista: bool) -> None:  # noqa: FBT001, N802
        if regras.pode_entrar_sozinho(
            preferencia=shared.schema.get_boolean("big-picture-ao-conectar"),
            controle_ligado=shared.schema.get_boolean("gamepad"),
            tem_3d=self._disponivel,
            grade_a_vista=grade_a_vista,
            ja_saiu=self._ja_saiu,
        ):
            self.entrar()

    def _pedir_etapa(self, para: str) -> None:
        """Muda de etapa: a página fica ocupada até o QML terminar a animação (`etapaTerminou`)."""
        de, self._etapa_bp = self._etapa_bp, para
        self._reabertura = None  # uma confirmação pendente só vale para a volta em que chegou
        self._transicao, self._ocupada = (de, para), True
        if para != "sessao":
            self._indo = False
        self.alterado.emit()
        self.etapaPedida.emit(de, para)

    def _mostrar_central(self) -> bool:
        """Mostra o jogo central nos detalhes (sem esperar o timer) e devolve se havia o que mostrar."""
        self._espera_do_central.stop()
        # O logo baixado nesta entrada: sem isto, voltar a esse jogo mostraria o nome até o `detalhes` chegar.
        if self._detalhes is not None and self._detalhes.logo:
            self._logos[self._detalhes.jogoId] = self._detalhes.logo
        central = self._central()
        if central is None:
            return False
        return self._detalhes is None or self._detalhes.mostrar(central["jogoId"])

    def _detalhes_pediu_saida(self) -> None:
        """O jogo dos detalhes foi excluído."""
        if self._etapa_bp == "detalhes":
            self._pedir_etapa("carrossel")
        elif self._esperando_inis:
            # O jogo sumiu durante a conferência dos .ini: sem isto a capa ficaria aberta para sempre.
            self._esperando_inis = False
            self._desistir_da_abertura()

    @Slot()
    def ativar(self) -> None:
        if self._etapa_bp == "sessao":
            if shared.sessao is not None and shared.sessao.emAndamento:
                shared.sessao.terminar()
        elif self._ocupada or not self._visivel:
            return
        elif self._etapa_bp == "carrossel":
            if self._mostrar_central():  # `selecionar`: os detalhes do central, já
                self._pedir_etapa("detalhes")
        else:
            self.abrirJogo()

    @Slot()
    def voltar(self) -> None:
        if self._etapa_bp == "carrossel":
            self.sair()
        elif self._etapa_bp == "detalhes" and not self._ocupada:
            self._pedir_etapa("carrossel")

    @Slot()
    def etapaTerminou(self) -> None:  # noqa: N802
        transicao, self._transicao = self._transicao, None
        if transicao == ("detalhes", "sessao"):
            self._lancar()
        elif transicao is not None:
            self._destravar()
            if transicao[1] == "carrossel":
                self._seguir_lista_refeita()  # a lista pode ter mudado durante os detalhes ou a sessão
            if transicao == ("sessao", "detalhes") and (pendente := self._reabertura) is not None:
                self._reabertura = None
                if self._visivel and self._etapa_bp == "detalhes":
                    self._continuar_abertura(*pendente)

    @Slot()
    def abrirJogo(self) -> None:  # noqa: N802
        if self._etapa_bp == "detalhes" and (central := self._central()) is not None:
            self._abrir(central["jogoId"])

    def _abrir(self, jogo_id: str) -> None:
        if self._ocupada or not self._visivel or self._etapa_bp != "detalhes":
            return
        self._indo = True
        self._jogo_aberto = jogo_id
        self._inis_conferidos = False
        self._pedir_etapa("sessao")

    def _voltar_a_tela_cheia(self) -> None:
        if self._janela is not None:
            # Se a janela ficou minimizada durante o jogo, ela precisa ser restaurada antes: pedir a tela cheia a uma janela minimizada a devolvia em modo janela.
            if self._janela.visibility() == QWindow.Visibility.Minimized:
                self._janela.showNormal()
            self._janela.showFullScreen()

    def _lancar(self) -> None:
        if not self._indo:
            return
        self._indo = False
        jogo = shared.store.get(self._jogo_aberto) if shared.store is not None else None
        conferidos, self._inis_conferidos = self._inis_conferidos, False
        try:
            # Confirmado o comando de um jogo restaurado, abre pelo mesmo caminho; referência fraca: o callback fica na ponte, que sobrevive a este objeto.
            eu, jogo_id = weakref.ref(self), self._jogo_aberto
            aberto = jogo is not None and jogo.launch(
                ao_confirmar=lambda: (b := eu()) and b._continuar_abertura(jogo_id), inis_conferidos=conferidos,
                em_tela_cheia=True,
            )
        except Exception:
            self._desistir_da_abertura()
            raise
        if not aberto and jogo is not None and jogo.conferindo_inis:
            # Conferência rápida dos .ini: a capa fica aberta e o relançamento termina a abertura sem animar de novo.
            self._esperando_inis = True
            jogo.procurando_inis.connect(self._inis_pedem_dialogo, Qt.ConnectionType.UniqueConnection)
        elif not aberto:
            self._desistir_da_abertura()
        elif shared.sessao is None or not shared.sessao.jogoId:
            self._voltar_sem_sessao()

    def _continuar_abertura(self, jogo_id: str, conferidos: bool | None = None) -> None:  # noqa: FBT001
        """O relançamento pedido pelo jogo (comando confirmado ou .ini conferidos); `conferidos` vem de um pedido adiado."""
        if conferidos is None:  # a marca do jogo some no `launch`: lida já, ela vai junto se o pedido esperar
            jogo = shared.store.get(jogo_id) if shared.store is not None else None
            conferidos = jogo is not None and jogo.inis_conferidos
        if self._transicao == ("sessao", "detalhes"):
            self._reabertura = (jogo_id, conferidos)  # a capa ainda volta: o pedido não se perde, recomeça no fim da volta
            return
        if self._esperando_inis and jogo_id == self._jogo_aberto:
            self._esperando_inis, self._indo, self._inis_conferidos = False, True, conferidos
            self._lancar()
            return
        self._abrir(jogo_id)
        if self._indo and self._jogo_aberto == jogo_id:
            # A animação demora: a marca do jogo some antes do `launch`, então vai junto.
            self._inis_conferidos = conferidos

    @Slot(object, object)
    def _inis_pedem_dialogo(self, _jogar: object, _cancelar: object) -> None:
        """A busca dos .ini vai mostrar o diálogo: a capa volta enquanto ele está na tela."""
        if self._esperando_inis:
            self._esperando_inis = False
            self._desistir_da_abertura()

    def _desistir_da_abertura(self) -> None:
        """O jogo não abriu (comando a conferir, erro, sumiu): a capa volta e a tela cheia também."""
        self._pedir_etapa("detalhes")
        window_geometry.restore_from_monitor(self._janela)  # o `launch` que levantou já tinha mudado a janela de monitor
        self._voltar_a_tela_cheia()

    def _reabrir(self, para: str = "detalhes") -> None:
        self._pendente, self._centro_pendente = True, self._jogo_aberto
        if para == "carrossel":
            # As capas estão fora da tela durante a sessão: refazer agora evita o salto do carrossel no fim da volta.
            self._pendente = False
            self._refazer(self._jogo_aberto)
        self._pedir_etapa(para)
        self.focoPedido.emit()  # o bloqueio do jogo levou o foco; sem ele o teclado não chega aqui

    @Slot()
    def voltouDoJogo(self) -> None:  # noqa: N802
        # Uma entrada ou saída em curso não é a espera do jogo: segue com o próprio `depois`, que uma sequência nova descartaria (`_fechar_cortina`).
        if not self._ocupada or self._em_fade or self._na_fila or self._saindo:
            return
        self._voltar_a_tela_cheia()
        self._reabrir("carrossel")

    def _voltar_sem_sessao(self) -> None:
        self._reabrir()

    def _hwnd(self) -> int:
        return int(self._janela.winId()) if self._janela is not None else 0

    def _trocar_no_escuro(
        self, trocar: Callable[[], None], ms_escurecer: int, depois: Callable[[], None] | None
    ) -> None:
        """Escurece o monitor, troca, espera um instante e clareia; sem cortina, só troca. Na entrada, a troca espera
        `capasProntas` (ou `ESPERA_MAXIMA_DAS_CAPAS_MS`).
        """
        self._fechar_cortina()
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
        if not self._animacoes_do_sistema:
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
            # A cortina preta não pode ficar no monitor nem a página travada.
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
