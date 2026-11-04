# avisos.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A fila de avisos: um por vez, na ordem de chegada.

`dispensar_depois` só começa a contar quando o aviso ganha a vez (quem está na fila não está na tela). Cada aviso sai com o
fade (`_SAIDA_MS`) antes de o próximo entrar, e o tempo para com o mouse em cima. Tudo na thread principal.
"""

import itertools
from collections import deque
from collections.abc import Callable, Hashable
from dataclasses import dataclass

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

# O fade de saída do `Avisos.qml` (`Tema.duracaoCurta`).
_SAIDA_MS = 200


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
        self._saida = QTimer(self)
        self._saida.setSingleShot(True)
        self._saida.setInterval(_SAIDA_MS)
        self._saida.timeout.connect(self._proximo)
        # Quanto faltava ao parar o relógio (mouse sobre o aviso); None = não está parado.
        self._restante: int | None = None

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
        """Enfileira o aviso e devolve o id; `segundos=0` só sai por `dispensar`. Um aviso com a mesma `chave` de um na tela ou
        na fila o substitui e vai ao fim da fila.
        """
        if chave is not None:
            self.dispensar_chave(chave)
        novo = _Aviso(next(self._ids), texto, botao, ao_clicar, segundos, chave)
        self._fila.append(novo)
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
            self._contar(round(segundos * 1000))
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
        self._restante = None
        self._atual = None
        self._saida.start()
        self.mudou.emit()

    @Slot()
    def pausar(self) -> None:
        """Mouse sobre o aviso: o tempo para. Sem tempo correndo (`segundos=0`), nada a parar."""
        if self._atual is not None and self._relogio.isActive():
            self._restante = self._relogio.remainingTime()
            self._relogio.stop()

    @Slot()
    def retomar(self) -> None:
        if self._restante is not None:
            self._relogio.start(self._restante)
            self._restante = None

    def _contar(self, ms: int) -> None:
        # Com o mouse em cima, o novo prazo só começa a correr quando ele sair.
        if self._restante is not None:
            self._restante = ms
        else:
            self._relogio.start(ms)

    def _proximo(self) -> None:
        if self._atual is None and self._fila and not self._saida.isActive():
            self._mostrar(self._fila.popleft())

    def _mostrar(self, aviso: _Aviso) -> None:
        self._atual = aviso
        self._texto, self._botao = aviso.texto, aviso.botao
        segundos = aviso.depois if aviso.depois is not None else aviso.segundos
        if segundos > 0:
            self._contar(round(segundos * 1000))
        else:
            self._relogio.stop()
        self.mudou.emit()
