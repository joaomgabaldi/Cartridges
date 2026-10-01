"""Os ícones das conquistas: baixados uma vez, guardados no cache, entregues
como textura na thread principal.

Uma lista de conquistas pode pedir dezenas de ícones de uma vez; quatro
trabalhadores bastam e não disputam a rede com o resto do app.
"""

import hashlib
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Optional

from gi.repository import Gdk, GLib

from cartridges import shared
from cartridges.utils.download import download_bytes

_MAX_BYTES = 512 * 1024
_trabalhadores = ThreadPoolExecutor(
    max_workers=4, thread_name_prefix="icone-conquista"
)


def _sem_parametros(origem: str) -> str:
    """A origem sem a query string, que pode carregar chave e nunca vai ao log."""
    return origem.split("?", 1)[0].split("#", 1)[0]


def arquivo_local(origem: str) -> Optional[Path]:
    """O arquivo do ícone no disco, baixando-o se for preciso. Nunca levanta."""
    try:
        if not origem:
            return None
        if not origem.startswith(("http://", "https://")):
            caminho = Path(origem)
            return caminho if caminho.is_file() else None

        sufixo = Path(_sem_parametros(origem)).suffix.lower()[:5] or ".jpg"
        destino = (
            shared.conquistas_cache_dir
            / "icones"
            / (hashlib.sha1(origem.encode("utf-8")).hexdigest() + sufixo)
        )
        if destino.is_file():
            return destino
        dados = download_bytes(origem, timeout=10, max_bytes=_MAX_BYTES)
        destino.parent.mkdir(parents=True, exist_ok=True)
        temporario = destino.with_name(destino.name + ".tmp")
        temporario.write_bytes(dados)
        temporario.replace(destino)
        return destino
    except Exception as erro:  # noqa: BLE001 - nada daqui derruba o app
        # Só o tipo do erro: a mensagem de uma falha de rede pode trazer a URL
        # inteira, com a query string.
        logging.info(
            "Ícone de conquista indisponível (%s): %s",
            _sem_parametros(str(origem)),
            type(erro).__name__,
        )
        return None


def carregar(origem: str, entregar: Callable[[Gdk.Texture], None]) -> None:
    """Carrega ``origem`` fora da tela e chama ``entregar`` na thread principal."""

    def trabalho() -> None:
        try:
            caminho = arquivo_local(origem)
            if caminho is None:
                return
            textura = Gdk.Texture.new_from_filename(str(caminho))
        except Exception as erro:  # noqa: BLE001 - GLib.Error e o que mais vier
            logging.info(
                "Ícone de conquista ilegível (%s): %s",
                _sem_parametros(str(origem)),
                type(erro).__name__,
            )
            return

        def na_tela() -> bool:
            try:
                entregar(textura)
            except Exception:  # noqa: BLE001 - o widget pode já ter saído
                logging.info("Ícone de conquista sem destino", exc_info=True)
            return False

        GLib.idle_add(na_tela)

    try:
        _trabalhadores.submit(trabalho)
    except RuntimeError as erro:  # o executor já foi encerrado
        logging.info("Ícone de conquista não agendado: %s", erro)
