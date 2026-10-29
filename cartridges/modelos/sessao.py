# sessao.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O `ModeloDaSessao`: o que o `shared.win` fazia pelos rastreadores da sessão (D48).

`ProcessSession` e `SessionWindow` chamam aqui (`shared.sessao`) para mostrar e esconder a camada
da sessão, avisar o fim e trazer a janela de volta. O QML só lê as propriedades e chama os slots.
Tudo na thread principal.
"""

import weakref
from typing import Any

from PySide6.QtCore import Property, QObject, Qt, Signal, Slot
from PySide6.QtGui import QWindow

from cartridges.modelos.avisos import FilaDeAvisos
from cartridges.modelos.ordem import _url_da_capa  # noqa: PLC2701
from cartridges.process_session import ProcessSession
from cartridges.session_window import SessionWindow
from cartridges.utils import game_logo, session_log
from cartridges.utils.format_playtime import format_playtime, format_stopwatch


def pode_anotar(jogo: Any) -> bool:
    """Onde a anotação se edita: num jogo sendo jogado, ou que já tem uma.

    A anotação responde "onde eu parei?", que só é pergunta enquanto se joga; o jogo que já tem
    uma precisa continuar tendo onde apagá-la. Num zerado ela é só leitura.
    """
    if jogo.zerado:
        return False
    return jogo.status == "playing" or bool((jogo.notes or "").strip())


class ModeloDaSessao(QObject):
    alterado = Signal()
    anotarPedido = Signal(str)

    def __init__(self, avisos: FilaDeAvisos, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._avisos = avisos
        self._jogo: Any = None  # o jogo da sessão; None sem sessão (camada escondida)
        self._manual: SessionWindow | None = None
        self._janela: QWindow | None = None
        # O jogo cuja anotação o balão da camada edita: fica depois do fim da sessão, para o que foi
        # digitado com o balão aberto ainda chegar a ele ao fechar.
        self._anotando: Any = None
        self._logo = ""
        self._largura_do_logo = 0
        self._anotacao = ""

    def definir_janela(self, janela: QWindow) -> None:
        self._janela = janela

    # -- O que o QML lê -------------------------------------------------------------------------------

    @Property(bool, notify=alterado)
    def emAndamento(self) -> bool:
        return self._jogo is not None

    @Property(str, notify=alterado)
    def jogoId(self) -> str:
        return self._jogo.game_id if self._jogo is not None else ""

    @Property(str, notify=alterado)
    def nome(self) -> str:
        return self._jogo.name if self._jogo is not None else ""

    @Property(str, notify=alterado)
    def logo(self) -> str:
        return self._logo

    @Property(int, notify=alterado)
    def larguraDoLogo(self) -> int:  # noqa: N802
        return self._largura_do_logo

    @Property(str, notify=alterado)
    def anotacao(self) -> str:
        return self._anotacao

    @Property(str, notify=alterado)
    def relogio(self) -> str:
        # shortcut: lido na hora, sem tique de 1 s (o relógio fica escondido), a Task 4 liga o tique.
        return format_stopwatch(self.session_elapsed())

    @Property(bool, notify=alterado)
    def relogioVisivel(self) -> bool:
        # shortcut: sempre falso, só a Task 4 (monitor da sessão) decide quando o relógio aparece.
        return False

    @Property(bool, notify=alterado)
    def janelaManual(self) -> bool:
        return self._manual is not None

    @Property(str, notify=alterado)
    def tituloDaJanela(self) -> str:
        return _("Jogando {}").format(self.nome)

    # -- O contrato dos rastreadores ------------------------------------------------------------------

    def show_session_blocker(self, game: Any) -> None:
        # A mesma sessão trocando de rastreador (o `fall_back` de `ProcessSession` passando a vez à
        # janela manual): o jogo segue aberto e tudo o que veste a sessão já está vestido.
        if self._jogo is game:
            return
        self._jogo = self._anotando = game
        self._logo, self._largura_do_logo = "", 0
        if (caminho := game_logo.cached_logo_path(game)) and (carregado := game_logo.load_logo(caminho, 640, 140)):
            self._logo, self._largura_do_logo = _url_da_capa(carregado[0]), carregado[1]
        self._anotacao = game.notes or ""
        self.alterado.emit()

    def hide_session_blocker(self) -> None:
        self._jogo = None
        self._manual = None
        self.alterado.emit()

    def avisar(self, texto: str) -> None:
        self._avisos.adicionar(texto)

    def session_toast(self, game: Any, seconds: int) -> None:
        """O aviso do fim da sessão, com atalho para a anotação quando há onde anotar."""
        texto = _("{}: {} de jogo").format(game.name, format_playtime(seconds))
        # shortcut: sem o backup dos saves ao fim da sessão (backup_de_saves.no_fim_da_sessao), no plano que portar backup_de_saves (D52).
        if not pode_anotar(game):
            self._avisos.adicionar(texto)
            return
        eu, jogo_id = weakref.ref(self), game.game_id

        def anotar() -> None:
            if (modelo := eu()) is not None:
                modelo.anotarPedido.emit(jogo_id)

        self._avisos.adicionar(texto, _("Anotar"), anotar)

    @Slot()
    def minimizar(self) -> None:
        """Sai da frente guardando o estado: o `showMinimized()` do Qt 6 derrubaria o Maximizado."""
        janela = self._janela
        if janela is not None:
            janela.setWindowStates(janela.windowStates() | Qt.WindowState.WindowMinimized)

    def present(self) -> None:
        """Traz a janela de volta sem desmaximizá-la."""
        janela = self._janela
        if janela is None:
            return
        janela.setWindowStates(janela.windowStates() & ~Qt.WindowState.WindowMinimized)
        janela.raise_()
        janela.requestActivate()

    def move_to_session_monitor(self) -> bool:
        # shortcut: nunca move a janela, a Task 4 leva ao monitor da sessão.
        return False

    def vibrar_abertura(self) -> None:
        # shortcut: sem vibração do controle, a Task 6 confirma o lançamento na mão.
        return None

    def session_elapsed(self) -> int:
        """Os segundos que a sessão em andamento já contou. Zero sem sessão."""
        if ProcessSession.active is not None:
            return ProcessSession.active.elapsed
        if SessionWindow.active is not None:
            return SessionWindow.active.elapsed
        return 0

    def abrir_janela_manual(self, manual: SessionWindow) -> None:
        # A Task 3 desenha a janela; aqui só se diz que ela deve existir.
        self._manual = manual
        self.alterado.emit()

    # -- Slots do QML ---------------------------------------------------------------------------------

    @Slot()
    def terminar(self) -> None:
        """O botão da camada: encerra a sessão com registro, seja qual for o rastreador."""
        if SessionWindow.active is not None:
            SessionWindow.active.close()
        if ProcessSession.active is not None:
            ProcessSession.active.stop(record=True)

    @Slot(str)
    def gravarAnotacao(self, texto: str) -> None:  # noqa: N802
        """A anotação do balão da camada, com a regra do `DetalhesDoJogo.gravarAnotacao`."""
        jogo = self._anotando
        if jogo is None or jogo.zerado:
            return
        texto = texto.strip()
        if texto == (jogo.notes or ""):
            return
        jogo.notes = texto
        jogo.save()
        jogo.update()
        self._anotacao = texto
        self.alterado.emit()

    @Slot()
    def janelaManualFechada(self) -> None:
        manual, self._manual = self._manual, None
        if manual is None:
            return
        self.alterado.emit()
        manual.close()

    @Slot()
    def encerrar(self) -> None:
        """O app fechando no meio da sessão: grava o tempo e o histórico, sem tocar na interface."""
        if (manual := SessionWindow.active) is not None:
            SessionWindow.active = None
            manual.timer.stop()
            manual.flush()
            session_log.record(manual.game.game_id, manual.session_seconds)
        if (processo := ProcessSession.active) is not None:
            ProcessSession.active = None
            processo._parar_timer()  # noqa: SLF001
            processo.flush()
            if processo.started:
                session_log.record(processo.game.game_id, processo.session_seconds)
