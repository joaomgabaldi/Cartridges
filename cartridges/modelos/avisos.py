# avisos.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A fila de avisos: um por vez, na ordem em que chegaram.

Quem está na fila não está na tela, e um aviso que expirasse antes de aparecer ninguém veria:
por isso `dispensar_depois` só começa a contar quando o aviso ganha a vez. Tudo na thread principal.
"""

import itertools
from collections import deque
from collections.abc import Callable, Hashable
from dataclasses import dataclass

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot


@dataclass
class _Aviso:
    id: int
    texto: str
    botao: str
    ao_clicar: Callable[[], None] | None
    segundos: float
    chave: Hashable | None
    depois: float | None = None  # `dispensar_depois` pedido enquanto esperava a vez


class FilaDeAvisos(QObject):
    mudou = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._fila: deque[_Aviso] = deque()
        self._atual: _Aviso | None = None
        self._texto = self._botao = ""
        self._ids = itertools.count(1)
        self._relogio = QTimer(self)
        self._relogio.setSingleShot(True)
        self._relogio.timeout.connect(self.fechar)

    @Property(str, notify=mudou)
    def texto(self) -> str:
        """Fica o do último aviso depois que ele some, para o texto não sumir antes do fade."""
        return self._texto

    @Property(str, notify=mudou)
    def botao(self) -> str:
        return self._botao

    @Property(bool, notify=mudou)
    def visivel(self) -> bool:
        return self._atual is not None

    def adicionar(
        self,
        texto: str,
        botao: str = "",
        ao_clicar: Callable[[], None] | None = None,
        segundos: float = 5,
        chave: Hashable | None = None,
    ) -> int:
        """Enfileira o aviso e devolve o id. `segundos=0`: só sai por `dispensar`.

        Um aviso com a mesma `chave` de um que está na tela ou na fila toma o lugar dele.
        """
        novo = _Aviso(next(self._ids), texto, botao, ao_clicar, segundos, chave)
        if chave is not None and self._atual is not None and self._atual.chave == chave:
            self._mostrar(novo)
            return novo.id
        for i, antigo in enumerate(self._fila):
            if chave is not None and antigo.chave == chave:
                self._fila[i] = novo
                return novo.id
        self._fila.append(novo)
        if self._atual is None:
            self._proximo()
        return novo.id

    def dispensar_chave(self, chave: Hashable) -> None:
        for aviso in [self._atual, *self._fila]:
            if aviso is not None and aviso.chave == chave:
                self.dispensar(aviso.id)

    @Slot(int)
    def dispensar(self, id: int) -> None:  # noqa: A002
        """Tira o aviso, esteja ele na tela ou na fila."""
        if self._atual is not None and self._atual.id == id:
            self.fechar()
        else:
            self._fila = deque(a for a in self._fila if a.id != id)

    def dispensar_depois(self, id: int, segundos: float) -> None:  # noqa: A002
        """Tira o aviso `segundos` depois de ele *aparecer*."""
        if self._atual is not None and self._atual.id == id:
            self._relogio.start(round(segundos * 1000))
        else:
            for aviso in self._fila:
                if aviso.id == id:
                    aviso.depois = segundos

    @Slot()
    def clicar(self) -> None:
        if (aviso := self._atual) is not None:
            self.fechar()
            if aviso.ao_clicar is not None:
                aviso.ao_clicar()

    @Slot()
    def fechar(self) -> None:
        self._relogio.stop()
        self._atual = None
        self._proximo()
        self.mudou.emit()

    def _proximo(self) -> None:
        if self._atual is None and self._fila:
            self._mostrar(self._fila.popleft())

    def _mostrar(self, aviso: _Aviso) -> None:
        self._atual = aviso
        self._texto, self._botao = aviso.texto, aviso.botao
        segundos = aviso.depois if aviso.depois is not None else aviso.segundos
        if segundos > 0:
            self._relogio.start(round(segundos * 1000))
        else:
            self._relogio.stop()
        self.mudou.emit()
