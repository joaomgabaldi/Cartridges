# saves.py
#
# Copyright 2026 joaomgabaldi
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""As versões guardadas dos saves de um jogo ("Restaurar save").

As funções puras vêm do antigo `saves/dialogo.py`. `SavesDoJogo` (contexto `saves`) é o que o `DialogoDeVersoes.qml`
mostra: escolher uma versão pede a confirmação e só então chama `backup_de_saves.restaurar`. O QML só recebe
dicionários e ids, nunca um `Jogo` nem uma `Versao`.
"""

import weakref
from datetime import datetime
from typing import Any

from PySide6.QtCore import Property, QObject, Qt, Signal, Slot

from cartridges import shared
from cartridges.saves import backup_de_saves
from cartridges.saves.ludusavi import Versao


def _data_e_hora(quando: datetime) -> tuple[str, str]:
    """A data e a hora locais de uma versão (o Ludusavi as guarda em UTC)."""
    local = quando.astimezone()
    return f"{local:%d/%m/%Y}", f"{local:%H:%M}"


def formatar(quando: datetime) -> str:
    """"09/10/2026 às 21:14", no horário local."""
    data, hora = _data_e_hora(quando)
    return f"{data} às {hora}"


def subtitulo(versao: Versao) -> str:
    """O que a marca da versão significa para o usuário; o comentário cru nunca aparece."""
    if versao.comentario == backup_de_saves.INCOMPLETA:
        return _("Incompleta: alguns arquivos não puderam ser copiados")
    if versao.comentario == backup_de_saves.ANTES_DE_RESTAURAR:
        return _("Guardada antes de uma restauração")
    return ""


def corpo_da_confirmacao(versao: Versao) -> str:
    data, hora = _data_e_hora(versao.quando)
    corpo = _(
        "Tem certeza que deseja restaurar o save de {data} às {hora}? "
        "Os saves atuais deste jogo serão guardados como uma nova versão antes da restauração."
    ).format(data=data, hora=hora)
    if versao.comentario == backup_de_saves.INCOMPLETA:
        corpo += " " + _("Esta versão está incompleta: alguns arquivos não foram copiados.")
    return corpo


class SavesDoJogo(QObject):
    alterado = Signal()

    def __init__(self, aplicativo: Any, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._aplicativo = aplicativo
        self._jogo_id = ""
        self._versoes: list[Versao] = []
        # O `jogo_excluido` sai de threads do importador: a conexão enfileirada leva à principal.
        if shared.store is not None:
            shared.store.jogo_excluido.connect(self._excluido, Qt.ConnectionType.QueuedConnection)

    def _aberto(self) -> bool:
        return bool(self._jogo_id)

    def _lista(self) -> list[dict[str, str]]:
        return [{"id": v.id, "titulo": formatar(v.quando), "subtitulo": subtitulo(v)} for v in self._versoes]

    aberto = Property(bool, _aberto, notify=alterado)
    versoes = Property("QVariantList", _lista, notify=alterado)

    def _jogo(self) -> Any:
        return shared.store.get(self._jogo_id) if shared.store is not None and self._jogo_id else None

    @Slot(str, result=bool)
    def temBackup(self, jogo_id: str) -> bool:  # noqa: N802
        jogo = shared.store.get(jogo_id) if shared.store is not None else None
        return jogo is not None and backup_de_saves.tem_backup(jogo)

    @Slot(str, result=bool)
    def abrir(self, jogo_id: str) -> bool:
        jogo = shared.store.get(jogo_id) if shared.store is not None else None
        if jogo is None:
            return False
        versoes = sorted(backup_de_saves.versoes_do_jogo(jogo), key=lambda v: v.quando, reverse=True)
        if not versoes:
            return False
        self._jogo_id, self._versoes = jogo_id, versoes
        self.alterado.emit()
        return True

    @Slot()
    def fechar(self) -> None:
        if not self._jogo_id:
            return
        self._jogo_id, self._versoes = "", []
        self.alterado.emit()

    def _excluido(self, jogo_id: str) -> None:
        if jogo_id == self._jogo_id:
            self.fechar()

    @Slot(str)
    def escolher(self, versao_id: str) -> None:
        versao = next((v for v in self._versoes if v.id == versao_id), None)
        jogo = self._jogo()
        if versao is None or jogo is None:
            return
        eu, jogo_id = weakref.ref(self), self._jogo_id

        def ao_responder(confirmou: bool) -> None:
            modelo = eu()
            if not confirmou or modelo is None or modelo._jogo_id != jogo_id:  # noqa: SLF001
                return
            if (atual := modelo._jogo()) is not None:  # noqa: SLF001
                backup_de_saves.restaurar(atual, versao.id)
            modelo.fechar()

        self._aplicativo.pedir_confirmacao(
            _("Restaurar este save?"), corpo_da_confirmacao(versao), _("Restaurar"), ao_responder, destrutivo=True
        )
