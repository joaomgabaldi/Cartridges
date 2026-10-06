"""O resultado de uma leitura cara de disco, guardado enquanto o que ela leu não muda.

A varredura passa por todos os jogos da biblioteca, e alguns arquivos são os mesmos
para todos eles (os manifests da Epic, o `loginusers.vdf` da Steam) ou para cada
abertura do estado de um jogo (o schema da Steam). A chave de cada leitura é a
assinatura do que ela lê (`assinatura`: caminho, mtime e tamanho): o arquivo
regravado tem outra assinatura e é lido de novo, então o cache nunca devolve um
conteúdo velho — só poupa a releitura do mesmo conteúdo.

Seguro entre threads (a varredura lê em segundo plano, o vigia na principal). Uma
leitura que levanta não fica guardada.
"""

import os
import stat
import threading
from collections import OrderedDict
from typing import Callable, Hashable, Optional, TypeVar

T = TypeVar("T")

Assinatura = tuple[str, int, int]


def assinatura(caminho: "os.PathLike[str] | str") -> Optional[Assinatura]:
    """``(caminho, mtime_ns, tamanho)`` do arquivo comum, ou None (ausente, pasta, ilegível)."""
    try:
        info = os.stat(caminho)
    except (OSError, ValueError):
        return None
    if not stat.S_ISREG(info.st_mode):
        return None
    return str(caminho), info.st_mtime_ns, info.st_size


class CacheDeLeitura:
    """Até ``capacidade`` resultados, os usados por último (LRU)."""

    def __init__(self, capacidade: int = 1) -> None:
        self.capacidade = capacidade
        self._itens: "OrderedDict[Hashable, object]" = OrderedDict()
        self._trava = threading.Lock()

    def obter(self, chave: Hashable, ler: Callable[[], T]) -> T:
        """O resultado guardado para ``chave`` ou, sem ele, o de ``ler()`` (que fica guardado)."""
        with self._trava:
            if chave in self._itens:
                self._itens.move_to_end(chave)
                return self._itens[chave]  # type: ignore[return-value]
        # Fora da trava: a leitura pode ser lenta, e duas threads lendo o mesmo
        # arquivo ao mesmo tempo só custam uma leitura a mais.
        valor = ler()
        with self._trava:
            self._itens[chave] = valor
            self._itens.move_to_end(chave)
            while len(self._itens) > self.capacidade:
                self._itens.popitem(last=False)
        return valor

    def clear(self) -> None:
        with self._trava:
            self._itens.clear()

    def __len__(self) -> int:
        return len(self._itens)
