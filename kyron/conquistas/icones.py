"""Os ícones das conquistas: baixados uma vez, guardados no cache, entregues como arquivo na thread principal.

Uma lista pode pedir dezenas de ícones de uma vez; quatro trabalhadores bastam e não disputam a rede com o resto do app.
"""

import hashlib
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Optional

from PySide6.QtGui import QImageReader
lazy from requests.exceptions import RequestException

from kyron import shared
from kyron.conquistas import arquivos
from kyron.utils.download import download_bytes
from kyron.utils.gravar_atomico import gravar_atomico
from kyron.utils.thread_principal import na_thread_principal

_MAX_BYTES = 512 * 1024
_trabalhadores = ThreadPoolExecutor(
    max_workers=4, thread_name_prefix="icone-conquista"
)


def _sem_parametros(origem: object) -> str:
    return str(origem).split("?", 1)[0].split("#", 1)[0]


def _registrar_falha(o_que: str, origem: object, erro: BaseException) -> None:
    """Uma linha no log, sem a query string.

    Falhas esperadas (rede ou disco) levam só o tipo do erro, pois a mensagem de uma falha de rede costuma trazer a URL com a chave; qualquer outra coisa é defeito e leva o traceback.
    """
    if isinstance(erro, (RequestException, OSError)):
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
    try:
        if not origem:
            return None, False
        if not origem.startswith(("http://", "https://")):
            # Caminho de rede nunca: só checar o arquivo já conecta no servidor.
            if arquivos.eh_caminho_de_rede(origem):
                return None, False
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
        # Duas threads podem pedir o mesmo ícone: o destino é o hash da origem.
        gravar_atomico(destino, dados, outro_igual_basta=True)
        return destino, True
    except Exception as erro:  # noqa: BLE001 - nada daqui derruba o app
        _registrar_falha("Ícone de conquista indisponível", origem, erro)
        return None, False


def arquivo_local(origem: str) -> Optional[Path]:
    return _resolver(origem)[0]


def _legivel(caminho: Path) -> bool:
    # `canRead` só olha a assinatura: um corpo cortado passaria e o QML ficaria sem ícone para sempre.
    return not QImageReader(str(caminho)).read().isNull()


def carregar(origem: str, entregar: Callable[[Path], None]) -> None:
    def trabalho() -> None:
        caminho, do_cache = _resolver(origem)
        if caminho is None:
            return
        if not _legivel(caminho):
            logging.info("Ícone de conquista ilegível (%s)", _sem_parametros(origem))
            if do_cache:
                # Um arquivo ruim no cache (a página de um portal de rede salva como imagem, por exemplo) ficaria ruim para sempre; apagado, o próximo pedido baixa de novo.
                try:
                    caminho.unlink(missing_ok=True)
                except OSError:
                    pass
            return

        def na_tela() -> None:
            try:
                entregar(caminho)
            except Exception:  # noqa: BLE001 - o destino pode já ter saído
                logging.info("Ícone de conquista sem destino", exc_info=True)

        na_thread_principal(na_tela)

    try:
        _trabalhadores.submit(trabalho)
    except RuntimeError as erro:  # o executor já foi encerrado
        logging.debug("Ícone de conquista não agendado: %s", erro)


def encerrar() -> None:
    """Para de aceitar pedidos e descarta os que não começaram.

    Chamado no encerramento: as threads do executor não são daemons, e com a rede travada os downloads na fila segurariam o processo vivo. Um download em andamento termina sozinho (no máximo o tempo limite). Nunca levanta.
    """
    try:
        _trabalhadores.shutdown(wait=False, cancel_futures=True)
    except Exception:  # noqa: BLE001
        logging.warning("Falha ao encerrar os ícones de conquistas", exc_info=True)
