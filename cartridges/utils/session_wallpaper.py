# session_wallpaper.py
#
# Copyright 2026 kramo
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Veste os monitores em pé com a arte do jogo enquanto a sessão corre.

Só os monitores em pé, e por proporção, não por preferência: a arte de um jogo
é vertical ou vira vertical no corte, e espremer isso num monitor deitado dá
um resultado que ninguém escolheria. Quem está em pé é decidido pelo retângulo
que o Windows informa (altura maior que largura), então ligar, desligar ou
girar uma tela não pede configuração nenhuma.

A troca é por monitor, e isso descarta o caminho óbvio: o
``SystemParametersInfo(SPI_SETDESKWALLPAPER)`` de sempre pinta a área de
trabalho inteira, os três monitores de uma vez. Quem sabe falar de um monitor
só é a ``IDesktopWallpaper``, COM desde o Windows 8, chamada aqui por ctypes
como o resto das APIs nativas do app.

O papel de parede de antes é guardado no GSettings, e não em memória, porque
o caminho de volta tem de sobreviver ao processo: o app fechado no meio da
sessão (ou morto) deixaria as três telas vestidas de um jogo que já acabou.
Com a chave em disco, o arranque seguinte desfaz — é o que :func:`restaurar`
faz quando :func:`restaurar_orfaos` a chama.
"""

import ctypes
import json
import logging
import time
from ctypes import POINTER, byref, c_uint, c_void_p, c_wchar_p, wintypes
from io import BytesIO
from pathlib import Path
from typing import Any, NamedTuple, Optional, TYPE_CHECKING

from PIL import Image, ImageFilter, ImageOps

from cartridges import shared
from cartridges.utils.download import download_bytes
from cartridges.utils.wallhaven import IMAGE_SUFFIXES, melhor_para

if TYPE_CHECKING:
    from cartridges.game import Game

# O que a `enquadrar` usa quando o corte é vertical. Não é o meio: numa arte de
# jogo o que importa costuma estar na metade de cima (rosto, título), e centrar
# come a testa antes de comer o chão.
CENTRO_VERTICAL = 0.4

# Onde a escolha automática cai quando não há monitor em pé ligado — a tela de
# escolha precisa de uma proporção mesmo com tudo desconectado.
ALVO_PADRAO = (1080, 1920)

_COINIT_APARTMENTTHREADED = 0x2
_CLSID_DESKTOP_WALLPAPER = "{C2CF3110-460E-4FC1-B9D0-8A1C0C9CC4BD}"
_IID_IDESKTOP_WALLPAPER = "{B92B56A9-8B55-4E14-9A89-0199BBB6F93B}"
# INPROC | INPROC_HANDLER | LOCAL | REMOTE. Só INPROC_SERVER responde
# REGDB_E_CLASSNOTREG aqui, ainda que a classe esteja perfeitamente registrada.
_CLSCTX_ALL = 23


class _GUID(ctypes.Structure):
    _fields_ = [
        ("d1", ctypes.c_ulong),
        ("d2", ctypes.c_ushort),
        ("d3", ctypes.c_ushort),
        ("d4", ctypes.c_ubyte * 8),
    ]


class Monitor(NamedTuple):
    """Um monitor em pé: o id que a COM entende e o tamanho dele."""

    id: str
    largura: int
    altura: int


class _AreaDeTrabalho:
    """A ``IDesktopWallpaper`` viva, com COM iniciado nesta thread.

    Use como gerenciador de contexto: a inicialização do COM é por thread, e
    desfazê-la fora da que a fez não desfaz nada.
    """

    def __init__(self) -> None:
        self._ole32 = ctypes.windll.ole32  # type: ignore
        self._hresult = -1
        self._ponteiro = c_void_p()

    def __enter__(self) -> "_AreaDeTrabalho":
        self._hresult = self._ole32.CoInitializeEx(None, _COINIT_APARTMENTTHREADED)
        clsid, iid = _GUID(), _GUID()
        self._ole32.CLSIDFromString(c_wchar_p(_CLSID_DESKTOP_WALLPAPER), byref(clsid))
        self._ole32.CLSIDFromString(c_wchar_p(_IID_IDESKTOP_WALLPAPER), byref(iid))
        if self._ole32.CoCreateInstance(
            byref(clsid), None, _CLSCTX_ALL, byref(iid), byref(self._ponteiro)
        ):
            self.__exit__(None, None, None)
            raise OSError("IDesktopWallpaper indisponível")

        tabela = ctypes.cast(self._ponteiro, POINTER(POINTER(c_void_p))).contents

        def metodo(indice: int, *argumentos: Any) -> Any:
            return ctypes.WINFUNCTYPE(ctypes.HRESULT, c_void_p, *argumentos)(
                tabela[indice]
            )

        # A ordem da vtable é a da interface, IUnknown incluído nos três
        # primeiros lugares. Errar um índice aqui chama o método vizinho com
        # os argumentos deste, e o que sai disso não é um erro: é a memória
        # errada sendo lida.
        self._set = metodo(3, c_wchar_p, c_wchar_p)
        self._get = metodo(4, c_wchar_p, POINTER(c_wchar_p))
        self._id_em = metodo(5, c_uint, POINTER(c_wchar_p))
        self._quantos = metodo(6, POINTER(c_uint))
        self._retangulo = metodo(7, c_wchar_p, POINTER(wintypes.RECT))
        return self

    def __exit__(self, *_args: Any) -> None:
        if self._ponteiro:
            ctypes.cast(
                ctypes.cast(self._ponteiro, POINTER(POINTER(c_void_p))).contents[2],
                ctypes.WINFUNCTYPE(ctypes.c_ulong, c_void_p),
            )(self._ponteiro)
            self._ponteiro = c_void_p()
        if self._hresult in (0, 1):  # S_OK / S_FALSE: o COM é nosso
            self._ole32.CoUninitialize()

    def em_pe(self) -> list[Monitor]:
        """Os monitores ligados cujo retângulo é mais alto que largo."""
        quantos = c_uint()
        if self._quantos(self._ponteiro, byref(quantos)):
            return []

        monitores = []
        for indice in range(quantos.value):
            identificador = c_wchar_p()
            if self._id_em(self._ponteiro, indice, byref(identificador)):
                continue
            retangulo = wintypes.RECT()
            try:
                self._retangulo(self._ponteiro, identificador, byref(retangulo))
            except OSError:
                # A lista inclui monitor que já esteve ligado nesta máquina e
                # não está mais; esse não tem retângulo.
                continue
            largura = retangulo.right - retangulo.left
            altura = retangulo.bottom - retangulo.top
            if altura > largura > 0:
                monitores.append(Monitor(identificador.value or "", largura, altura))
        return monitores

    def papel(self, monitor: str) -> str:
        """O papel de parede do monitor agora. Vazio quando não há um."""
        atual = c_wchar_p()
        try:
            self._get(self._ponteiro, monitor, byref(atual))
        except OSError:
            return ""
        return atual.value or ""

    def vestir(self, monitor: str, caminho: str) -> None:
        try:
            self._set(self._ponteiro, monitor, caminho)
        except OSError as erro:
            logging.warning("Não foi possível trocar o papel de parede: %s", erro)


# region Enquadramento


def enquadrar(
    imagem: Image.Image, largura: int, altura: int, posicao: float = 0.5
) -> Image.Image:
    """Recorta ``imagem`` para ``largura`` x ``altura``, na faixa ``posicao``.

    A única regra de enquadramento do recurso, e o motivo de ser uma função
    só: a grade da tela de escolha corta a miniatura de 432px por aqui e o
    arquivo final corta o original de 4K por aqui. Como o ``ImageOps.fit``
    trabalha em proporção, as duas dão o MESMO quadro — o que se vê ao
    escolher é o que vai para o monitor, e não uma aproximação dele.

    ``posicao`` corre no eixo que sobra (0 = esquerda/topo, 1 = direita/pé).
    Qual eixo é esse depende das duas proporções, e é o que
    :func:`eixo_do_corte` responde para quem desenha a barrinha.
    """
    if eixo_do_corte(imagem.width, imagem.height, largura, altura):
        centro = (posicao, CENTRO_VERTICAL)
    else:
        centro = (0.5, posicao)
    return ImageOps.fit(imagem, (largura, altura), Image.LANCZOS, centering=centro)


def eixo_do_corte(
    origem_largura: int, origem_altura: int, largura: int, altura: int
) -> bool:
    """True quando o corte come as laterais; False quando come topo e pé."""
    if not origem_altura or not altura:
        return True
    # Empate devolve lateral: com as duas proporções iguais nada é cortado, e
    # o eixo só decide o texto da dica — que fala do caso comum, a arte larga.
    return (origem_largura / origem_altura) >= (largura / altura)


def da_capa(capa: Path, largura: int, altura: int) -> Image.Image:
    """A capa do jogo virando papel de parede: inteira, sobre ela mesma borrada.

    Reservado ao caso em que o wallhaven não tem nada: a capa é 2:3 e o monitor
    9:16, e cortar 30% da largura de uma capa apaga metade do título. Aqui o
    corte vai para o FUNDO, que já vai ser borrado, e a capa aparece inteira
    por cima.
    """
    with Image.open(capa) as arquivo:
        imagem = arquivo.convert("RGB")
        fundo = enquadrar(imagem, largura, altura).filter(ImageFilter.GaussianBlur(60))
        escala = min(largura / imagem.width, altura / imagem.height)
        frente = imagem.resize(
            (round(imagem.width * escala), round(imagem.height * escala)), Image.LANCZOS
        )
    fundo.paste(frente, ((largura - frente.width) // 2, (altura - frente.height) // 2))
    return fundo


# endregion
# region Escolha por jogo


def _sidecar(game_id: str) -> Path:
    return shared.wallpapers_dir / f"{game_id}.json"


def _ler_sidecar(game_id: str) -> Optional[dict[str, Any]]:
    try:
        with _sidecar(game_id).open(encoding="utf-8") as arquivo:
            dados = json.load(arquivo)
    except (OSError, ValueError):
        return None
    return dados if isinstance(dados, dict) else None


def _gravar_sidecar(
    game_id: str, name: str, arquivo: Optional[str], posicao: float, travado: bool
) -> None:
    shared.wallpapers_dir.mkdir(parents=True, exist_ok=True)
    dados = {
        "name": name,
        "file": arquivo,
        "position": posicao,
        "timestamp": int(time.time()),
        # Travado é escolha de gente. A busca automática nunca mexe nele, nem
        # quando o jogo é renomeado — foi o usuário que casou aquela arte com
        # aquele jogo, e isso vale mais que qualquer palpite de busca.
        "locked": travado,
    }
    try:
        _sidecar(game_id).write_text(json.dumps(dados), encoding="utf-8")
    except OSError as erro:
        logging.warning("Não foi possível gravar a escolha de parede: %s", erro)


def _arquivo_do_sidecar(dados: Optional[dict[str, Any]]) -> Optional[Path]:
    if not dados or not dados.get("file"):
        return None
    caminho = shared.wallpapers_dir / str(dados["file"])
    return caminho if caminho.is_file() else None


def escolha(game: "Game") -> str:
    """Como a parede deste jogo está decidida: ``auto``, ``manual`` ou ``none``."""
    dados = _ler_sidecar(game.game_id)
    if not dados or not dados.get("locked"):
        return "auto"
    return "manual" if _arquivo_do_sidecar(dados) else "none"


def imagem_escolhida(game_id: str) -> Optional[Path]:
    """A imagem que está valendo para ``game_id``, se houver uma em disco."""
    return _arquivo_do_sidecar(_ler_sidecar(game_id))


def salvar_escolha(
    game_id: str, name: str, origem: Path, posicao: float
) -> Optional[Path]:
    """Adota ``origem`` como a parede de ``game_id``. Trava a escolha."""
    sufixo = origem.suffix.lower()
    if sufixo not in IMAGE_SUFFIXES:
        sufixo = ".jpg"

    destino = shared.wallpapers_dir / f"{game_id}{sufixo}"
    try:
        shared.wallpapers_dir.mkdir(parents=True, exist_ok=True)
        _apagar_imagens(game_id, manter=destino.name)
        destino.write_bytes(origem.read_bytes())
    except OSError as erro:
        logging.warning("Não foi possível guardar a parede escolhida: %s", erro)
        return None

    _gravar_sidecar(game_id, name, destino.name, posicao, travado=True)
    return destino


def nao_trocar(game_id: str, name: str) -> None:
    """Este jogo não mexe na parede. Travado, para a busca não o reencontrar."""
    _apagar_imagens(game_id)
    _gravar_sidecar(game_id, name, None, 0.5, travado=True)


def redefinir(game_id: str) -> None:
    """Devolve o jogo à escolha automática."""
    _apagar_imagens(game_id)
    _sidecar(game_id).unlink(missing_ok=True)


def _apagar_imagens(game_id: str, manter: str = "") -> None:
    for sufixo in IMAGE_SUFFIXES:
        arquivo = shared.wallpapers_dir / f"{game_id}{sufixo}"
        if arquivo.name != manter:
            arquivo.unlink(missing_ok=True)


def _fonte(game: "Game", largura: int, altura: int) -> Optional[tuple[Path, float]]:
    """A imagem de partida deste jogo e a faixa dela, baixando se precisar.

    ``None`` quando o jogo está marcado para não trocar a parede, ou quando
    não sobrou nem busca nem capa.
    """
    dados = _ler_sidecar(game.game_id)
    posicao = float(dados.get("position", 0.5)) if dados else 0.5

    if dados and dados.get("locked"):
        arquivo = _arquivo_do_sidecar(dados)
        return (arquivo, posicao) if arquivo else None

    # Uma busca automática que já deu certo fica em disco: a sessão seguinte
    # do mesmo jogo não toca a rede, e a parede aparece no instante em que o
    # bloqueador aparece.
    if (arquivo := _arquivo_do_sidecar(dados)) and dados.get("name") == game.name:
        return arquivo, posicao

    if achado := melhor_para(game.name, largura, altura):
        try:
            conteudo = download_bytes(str(achado["path"]), timeout=30)
            sufixo = Path(str(achado["path"])).suffix.lower()
            if sufixo not in IMAGE_SUFFIXES:
                sufixo = ".jpg"
            destino = shared.wallpapers_dir / f"{game.game_id}{sufixo}"
            shared.wallpapers_dir.mkdir(parents=True, exist_ok=True)
            _apagar_imagens(game.game_id, manter=destino.name)
            destino.write_bytes(conteudo)
        except Exception as erro:  # pylint: disable=broad-except
            logging.info("Não foi possível baixar a parede do jogo: %s", erro)
        else:
            _gravar_sidecar(game.game_id, game.name, destino.name, 0.5, travado=False)
            return destino, 0.5

    # Último degrau: a capa. Não fica guardada como fonte — ela já está em
    # `covers`, e uma cópia aqui envelheceria sozinha quando a capa mudasse.
    capa = game.get_cover_path()
    return (capa, 0.5) if capa else None


# endregion
# region Aplicar e restaurar

_CHAVE_ORIGINAIS = "session-wallpaper-saved"


def _cache() -> Path:
    return shared.wallpapers_dir / "cache"


def _limpar_cache() -> None:
    try:
        for arquivo in _cache().glob("*.jpg"):
            arquivo.unlink(missing_ok=True)
    except OSError:
        pass


def alvo() -> tuple[int, int]:
    """A resolução para a qual enquadrar. Usada pela tela de escolha."""
    try:
        with _AreaDeTrabalho() as area:
            if monitores := area.em_pe():
                return monitores[0].largura, monitores[0].altura
    except OSError:
        pass
    return ALVO_PADRAO


def aplicar(game: "Game") -> None:
    """Veste os monitores em pé com a arte de ``game``. Roda fora da thread de UI.

    Nunca levanta: isto é enfeite de sessão, e uma sessão de jogo não pode
    falhar porque um monitor foi desligado ou porque o site saiu do ar.
    """
    try:
        with _AreaDeTrabalho() as area:
            if not (monitores := area.em_pe()):
                return

            maior = max(monitores, key=lambda monitor: monitor.largura * monitor.altura)
            if not (fonte := _fonte(game, maior.largura, maior.altura)):
                return
            origem, posicao = fonte

            # Os originais são guardados uma vez só. Uma segunda sessão
            # gravaria por cima a arte do jogo anterior, e a volta ao papel de
            # parede de verdade se perderia para sempre.
            if not shared.schema.get_string(_CHAVE_ORIGINAIS):
                shared.schema.set_string(
                    _CHAVE_ORIGINAIS,
                    json.dumps({m.id: area.papel(m.id) for m in monitores}),
                )

            _cache().mkdir(parents=True, exist_ok=True)
            carimbo = int(time.time())
            # A capa entra pela composição com fundo borrado; tudo o mais é
            # arte larga o bastante para o corte.
            da_capa_ = origem.parent == shared.covers_dir
            for monitor in monitores:
                if da_capa_:
                    quadro = da_capa(origem, monitor.largura, monitor.altura)
                else:
                    with Image.open(origem) as arquivo:
                        quadro = enquadrar(
                            arquivo.convert("RGB"),
                            monitor.largura,
                            monitor.altura,
                            posicao,
                        )
                # Nome novo a cada sessão: o Windows guarda o papel de parede
                # por caminho, e reescrever o mesmo arquivo com outro conteúdo
                # deixa a tela com a imagem antiga.
                destino = _cache() / (
                    f"{game.game_id}-{monitor.largura}x{monitor.altura}-{carimbo}.jpg"
                )
                quadro.save(destino, quality=92)
                area.vestir(monitor.id, str(destino))
    except Exception as erro:  # pylint: disable=broad-except
        logging.warning("Não foi possível vestir os monitores: %s", erro)


def restaurar() -> None:
    """Devolve cada monitor ao papel de parede que tinha. Seguro chamar à toa."""
    guardados = shared.schema.get_string(_CHAVE_ORIGINAIS)
    if not guardados:
        return

    try:
        originais = json.loads(guardados)
    except ValueError:
        originais = {}

    try:
        with _AreaDeTrabalho() as area:
            for monitor, caminho in originais.items():
                # Monitor sem papel de parede antes fica sem agora: vesti-lo
                # de vazio apagaria o fundo em vez de devolvê-lo.
                if caminho:
                    area.vestir(monitor, caminho)
    except OSError as erro:
        logging.warning("Não foi possível devolver o papel de parede: %s", erro)

    # A chave sai mesmo quando a devolução falhou. Ela é a marca de "há uma
    # sessão vestindo as telas", e mantê-la faria a sessão seguinte guardar a
    # nossa própria arte como se fosse o papel de parede do usuário.
    shared.schema.set_string(_CHAVE_ORIGINAIS, "")
    _limpar_cache()


def restaurar_orfaos() -> None:
    """Desfaz no arranque a troca que uma sessão anterior não desfez."""
    if shared.schema.get_string(_CHAVE_ORIGINAIS):
        logging.info("Papel de parede de uma sessão anterior encontrado; desfazendo")
        restaurar()


# endregion


def imagem_para_textura_bytes(imagem: Image.Image) -> bytes:
    """PNG em memória, que é como o GTK aceita uma imagem do Pillow."""
    buffer = BytesIO()
    # Nível 1: a compressão aqui é pura perda de tempo — o PNG vive alguns
    # milissegundos, entre o Pillow e a textura.
    imagem.save(buffer, "png", compress_level=1)
    return buffer.getvalue()
