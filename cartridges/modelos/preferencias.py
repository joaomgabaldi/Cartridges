# preferencias.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O modelo das Preferências (D66): as chaves, as travas e a busca, sem tela.

O QML lê `valores` e `estado` e grava por `definir` e `definirTexto`. O que tem efeito (a trava do minimizar, o
cinza do controle e do 3D, as regras dos textos) mora aqui, em Python, e é testado sem QML. `valores` é refeito no
`changed` do `schema` (ouvinte com referência fraca) enquanto a tela está aberta. Só na thread principal.
"""

import logging
import math
import unicodedata
import weakref
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import Property, QObject, QUrl, Signal, Slot

from cartridges import metadata_refresh, shared
from cartridges.errors.friendly_error import FriendlyError
from cartridges.store.managers.sgdb_manager import SgdbManager
from cartridges.utils import open_uri

# As 19 de `bind_switches` da main (sem `show-news-button`, D64), mais as que ela ligava por widget próprio.
CHAVES_GRAVAVEIS = frozenset(
    {
        "minimize-after-launch",
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
# Chaves com regra própria (`definirTexto` e as tasks seguintes): só lidas por `valores`.
CHAVES_DE_TEXTO = frozenset({"sgdb-key", "wallhaven-key", "conquistas-chave-steam"})
CHAVES_DA_TELA = (
    CHAVES_GRAVAVEIS
    | CHAVES_DE_TEXTO
    | {"show-news-button", "shortcuts-location", "session-monitor", "conquistas-aviso-posicao", "conquistas-pulso-estilo"}
)
# Chaves inteiras: (mínimo, máximo), como no gschema. As demais de CHAVES_GRAVAVEIS são booleanas.
_INTEIROS = {"process-tracking-grace": (0, 120), "conquistas-aviso-som-volume": (10, 100)}
PAGINAS = ("general", "session", "import", "sgdb", "conquistas")
SEM_3D = "Requer uma placa de vídeo com aceleração 3D."

_log = logging.getLogger(__name__)


class AtualizacoesDaBiblioteca(QObject):
    """As atualizações em lote (metadados e capas) que as Preferências disparam, vistas pela tela.

    A atualização de metadados não é daqui: roda por `metadata_refresh` pela vida do processo, e esta classe só a
    espelha enquanto as Preferências estão abertas (`seguir`); fechar a tela não cancela nada. As capas são um lote
    que termina quando o último jogo responde. Só na thread principal.
    """

    alterado = Signal()
    perguntar = Signal(str)

    def __init__(self, avisos: Any, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._avisos = avisos
        self._baixando = False
        self._seguindo = False
        self._ligacao: int | None = None
        self._refresh_seguido: Any = None

    @staticmethod
    def _refresh() -> metadata_refresh.MetadataRefresh:
        return metadata_refresh.get_metadata_refresh()

    def _avisar(self, texto: str, **kwargs: Any) -> Any:
        if self._avisos is not None:
            return self._avisos.adicionar(texto, **kwargs)
        return None

    @Property(bool, notify=alterado)
    def metadadosAtivos(self) -> bool:  # noqa: N802
        # As duas fontes desligadas: os gerentes não fazem nada, e o botão percorreria a biblioteca à toa.
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
        """Liga ou solta o acompanhamento da atualização (a tela aberta liga; ao fechar, solta)."""
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
        """Pergunta o que buscar (a tela abre o diálogo no `perguntar`); sem jogos, só avisa."""
        refresh = self._refresh()
        jogos = refresh.library()
        if not jogos:
            self._avisar(_("Nenhum jogo na biblioteca"))
            return
        incompletos = [jogo for jogo in jogos if refresh.is_incomplete(jogo)]
        self.perguntar.emit(
            _(
                "Buscar o que falta atualiza {} de {} jogos, consultando somente "
                "os campos ausentes. Buscar tudo preenche todos os campos, podendo "
                "levar mais tempo."
            ).format(len(incompletos), len(jogos))
        )

    @Slot(bool)
    def buscarMetadados(self, somente_faltantes: bool) -> None:  # noqa: N802
        refresh = self._refresh()
        jogos = refresh.library()
        desejados = [jogo for jogo in jogos if refresh.is_incomplete(jogo)] if somente_faltantes else jogos
        if refresh.start(desejados, only_missing=somente_faltantes):
            return
        # `start` recusa por dois motivos, e dizer que não há o que buscar com uma atualização em curso seria falso.
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
        """O lote de capas do SteamGridDB para os jogos da biblioteca."""
        if self._baixando:
            return
        # Os removidos continuam na store como lápides: ficam de fora.
        jogos = [jogo for jogo in shared.store if not jogo.removed]
        total = len(jogos)
        if not total:
            return
        gerente = shared.store.managers[SgdbManager]
        gerente.reset_cancellable()
        self._baixando = True
        self.alterado.emit()
        aviso = self._avisar(_("Baixando capas…"), segundos=0)
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
            # Só quem ainda está na store: um reset no meio do lote apagou a biblioteca, e o `update()` de um jogo
            # apagado o punha de volta na grade.
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
        self._biblioteca = AtualizacoesDaBiblioteca(avisos, self)

    @Property(QObject, constant=True)
    def biblioteca(self) -> QObject:
        return self._biblioteca

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
        eu = weakref.ref(self)
        self._ligacao = shared.schema.connect("changed", lambda *_: (p := eu()) and p._reler())
        self._reler()
        return True

    @Slot()
    def fechar(self) -> None:
        if not self._aberto:
            return
        self._aberto = False
        self._biblioteca.seguir(False)
        if self._ligacao is not None:
            shared.schema.disconnect(self._ligacao)
            self._ligacao = None
        self.alterado.emit()

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

    @Slot(QUrl)
    def escolherPastaDosAtalhos(self, url: QUrl) -> None:  # noqa: N802
        """A pasta do `FolderDialog`; uma escolha vazia (diálogo cancelado) não grava."""
        if url.isEmpty() or not url.toLocalFile():
            return
        shared.schema["shortcuts-location"] = str(Path(url.toLocalFile()))

    @Slot(str)
    def abrirEndereco(self, url: str) -> None:  # noqa: N802
        open_uri.abrir_url(url)

    @Slot(str, str, result=bool)
    def corresponde(self, texto: str, filtro: str) -> bool:
        return _normalizar(filtro) in _normalizar(texto)

    def _reler(self) -> None:
        # O playtime sempre minimiza a principal (a janela da sessão assume): a chave fica ligada e travada.
        if shared.schema.get_boolean("playtime-tracking") and not shared.schema.get_boolean("minimize-after-launch"):
            shared.schema["minimize-after-launch"] = True  # o `changed` volta aqui já com a chave certa
            return
        self._valores = {chave: shared.schema.get_value(chave) for chave in CHAVES_DA_TELA}
        gamepad = shared.schema.get_boolean("gamepad")
        com_3d = bool(self._tem_3d())
        self._estado = {
            "minimizarTravado": shared.schema.get_boolean("playtime-tracking"),
            "rumbleAtivo": gamepad,
            "bigPictureAtivo": gamepad and com_3d,
            "somDoBigPictureAtivo": com_3d,
            "subtituloSem3d": "" if com_3d else SEM_3D,
            "sgdbAtivo": bool(shared.schema.get_string("sgdb-key")),
            # O valor guardado já vem como o Windows escreve, menos a barra que o seletor às vezes devolve.
            "pastaDosAtalhos": shared.schema.get_string("shortcuts-location").replace("/", "\\")
            or "Nenhuma pasta selecionada",
        }
        self.alterado.emit()


def _normalizar(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto.casefold()) if not unicodedata.combining(c))
