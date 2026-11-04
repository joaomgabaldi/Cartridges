"""O cartão que aparece por cima do jogo quando uma conquista é desbloqueada."""

import array
import io
import logging
import threading
import wave
import winsound
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable, Optional

from pathlib import Path

from PySide6.QtCore import QTimer

from cartridges import shared
from cartridges.conquistas import progresso
from cartridges.utils.thread_principal import na_thread_principal

DURACAO = 5
_LIMITE_DA_SAIDA = 1


_ARQUIVO_DO_SOM = Path(__file__).resolve().parent.parent / "data" / "sons" / "conquista.wav"
_dados_do_som: Optional[bytes] = None


def _agendar(segundos: int, funcao: Callable[[], Any]) -> None:
    QTimer.singleShot(segundos * 1000, funcao)


def _som() -> bytes:
    """O WAV do aviso, lido uma vez; levanta se o arquivo faltar."""
    global _dados_do_som  # pylint: disable=global-statement
    if _dados_do_som is None:
        _dados_do_som = _ARQUIVO_DO_SOM.read_bytes()
    return _dados_do_som


def _em_segundo_plano(funcao: Callable[..., Any], *args: Any) -> None:
    threading.Thread(target=funcao, args=args, daemon=True).start()


def _tocar_som() -> None:
    try:
        if not shared.schema.get_boolean("conquistas-aviso-som"):
            return
        volume = shared.schema.get_int("conquistas-aviso-som-volume")
        _em_segundo_plano(_reproduzir, _som(), volume)
    except Exception:  # pylint: disable=broad-exception-caught
        logging.warning("Não foi possível tocar o som do aviso de conquista", exc_info=True)


def _no_volume(dados: bytes, volume: int) -> bytes:
    """O WAV (PCM 16-bit) escalado a ``volume`` por cento (``PlaySound`` não tem volume)."""
    if volume >= 100:
        return dados
    with wave.open(io.BytesIO(dados)) as entrada:
        if entrada.getsampwidth() != 2:
            raise ValueError("o som não é PCM de 16 bits")
        parametros = entrada.getparams()
        amostras = array.array("h", entrada.readframes(entrada.getnframes()))
    fator = volume / 100  # nunca acima de 1: o resultado cabe em 16 bits
    amostras = array.array("h", (round(amostra * fator) for amostra in amostras))
    saida = io.BytesIO()
    with wave.Wave_write(saida) as escrita:
        escrita.setparams(parametros)
        escrita.writeframes(amostras.tobytes())
    return saida.getvalue()


_som_escalado: Optional[tuple[int, bytes]] = None


def _no_volume_guardado(dados: bytes, volume: int) -> bytes:
    global _som_escalado  # pylint: disable=global-statement
    guardado = _som_escalado
    if guardado is not None and guardado[0] == volume:
        return guardado[1]
    escalado = _no_volume(dados, volume)
    _som_escalado = (volume, escalado)
    return escalado


def _reproduzir(dados: bytes, volume: int) -> None:
    try:
        dados = _no_volume_guardado(dados, volume)
    except Exception:  # pylint: disable=broad-exception-caught
        logging.warning("Não foi possível ajustar o volume do aviso de conquista", exc_info=True)
    # SND_MEMORY não aceita SND_ASYNC: por isso a thread.
    try:
        winsound.PlaySound(dados, winsound.SND_MEMORY | winsound.SND_NODEFAULT)
    except Exception:  # pylint: disable=broad-exception-caught
        logging.warning("Falha ao tocar o som do aviso de conquista", exc_info=True)


@dataclass(frozen=True)
class Aviso:
    rotulo: str
    titulo: str
    descricao: str
    icone: str

    @classmethod
    def de(cls, desbloqueada: Any) -> Optional["Aviso"]:
        info = desbloqueada.info
        if info is None:
            return None
        rotulo = (
            _("Todas as conquistas desbloqueadas")
            if desbloqueada.completou
            else _("Conquista desbloqueada")
        )
        if info.rara and info.porcentagem is not None:
            # A variável é a porcentagem de jogadores, como "4,1%"
            rotulo += " · " + _("★ Rara, {}").format(
                progresso.porcentagem_em_texto(info.porcentagem)
            )
        return cls(rotulo, info.titulo, info.descricao, info.icone)

    @classmethod
    def exemplo(cls, porcentagem: float = 4.1) -> "Aviso":
        return cls(
            _("Conquista desbloqueada")
            + " · "
            + _("★ Rara, {}").format(progresso.porcentagem_em_texto(porcentagem)),
            _("Conquista de exemplo"),
            _("Assim o aviso aparece durante o jogo."),
            "",
        )


def _criar_janela(aviso: Aviso) -> Any:
    from cartridges.janela_do_aviso import JanelaDoAviso  # noqa: PLC0415

    return JanelaDoAviso(aviso)


_fila: deque[Aviso] = deque()
_atual: Optional[Any] = None
_vez = 0


def na_tela() -> Optional[str]:
    return _atual.titulo if _atual is not None else None


def mostrar(aviso: Aviso) -> None:
    _fila.append(aviso)
    if _atual is None:
        _proximo(com_som=True)


def _proximo(com_som: bool = True) -> bool:
    global _atual, _vez  # pylint: disable=global-statement
    if _atual is not None or not _fila:
        return False
    aviso = _fila.popleft()
    _vez += 1
    vez = _vez
    janela: Optional[Any] = None
    try:
        janela = _criar_janela(aviso)
        janela.entrar(shared.schema.get_string("conquistas-aviso-posicao"))
        _atual = janela
        if com_som:
            _tocar_som()
        _agendar(DURACAO, lambda: _esconder(vez))
    except Exception:  # pylint: disable=broad-exception-caught
        logging.warning("Não foi possível mostrar o aviso de conquista", exc_info=True)
        _atual = None
        _destruir(janela)
        if _fila:
            na_thread_principal(_proximo, com_som)
    return False


def _destruir(janela: Optional[Any]) -> None:
    if janela is None:
        return
    try:
        janela.fechar()
    except Exception:  # pylint: disable=broad-exception-caught
        logging.warning("Falha ao fechar o aviso de conquista", exc_info=True)


def _esconder(vez: int) -> bool:
    try:
        if vez != _vez or _atual is None:
            return False
        janela = _atual
        # Se a animação nunca terminar (janela encoberta, sem quadros), a fila não pode travar.
        _agendar(_LIMITE_DA_SAIDA, lambda: _forcar_saida(vez, janela))
        try:
            janela.sair(lambda: _saiu(vez, janela))
        except Exception:  # pylint: disable=broad-exception-caught
            logging.warning("Falha na saída do aviso de conquista", exc_info=True)
            _saiu(vez, janela)
    except Exception:  # pylint: disable=broad-exception-caught
        logging.warning("Falha ao fechar o aviso de conquista", exc_info=True)
    return False


def _forcar_saida(vez: int, janela: Any) -> bool:
    _saiu(vez, janela)
    return False


def _saiu(vez: int, janela: Any) -> None:
    global _atual  # pylint: disable=global-statement
    try:
        if vez != _vez or _atual is not janela:
            return
        _atual = None
        _destruir(janela)
        _proximo(com_som=False)
    except Exception:  # pylint: disable=broad-exception-caught
        logging.warning("Falha ao fechar o aviso de conquista", exc_info=True)


def fechar() -> None:
    global _atual, _vez  # pylint: disable=global-statement
    _fila.clear()
    _vez += 1
    janela, _atual = _atual, None
    _destruir(janela)
