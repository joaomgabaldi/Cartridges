# preferencias.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O modelo das Preferências: as chaves, as travas e a busca, sem tela."""

import logging
import math
import threading
import unicodedata
import weakref
from collections.abc import Callable
from pathlib import Path
from typing import Any

import shiboken6
from PySide6.QtCore import Property, QObject, QUrl, Signal, Slot
from PySide6.QtGui import QColor

from cartridges import conquista_aviso, metadata_refresh, shared
from cartridges.calibracao_janela import AssistenteDeCalibracao
from cartridges.errors.friendly_error import FriendlyError
from cartridges.fita_wizard import FitaWizard
from cartridges.modelos.backup_da_biblioteca import BackupDasPreferencias
from cartridges.modelos.contas import ContasDasLojas
from cartridges.store.managers.sgdb_manager import SgdbManager
from cartridges.utils import janela_por_cima, open_uri, session_fita, window_geometry
from cartridges.utils.thread_principal import na_thread_principal

CHAVES_GRAVAVEIS = frozenset(
    {
        "minimize-after-launch",
        "show-news-button",
        "playtime-tracking",
        "session-move-window",
        "session-wallpaper",
        "session-fita",
        "fita-acompanha-tela",
        "gamepad",
        "gamepad-rumble",
        "big-picture-ao-conectar",
        "big-picture-som",
        "auto-import",
        "remove-missing",
        "steam-metadata",
        "hltb-metadata",
        "shortcuts-recursive",
        "sgdb",
        "sgdb-prefer",
        "sgdb-animated",
        "cover-autoplay",
        "shortcuts",
        "process-tracking-grace",
        "conquistas-mostrar-ocultas",
        "conquistas-aviso",
        "conquistas-aviso-som",
        "conquistas-aviso-som-volume",
        "conquistas-iluminacao",
    }
)
CHAVES_DE_TEXTO = frozenset({"sgdb-key", "wallhaven-key", "conquistas-chave-steam"})
CHAVES_DA_TELA = (
    CHAVES_GRAVAVEIS
    | CHAVES_DE_TEXTO
    | {"shortcuts-location", "session-monitor", "conquistas-aviso-posicao", "conquistas-pulso-estilo"}
)
_INTEIROS = {"process-tracking-grace": (0, 120), "conquistas-aviso-som-volume": (10, 100)}
PAGINAS = ("general", "session", "import", "sgdb", "conquistas")
ESTILOS_NA_TELA = ("piscar", "respirar", "rapido", "longo")
SEM_3D = "Requer uma placa de vídeo com aceleração 3D."

_log = logging.getLogger(__name__)


class AtualizacoesDaBiblioteca(QObject):
    """As atualizações em lote (metadados e capas) que as Preferências disparam, vistas pela tela."""

    alterado = Signal()
    perguntar = Signal(str)

    def __init__(self, avisos: Any, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._avisos = avisos
        self._baixando = False
        self._seguindo = False
        self._ligacao: int | None = None
        self._refresh_seguido: Any = None
        self._pergunta: tuple[list[Any], list[Any]] | None = None

    @staticmethod
    def _refresh() -> metadata_refresh.MetadataRefresh:
        return metadata_refresh.get_metadata_refresh()

    def _avisar(self, texto: str, **kwargs: Any) -> Any:
        if self._avisos is not None:
            return self._avisos.adicionar(texto, **kwargs)
        return None

    @Property(bool, notify=alterado)
    def metadadosAtivos(self) -> bool:  # noqa: N802
        return shared.schema.get_boolean("steam-metadata") or shared.schema.get_boolean("hltb-metadata")

    @Property(bool, notify=alterado)
    def rodando(self) -> bool:
        return self._refresh().running

    @Property(bool, notify=alterado)
    def cancelado(self) -> bool:
        return self._refresh().cancelled

    @Property(float, notify=alterado)
    def fracao(self) -> float:
        return self._refresh().fraction

    @Property(str, notify=alterado)
    def progresso(self) -> str:
        refresh = self._refresh()
        # As variáveis são quantos jogos já foram e quantos há
        return _("{} de {}").format(refresh.done, refresh.total)

    @Property(bool, notify=alterado)
    def baixandoCapas(self) -> bool:  # noqa: N802
        return self._baixando

    @Slot(bool)
    def seguir(self, ligado: bool) -> None:
        if ligado == self._seguindo:
            return
        self._seguindo = ligado
        if ligado:
            self._refresh_seguido = refresh = self._refresh()
            refresh.progress.connect(self._ao_progredir)
            eu = weakref.ref(self)
            self._ligacao = shared.schema.connect("changed", lambda *_: (b := eu()) and b.alterado.emit())
            self.alterado.emit()
            return
        if self._refresh_seguido is not None:
            try:
                self._refresh_seguido.progress.disconnect(self._ao_progredir)
            except (RuntimeError, TypeError):
                pass
            self._refresh_seguido = None
        if self._ligacao is not None:
            shared.schema.disconnect(self._ligacao)
            self._ligacao = None

    def _ao_progredir(self) -> None:
        self.alterado.emit()

    @Slot()
    def atualizarMetadados(self) -> None:  # noqa: N802
        refresh = self._refresh()
        jogos = refresh.library()
        if not jogos:
            self._avisar(_("Nenhum jogo na biblioteca"))
            return
        incompletos = [jogo for jogo in jogos if refresh.is_incomplete(jogo)]
        self._pergunta = (jogos, incompletos)
        self.perguntar.emit(
            _(
                "Buscar o que falta atualiza {} de {} jogos, consultando somente "
                "os campos ausentes. Buscar tudo preenche todos os campos, podendo "
                "levar mais tempo."
            ).format(len(incompletos), len(jogos))
        )

    @Slot()
    def descartarPergunta(self) -> None:  # noqa: N802
        self._pergunta = None

    @Slot(bool)
    def buscarMetadados(self, somente_faltantes: bool) -> None:  # noqa: N802
        refresh = self._refresh()
        if self._pergunta is not None:
            jogos, incompletos = self._pergunta
            self._pergunta = None
        else:
            jogos = refresh.library()
            incompletos = [jogo for jogo in jogos if refresh.is_incomplete(jogo)]
        desejados = incompletos if somente_faltantes else jogos
        if refresh.start(desejados, only_missing=somente_faltantes):
            return
        self._avisar(
            _("Todos os jogos já estão com os metadados completos")
            if not desejados
            else _("Uma atualização de metadados já está em andamento")
        )

    @Slot()
    def cancelarMetadados(self) -> None:  # noqa: N802
        self._refresh().cancel()
        self.alterado.emit()

    @Slot()
    def atualizarCapas(self) -> None:  # noqa: N802
        if self._baixando:
            return
        jogos = [jogo for jogo in shared.store if not jogo.removed]
        total = len(jogos)
        if not total:
            return
        gerente = shared.store.managers[SgdbManager]
        gerente.reset_cancellable()
        self._baixando = True
        self.alterado.emit()
        aviso = self._avisar(_("Baixando capas…"))
        eu = weakref.ref(self)
        contador = 0

        def ao_terminar_um(manager: SgdbManager) -> None:
            nonlocal contador
            contador += 1
            if contador != total:
                return
            for erro in manager.collect_errors():
                if isinstance(erro, FriendlyError):
                    aplicativo = getattr(shared, "aplicativo", None)
                    if aplicativo is not None:
                        aplicativo.pedir_dialogo(erro.title, erro.subtitle, [], lambda: None)
                    break
            for jogo in jogos:
                if shared.store.get(jogo.game_id) is jogo:
                    jogo.update()
            modelo = eu()
            if modelo is None:
                return
            if aviso is not None and modelo._avisos is not None:  # noqa: SLF001
                modelo._avisos.dispensar(aviso)  # noqa: SLF001
            modelo._avisar(_("Capas atualizadas"))  # noqa: SLF001
            modelo._baixando = False  # noqa: SLF001
            modelo.alterado.emit()

        for jogo in jogos:
            gerente.process_game(jogo, {}, ao_terminar_um)


class FitasDasPreferencias(QObject):
    """A iluminação inteligente vista pelas Preferências: o brilho, a cor do app e o "Testar"."""

    alterado = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._configuradas = 0
        self._aberta = False
        self._balao_do_pulso = False
        self._parar: threading.Event | None = None
        self._resultado = ""

    @Property(int, notify=alterado)
    def configuradas(self) -> int:
        return self._configuradas

    @Property(str, notify=alterado)
    def subtitulo(self) -> str:
        if not self._configuradas:
            return _("Nenhum dispositivo configurado")
        return ngettext("{} dispositivo configurado", "{} dispositivos configurados", self._configuradas).format(
            self._configuradas
        )

    @Property(int, notify=alterado)
    def brilho(self) -> int:
        return session_fita.por_cento(shared.schema.get_int("fita-brilho-padrao"))

    @Property(QColor, notify=alterado)
    def corDoApp(self) -> QColor:  # noqa: N802
        return QColor.fromRgbF(*session_fita.cor_para_rgb(session_fita.cor_do_app()))

    @Property(bool, notify=alterado)
    def corDoAppPadrao(self) -> bool:  # noqa: N802
        return session_fita.tom_do_app() == session_fita.COR_PADRAO_DO_APP

    @Property(QColor, notify=alterado)
    def corDoPulso(self) -> QColor:  # noqa: N802
        return QColor.fromRgbF(*session_fita.cor_para_rgb(session_fita.cor_do_pulso()))

    @Property(bool, notify=alterado)
    def corDoPulsoPadrao(self) -> bool:  # noqa: N802
        return session_fita.tom_do_pulso() == session_fita.TOM_DO_OURO

    @Property(int, notify=alterado)
    def estiloDoPulso(self) -> int:  # noqa: N802
        return ESTILOS_NA_TELA.index(session_fita.estilo_do_pulso())

    @Property(bool, notify=alterado)
    def testando(self) -> bool:
        return self._parar is not None

    @Property(str, notify=alterado)
    def resultadoDoTeste(self) -> str:  # noqa: N802
        return self._resultado

    @staticmethod
    def _previa(cor: session_fita.Cor) -> None:
        session_fita.previa(cor)

    @Slot()
    def reler(self) -> None:
        self._aberta = True
        self._balao_do_pulso = False
        if self._parar is None:
            self._resultado = ""
        self.recontar()

    @Slot()
    def recontar(self) -> None:
        self._configuradas = len(session_fita.fitas())
        if not self._configuradas:
            shared.schema["session-fita"] = False
        self.alterado.emit()

    @Slot(int)
    def definirBrilho(self, pct: int) -> None:  # noqa: N802
        brilho = session_fita.de_por_cento(pct)
        shared.schema["fita-brilho-padrao"] = brilho
        self._previa(session_fita.Cor(*session_fita.tom_do_app(), brilho))
        self.alterado.emit()

    @Slot(QColor)
    def escolherCorDoApp(self, cor: QColor) -> None:  # noqa: N802
        if not cor.isValid():
            return
        escolhida = session_fita.rgb_para_cor(cor.redF(), cor.greenF(), cor.blueF(), session_fita.brilho_padrao())
        session_fita.salvar_tom_do_app(escolhida.matiz, escolhida.saturacao)
        self._previa(session_fita.cor_do_app())
        self.alterado.emit()

    @Slot()
    def voltarCorDoApp(self) -> None:  # noqa: N802
        session_fita.redefinir_tom_do_app()
        self._previa(session_fita.cor_do_app())
        self.alterado.emit()

    @Slot()
    def abrirCorDoPulso(self) -> None:  # noqa: N802
        self._balao_do_pulso = True
        self._previa(session_fita.cor_do_pulso())

    @Slot()
    def fecharCorDoPulso(self) -> None:  # noqa: N802
        if not self._balao_do_pulso:
            return
        self._balao_do_pulso = False
        self._previa(session_fita.cor_do_app())

    @Slot(QColor)
    def escolherCorDoPulso(self, cor: QColor) -> None:  # noqa: N802
        if not cor.isValid():
            return
        escolhida = session_fita.rgb_para_cor(cor.redF(), cor.greenF(), cor.blueF(), session_fita.BRILHO_CHEIO)
        session_fita.salvar_tom_do_pulso(escolhida.matiz, escolhida.saturacao)
        if self._balao_do_pulso:
            self._previa(session_fita.cor_do_pulso())
        self.alterado.emit()

    @Slot()
    def voltarCorDoPulso(self) -> None:  # noqa: N802
        # O dourado exato: a ida e volta pela cor da tela pode arredondar uma unidade.
        session_fita.redefinir_tom_do_pulso()
        if self._balao_do_pulso:
            self._previa(session_fita.cor_do_pulso())
        self.alterado.emit()

    @Slot(int)
    def escolherEstiloDoPulso(self, indice: int) -> None:  # noqa: N802
        if 0 <= indice < len(ESTILOS_NA_TELA):
            shared.schema["conquistas-pulso-estilo"] = ESTILOS_NA_TELA[indice]
            self.alterado.emit()

    @Slot()
    def testarAlerta(self) -> None:  # noqa: N802
        session_fita.testar_pulso()

    @Slot()
    def testar(self) -> None:
        if self._parar is not None:
            self._parar.set()
            return
        parar = threading.Event()
        self._parar = parar
        session_fita.retomar()
        cor = session_fita.cor_do_app()
        eu = weakref.ref(self)

        def tarefa() -> None:
            mudas: list[str] = []
            interrompido = False
            try:
                for fita in session_fita.fitas():
                    if parar.is_set():
                        break
                    if not session_fita.aplicar(fita, True, session_fita.hsv_hex(session_fita.na_fita(cor, fita))):
                        mudas.append(fita.nome)
            except Exception:  # noqa: BLE001
                _log.exception("Teste das fitas interrompido por erro")
                interrompido = True
            na_thread_principal(_entregar_teste, eu, parar, mudas, interrompido or parar.is_set())

        self._resultado = _("Testando…")
        self.alterado.emit()
        threading.Thread(target=tarefa, daemon=True).start()

    def _teste_terminou(self, parar: threading.Event, mudas: list[str], cancelado: bool) -> None:
        if self._parar is parar:
            self._parar = None
        if self._aberta:
            if cancelado:
                self._resultado = _("Teste interrompido")
            elif mudas:
                self._resultado = _(
                    "Sem resposta: {}. Se o dispositivo estiver ligado, o endereço dele na rede pode ter mudado; "
                    "configure a iluminação inteligente novamente."
                ).format(", ".join(mudas))
            else:
                self._resultado = _("Teste concluído")
        self.alterado.emit()

    @Slot()
    def fechar(self) -> None:
        self._aberta = False
        self._balao_do_pulso = False


def _entregar_teste(eu: "weakref.ref[FitasDasPreferencias]", *args: Any) -> None:
    fitas = eu()
    if fitas is not None and shiboken6.isValid(fitas):
        fitas._teste_terminou(*args)  # noqa: SLF001


class BrilhoPorDispositivo(QObject):
    """A janela "Brilho máximo por dispositivo": cada fita acende no próprio número, sem o brilho geral por cima."""

    fechado = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        configuradas = session_fita.fitas()
        self._brilhos = {fita.id: fita.brilho for fita in configuradas}
        self._linhas = [{"id": fita.id, "nome": fita.nome, "brilho": fita.brilho} for fita in configuradas]
        self._mostrar()

    @Property("QVariantList", constant=True)
    def linhas(self) -> list[dict[str, Any]]:
        return self._linhas

    def _mostrar(self) -> None:
        session_fita.previa(session_fita.Cor(*session_fita.tom_do_app(), session_fita.BRILHO_CHEIO), dict(self._brilhos))

    @Slot(str, int)
    def mudar(self, id_: str, brilho: int) -> None:
        if id_ not in self._brilhos:
            return
        self._brilhos[id_] = max(1, min(100, int(brilho)))
        self._mostrar()

    @Slot()
    def salvar(self) -> None:
        session_fita.gravar_fitas(
            [
                fita._replace(brilho=self._brilhos[fita.id]) if fita.id in self._brilhos else fita
                for fita in session_fita.fitas()
            ]
        )
        self.cancelar()

    @Slot()
    def cancelar(self) -> None:
        # Depois do Salvar é o mesmo brilho da prévia; sem ele, volta ao salvo.
        session_fita.previa(session_fita.cor_do_app())
        self.fechado.emit()


class Preferencias(QObject):
    alterado = Signal()

    def __init__(self, avisos: Any, tem_3d: Callable[[], bool], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._avisos = avisos
        self._tem_3d = tem_3d
        self._aberto = False
        self._pagina = "general"
        self._valores: dict[str, Any] = {}
        self._estado: dict[str, Any] = {}
        self._ligacao: int | None = None
        self._monitores: list[window_geometry.Monitor] = []
        self._biblioteca = AtualizacoesDaBiblioteca(avisos, self)
        self._fitas = FitasDasPreferencias(self)
        self._backup = BackupDasPreferencias(avisos, self)
        self._brilho: BrilhoPorDispositivo | None = None
        self._config: FitaWizard | None = None
        self._calibracao: AssistenteDeCalibracao | None = None
        self._contas: ContasDasLojas | None = None

    @Property(QObject, notify=alterado)
    def contas(self) -> QObject | None:
        return self._contas

    @Property(QObject, constant=True)
    def biblioteca(self) -> QObject:
        return self._biblioteca

    @Property(QObject, constant=True)
    def backup(self) -> QObject:
        return self._backup

    @Property(QObject, constant=True)
    def fitas(self) -> QObject:
        return self._fitas

    @Property(QObject, notify=alterado)
    def brilhoPorDispositivo(self) -> QObject | None:  # noqa: N802
        return self._brilho

    @Slot()
    def abrirBrilhoPorDispositivo(self) -> None:  # noqa: N802
        if self._brilho is not None:
            return
        self._brilho = BrilhoPorDispositivo(self)
        self._brilho.fechado.connect(self._brilho_fechou)
        self.alterado.emit()

    def _brilho_fechou(self) -> None:
        brilho, self._brilho = self._brilho, None
        if brilho is not None:
            brilho.deleteLater()
        self.alterado.emit()

    @Property(QObject, notify=alterado)
    def configuracaoDasFitas(self) -> QObject | None:  # noqa: N802
        return self._config

    @Slot()
    def abrirConfiguracaoDasFitas(self) -> None:  # noqa: N802
        if self._config is not None:
            return
        self._config = FitaWizard(self)
        self._config.fechado.connect(self._config_fechou)
        self.alterado.emit()

    def _config_fechou(self) -> None:
        config, self._config = self._config, None
        if config is not None:
            config.deleteLater()
        self._fitas.recontar()
        if session_fita.ligada():
            session_fita.reacender()
        self.alterado.emit()

    @Property(QObject, notify=alterado)
    def calibracao(self) -> QObject | None:
        return self._calibracao

    @Slot()
    def abrirCalibracao(self) -> None:  # noqa: N802
        if self._calibracao is not None:
            return
        self._calibracao = AssistenteDeCalibracao(session_fita.fitas(), self)
        self._calibracao.fechado.connect(self._calibracao_fechou)
        self.alterado.emit()

    def _calibracao_fechou(self) -> None:
        calibracao, self._calibracao = self._calibracao, None
        if calibracao is not None:
            calibracao.deleteLater()
        self.alterado.emit()

    @Property(bool, notify=alterado)
    def aberto(self) -> bool:
        return self._aberto

    @Property(str, notify=alterado)
    def pagina(self) -> str:
        return self._pagina

    @Property("QVariantMap", notify=alterado)
    def valores(self) -> dict[str, Any]:
        return self._valores

    @Property("QVariantMap", notify=alterado)
    def estado(self) -> dict[str, Any]:
        return self._estado

    @Slot(str, result=bool)
    @Slot(result=bool)
    def abrir(self, pagina: str = "") -> bool:
        if self._aberto or getattr(shared.aplicativo, "importando", False):
            return False
        self._aberto = True
        self._pagina = pagina if pagina in PAGINAS else "general"
        self._biblioteca.seguir(True)
        self._contas = ContasDasLojas(self._avisos, parent=self)
        self._ler_monitores()
        self._fitas.reler()
        self._backup.reler()
        eu = weakref.ref(self)
        self._ligacao = shared.schema.connect("changed", lambda *_: (p := eu()) and p._reler())
        self._reler()
        return True

    @Slot()
    def fechar(self) -> None:
        if not self._aberto:
            return
        self._aberto = False
        contas, self._contas = self._contas, None
        calibracao, config, brilho = self._calibracao, self._config, self._brilho
        passos = (
            lambda: contas is not None and contas.fechar(),
            lambda: calibracao is not None and calibracao.cancelar(),
            lambda: config is not None and config.fechar(),
            lambda: brilho is not None and brilho.cancelar(),
            self._fitas.fecharCorDoPulso,
            self._fitas.fechar,
            lambda: self._biblioteca.seguir(False),
            self._biblioteca.descartarPergunta,
            self._soltar_ouvinte,
        )
        for passo in passos:
            try:
                passo()
            except Exception:  # noqa: BLE001
                _log.exception("Falha ao fechar as Preferências")
        if contas is not None:
            contas.deleteLater()
        self.alterado.emit()

    def _soltar_ouvinte(self) -> None:
        ligacao, self._ligacao = self._ligacao, None
        if ligacao is not None:
            shared.schema.disconnect(ligacao)

    @Slot(str, "QVariant")
    def definir(self, chave: str, valor: Any) -> None:
        if chave not in CHAVES_GRAVAVEIS:
            _log.warning("Preferência fora da lista recusada: %r", chave)
            return
        if chave in _INTEIROS:
            minimo, maximo = _INTEIROS[chave]
            if isinstance(valor, bool) or not isinstance(valor, (int, float)) or not math.isfinite(valor):
                _log.warning("Valor inválido para %r recusado: %r", chave, valor)
                return
            valor = max(minimo, min(maximo, int(valor)))
        elif not isinstance(valor, bool):
            _log.warning("Valor inválido para %r recusado: %r", chave, valor)
            return
        shared.schema[chave] = valor
        if chave == "session-fita" and valor:
            # Grava antes: o `reacender` decide pela chave.
            session_fita.reacender()

    @Slot(str, str)
    def definirTexto(self, chave: str, texto: str) -> None:
        if chave not in CHAVES_DE_TEXTO:
            _log.warning("Texto de preferência fora da lista recusado: %r", chave)
            return
        if chave != "sgdb-key":
            texto = texto.strip()
        shared.schema[chave] = texto
        if chave == "sgdb-key" and not texto:
            shared.schema["sgdb"] = False

    def _ler_monitores(self) -> None:
        self._monitores = window_geometry.monitores_da_sessao()
        if not self._monitores:
            shared.schema["session-move-window"] = False
            shared.schema["session-wallpaper"] = False
            return
        _rotulos, escolhido = window_geometry.escolha_de_monitor(
            self._monitores, shared.schema.get_string("session-monitor")
        )
        chave = self._monitores[escolhido].key
        if shared.schema.get_string("session-monitor") != chave:
            shared.schema["session-monitor"] = chave

    @Slot(int)
    def escolherMonitor(self, indice: int) -> None:  # noqa: N802
        if 0 <= indice < len(self._monitores):
            shared.schema["session-monitor"] = self._monitores[indice].key

    @Slot()
    def identificarMonitores(self) -> None:  # noqa: N802
        window_geometry.identificar_monitores()

    @Slot(QUrl)
    def escolherPastaDosAtalhos(self, url: QUrl) -> None:  # noqa: N802
        if url.isEmpty() or not url.toLocalFile():
            return
        shared.schema["shortcuts-location"] = str(Path(url.toLocalFile()))

    @Slot(int)
    def escolherPosicaoDoAviso(self, indice: int) -> None:  # noqa: N802
        """Um índice fora da lista (nenhuma opção escolhida) não grava."""
        if 0 <= indice < len(janela_por_cima.CANTOS):
            shared.schema["conquistas-aviso-posicao"] = janela_por_cima.CANTOS[indice]

    @Slot()
    def mostrarAvisoDeExemplo(self) -> None:  # noqa: N802
        conquista_aviso.fechar()
        conquista_aviso.mostrar(conquista_aviso.Aviso.exemplo())

    @Slot(str)
    def abrirEndereco(self, url: str) -> None:  # noqa: N802
        open_uri.abrir_url(url)

    @Slot(str, str, result=bool)
    def corresponde(self, texto: str, filtro: str) -> bool:
        return _normalizar(filtro) in _normalizar(texto)

    def _reler(self) -> None:
        if shared.schema.get_boolean("playtime-tracking") and not shared.schema.get_boolean("minimize-after-launch"):
            shared.schema["minimize-after-launch"] = True
            return
        self._valores = {chave: shared.schema.get_value(chave) for chave in CHAVES_DA_TELA}
        gamepad = shared.schema.get_boolean("gamepad")
        com_3d = bool(self._tem_3d())
        contando = shared.schema.get_boolean("playtime-tracking")
        sem_segundo = not self._monitores
        rotulos, escolhido = window_geometry.escolha_de_monitor(
            self._monitores, shared.schema.get_string("session-monitor")
        )
        canto = shared.schema.get_string("conquistas-aviso-posicao")
        if canto not in janela_por_cima.CANTOS:
            canto = "inferior-direito"
        aviso = shared.schema.get_boolean("conquistas-aviso")
        self._estado = {
            "minimizarTravado": shared.schema.get_boolean("playtime-tracking"),
            "rumbleAtivo": gamepad,
            "bigPictureAtivo": gamepad and com_3d,
            "somDoBigPictureAtivo": com_3d,
            "subtituloSem3d": "" if com_3d else SEM_3D,
            # Sem o Ludusavi no pacote não há saves a configurar (lido ao abrir, em `backup.reler`).
            "savesDisponiveis": self._backup.savesDisponiveis,
            "monitores": rotulos,
            "monitorEscolhido": escolhido,
            "semSegundoMonitor": sem_segundo,
            "moverAtivo": contando and not sem_segundo,
            "monitorAtivo": contando and not sem_segundo and shared.schema.get_boolean("session-move-window"),
            "papelDeParedeAtivo": contando,
            "papelDeParedeLigavel": contando and not sem_segundo,
            "chaveWallhavenAtiva": contando and shared.schema.get_boolean("session-wallpaper"),
            "sgdbAtivo": bool(shared.schema.get_string("sgdb-key")),
            "posicaoDoAviso": janela_por_cima.CANTOS.index(canto),
            "avisoAtivo": aviso,
            "volumeDoAvisoAtivo": aviso and shared.schema.get_boolean("conquistas-aviso-som"),
            "alertaAtivo": shared.schema.get_boolean("session-fita") and shared.schema.get_boolean("conquistas-iluminacao"),
            # O valor guardado já vem como o Windows escreve, menos a barra que o seletor às vezes devolve.
            "pastaDosAtalhos": shared.schema.get_string("shortcuts-location").replace("/", "\\")
            or "Nenhuma pasta selecionada",
        }
        self.alterado.emit()
        self._fitas.alterado.emit()


def _normalizar(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto.casefold()) if not unicodedata.combining(c))
