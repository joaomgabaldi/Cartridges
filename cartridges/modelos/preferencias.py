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

from cartridges import shared
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
        eu = weakref.ref(self)
        self._ligacao = shared.schema.connect("changed", lambda *_: (p := eu()) and p._reler())
        self._reler()
        return True

    @Slot()
    def fechar(self) -> None:
        if not self._aberto:
            return
        self._aberto = False
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
