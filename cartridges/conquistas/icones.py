"""Os ícones das conquistas: baixados uma vez, guardados no cache, entregues
como textura na thread principal.

Uma lista de conquistas pode pedir dezenas de ícones de uma vez; quatro
trabalhadores bastam e não disputam a rede com o resto do app.
"""

import hashlib
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Optional

from gi.repository import Gdk, GLib
from requests.exceptions import RequestException

from cartridges import shared
from cartridges.utils.download import download_bytes

_MAX_BYTES = 512 * 1024
_trabalhadores = ThreadPoolExecutor(
    max_workers=4, thread_name_prefix="icone-conquista"
)


def _sem_parametros(origem: object) -> str:
    """A origem sem a query string, que pode carregar chave e nunca vai ao log."""
    return str(origem).split("?", 1)[0].split("#", 1)[0]


def _registrar_falha(o_que: str, origem: object, erro: BaseException) -> None:
    """Uma linha no log, sem a query string.

    Falhas esperadas (rede, disco, imagem ilegível) levam só o tipo do erro: a
    mensagem de uma falha de rede costuma trazer a URL inteira, com a chave.
    Qualquer outra coisa é defeito nosso e leva o traceback.
    """
    if isinstance(erro, (RequestException, OSError, GLib.Error)):
        logging.info(
            "%s (%s): %s", o_que, _sem_parametros(origem), type(erro).__name__
        )
    else:
        logging.warning(
            "%s (%s): %s",
            o_que,
            _sem_parametros(origem),
            type(erro).__name__,
            exc_info=True,
        )


def _resolver(origem: str) -> tuple[Optional[Path], bool]:
    """O arquivo do ícone e se ele veio do cache de downloads. Nunca levanta."""
    try:
        if not origem:
            return None, False
        if not origem.startswith(("http://", "https://")):
            caminho = Path(origem)
            return (caminho if caminho.is_file() else None), False

        sufixo = Path(_sem_parametros(origem)).suffix.lower()[:5] or ".jpg"
        destino = (
            shared.conquistas_cache_dir
            / "icones"
            / (hashlib.sha1(origem.encode("utf-8")).hexdigest() + sufixo)
        )
        if destino.is_file():
            return destino, True

        dados = download_bytes(origem, timeout=10, max_bytes=_MAX_BYTES)
        destino.parent.mkdir(parents=True, exist_ok=True)
        # Um nome por download: duas threads pedindo o mesmo ícone não pisam
        # no arquivo uma da outra.
        temporario = destino.with_name(f"{destino.name}.{uuid.uuid4().hex}.tmp")
        try:
            temporario.write_bytes(dados)
            try:
                temporario.replace(destino)
            except OSError:
                # No Windows, dois replace no mesmo destino ao mesmo tempo
                # fazem um deles falhar; se o arquivo já está lá (o outro
                # download, com o mesmo conteúdo, ganhou), basta.
                if not destino.is_file():
                    raise
        finally:
            try:
                temporario.unlink(missing_ok=True)
            except OSError:
                pass
        return destino, True
    except Exception as erro:  # noqa: BLE001 - nada daqui derruba o app
        _registrar_falha("Ícone de conquista indisponível", origem, erro)
        return None, False


def arquivo_local(origem: str) -> Optional[Path]:
    """O arquivo do ícone no disco, baixando-o se for preciso. Nunca levanta."""
    return _resolver(origem)[0]


def _textura(origem: str) -> Optional[Gdk.Texture]:
    """Resolve e decodifica o ícone. Nunca levanta."""
    caminho, do_cache = _resolver(origem)
    if caminho is None:
        return None
    try:
        return Gdk.Texture.new_from_filename(str(caminho))
    except Exception as erro:  # noqa: BLE001 - GLib.Error e o que mais vier
        _registrar_falha("Ícone de conquista ilegível", origem, erro)
        if do_cache:
            # Um arquivo ruim no cache (a página de um portal de rede salva
            # como imagem, por exemplo) ficaria ruim para sempre; apagado, o
            # próximo pedido baixa de novo.
            try:
                caminho.unlink(missing_ok=True)
            except OSError:
                pass
        return None


def carregar(origem: str, entregar: Callable[[Gdk.Texture], None]) -> None:
    """Carrega ``origem`` fora da tela e chama ``entregar`` na thread principal."""

    def trabalho() -> None:
        textura = _textura(origem)
        if textura is None:
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
        logging.debug("Ícone de conquista não agendado: %s", erro)


def encerrar() -> None:
    """Para de aceitar pedidos e descarta os que ainda não começaram.

    Chamado no encerramento do app: as threads do executor não são daemons, e
    com a rede travada os downloads na fila segurariam o processo vivo. Um
    download já em andamento termina sozinho (no máximo o tempo limite).
    Depois disto, ``carregar`` não faz nada. Nunca levanta.
    """
    try:
        _trabalhadores.shutdown(wait=False, cancel_futures=True)
    except Exception:  # noqa: BLE001
        logging.warning("Falha ao encerrar os ícones de conquistas", exc_info=True)
