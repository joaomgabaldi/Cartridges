# session_wallpaper.py
#
# Copyright 2026 joaomgabaldi
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

"""Veste os outros monitores (todos menos o principal, onde o jogo roda) com a arte do jogo durante a sessão.

O principal é o único que começa na origem da área de trabalho, então ligar, desligar ou girar uma tela não pede configuração. A troca é por monitor: o ``SPI_SETDESKWALLPAPER`` pinta todos; só a ``IDesktopWallpaper`` (COM, por ctypes) fala de um.
O papel de parede de antes fica no GSettings, não em memória: o app morto no meio da sessão deixaria as telas vestidas, e o arranque seguinte desfaz (:func:`restaurar_orfaos`).
"""

import ctypes
import json
import logging
import threading
import time
import winreg
from ctypes import POINTER, byref, c_uint, c_void_p, c_wchar_p, wintypes
from io import BytesIO
from pathlib import Path
from typing import Any, NamedTuple, Optional, TYPE_CHECKING
from uuid import uuid4

from PIL import Image, ImageFilter, ImageOps

from cartridges import shared
from cartridges.utils import window_geometry
from cartridges.utils.download import MAX_WALLPAPER_BYTES, download_bytes
from cartridges.utils.ler_json import ler_json
from cartridges.utils.thread_principal import na_thread_principal
from cartridges.utils.wallhaven import IMAGE_SUFFIXES, melhor_para

if TYPE_CHECKING:
    from cartridges.game import Game

# O que a `enquadrar` usa no corte vertical: numa arte de jogo o que importa costuma estar na metade de cima (rosto, título).
CENTRO_VERTICAL = 0.4

# Onde a tela de escolha cai sem monitor-alvo ligado (ela precisa de uma proporção): deitado, o formato de quase toda arte e monitor.
PAISAGEM_PADRAO = (1920, 1080)

_COINIT_APARTMENTTHREADED = 0x2
_CLSID_DESKTOP_WALLPAPER = "{C2CF3110-460E-4FC1-B9D0-8A1C0C9CC4BD}"
_IID_IDESKTOP_WALLPAPER = "{B92B56A9-8B55-4E14-9A89-0199BBB6F93B}"
# INPROC | INPROC_HANDLER | LOCAL | REMOTE. Só INPROC_SERVER responde
# REGDB_E_CLASSNOTREG aqui, ainda que a classe esteja perfeitamente registrada.
_CLSCTX_ALL = 23
# DESKTOP_SLIDESHOW_STATE: uma apresentação de slides está configurada.
_DSS_SLIDESHOW = 0x2
# O Spotlight (Windows 11) não aparece no estado da IDesktopWallpaper (para ela é só uma imagem fixa): quem diz que está ligado é o registro, e qualquer das duas marcas basta.
_SPOTLIGHT = (
    (r"Software\Microsoft\Windows\CurrentVersion\DesktopSpotlight\Settings", "EnabledState", 1),
    (r"Software\Microsoft\Windows\CurrentVersion\Explorer\Wallpapers", "BackgroundType", 3),
)


def _spotlight_ligado() -> bool:
    for caminho, nome, ligado in _SPOTLIGHT:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, caminho) as chave:
                if winreg.QueryValueEx(chave, nome)[0] == ligado:
                    return True
        except OSError:
            continue
    return False


class _GUID(ctypes.Structure):
    _fields_ = [
        ("d1", ctypes.c_ulong),
        ("d2", ctypes.c_ushort),
        ("d3", ctypes.c_ushort),
        ("d4", ctypes.c_ubyte * 8),
    ]


class Monitor(NamedTuple):
    """Um monitor ligado: o id que a COM entende, onde ele começa e o tamanho."""

    id: str
    x: int
    y: int
    largura: int
    altura: int

    @property
    def em_pe(self) -> bool:
        return self.altura > self.largura

    @property
    def principal(self) -> bool:
        # O canto do principal fica na origem da área de trabalho, só o dele: os outros começam onde o arranjo os pôs, até em negativo.
        return self.x == 0 and self.y == 0


class _AreaDeTrabalho:
    """A ``IDesktopWallpaper`` viva, com COM iniciado nesta thread. Use como gerenciador de contexto: o COM é por thread, e desfazê-lo fora da que o fez não desfaz nada."""

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

        # A ordem da vtable é a da interface, IUnknown nos três primeiros lugares. Errar um índice chama o método vizinho com estes argumentos, e não dá erro: lê memória errada.
        self._set = metodo(3, c_wchar_p, c_wchar_p)
        # As duas que devolvem texto recebem um ponteiro cru e não c_wchar_p: a string é da COM e volta a ela em `CoTaskMemFree`, e o c_wchar_p copia o texto e perde o endereço.
        self._get = metodo(4, c_wchar_p, POINTER(c_void_p))
        self._id_em = metodo(5, c_uint, POINTER(c_void_p))
        self._quantos = metodo(6, POINTER(c_uint))
        self._retangulo = metodo(7, c_wchar_p, POINTER(wintypes.RECT))
        self._estado = metodo(17, POINTER(wintypes.DWORD))
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

    def _texto(self, ponteiro: c_void_p) -> str:
        if not ponteiro.value:
            return ""
        try:
            return ctypes.wstring_at(ponteiro.value)
        finally:
            self._ole32.CoTaskMemFree(ponteiro)

    def ligados(self) -> list[Monitor]:
        quantos = c_uint()
        if self._quantos(self._ponteiro, byref(quantos)):
            return []

        monitores = []
        for indice in range(quantos.value):
            bruto = c_void_p()
            try:
                self._id_em(self._ponteiro, indice, byref(bruto))
            except OSError:
                continue
            identificador = self._texto(bruto)
            retangulo = wintypes.RECT()
            try:
                self._retangulo(self._ponteiro, identificador, byref(retangulo))
            except OSError:
                # A lista inclui monitor que já esteve ligado e não está mais; esse não tem retângulo.
                continue
            largura = retangulo.right - retangulo.left
            altura = retangulo.bottom - retangulo.top
            if largura > 0 and altura > 0:
                monitores.append(
                    Monitor(identificador, retangulo.left, retangulo.top, largura, altura)
                )
        return monitores

    def papel(self, monitor: str) -> Optional[str]:
        """O papel de parede do monitor agora. Vazio se não mostra imagem (só a cor de fundo), ``None`` se a pergunta falhou: a primeira é um estado a devolver no fim, a segunda é não saber qual era, e o monitor não deve ser vestido."""
        atual = c_void_p()
        try:
            self._get(self._ponteiro, monitor, byref(atual))
        except OSError:
            return None
        return self._texto(atual)

    def em_apresentacao(self) -> bool:
        """True com uma apresentação de slides ou o Spotlight na área de trabalho: vestir por cima os troca por uma imagem fixa e devolver o caminho não os religa, então a sessão não mexe em nada."""
        if _spotlight_ligado():
            return True
        estado = wintypes.DWORD()
        try:
            self._estado(self._ponteiro, byref(estado))
        except OSError:
            return False
        return bool(estado.value & _DSS_SLIDESHOW)

    def vestir(self, monitor: str, caminho: str) -> bool:
        try:
            self._set(self._ponteiro, monitor, caminho)
        except OSError as erro:
            logging.warning("Não foi possível trocar o papel de parede: %s", erro)
            return False
        return True



def alvos(monitores: list[Monitor]) -> list[Monitor]:
    return [monitor for monitor in monitores if not monitor.principal]


class Formatos(NamedTuple):
    """O tamanho do maior monitor-alvo de cada orientação; None se não houver."""

    retrato: Optional[tuple[int, int]]
    paisagem: Optional[tuple[int, int]]

    @property
    def grade(self) -> tuple[int, int]:
        """O formato da tela de escolha: em pé só quando todos os alvos estão em pé; no arranjo misto é deitada (quase toda arte é, e o corte agressivo fica para o ajuste em pé)."""
        return self.paisagem or self.retrato or PAISAGEM_PADRAO

    @property
    def ratio(self) -> str:
        largura, altura = self.grade
        return "portrait" if altura > largura else "landscape"

    @property
    def minimo(self) -> tuple[int, int]:
        tamanhos = [tamanho for tamanho in (self.retrato, self.paisagem) if tamanho]
        if not tamanhos:
            return self.grade
        return (
            max(largura for largura, _altura in tamanhos),
            max(altura for _largura, altura in tamanhos),
        )


def formatos(monitores: list[Monitor]) -> Formatos:
    """Os formatos dos monitores-alvo entre ``monitores`` (a lista completa ou só os alvos: :func:`alvos` é filtro puro)."""

    def maior(orientacao: list[Monitor]) -> Optional[tuple[int, int]]:
        if not orientacao:
            return None
        monitor = max(orientacao, key=lambda item: item.largura * item.altura)
        return monitor.largura, monitor.altura

    alvo = alvos(monitores)
    return Formatos(
        maior([monitor for monitor in alvo if monitor.em_pe]),
        maior([monitor for monitor in alvo if not monitor.em_pe]),
    )


def formatos_ligados() -> Formatos:
    try:
        with _AreaDeTrabalho() as area:
            return formatos(area.ligados())
    except OSError:
        return Formatos(None, None)


# endregion
# region Enquadramento


def enquadrar(
    imagem: Image.Image, largura: int, altura: int, posicao: float = 0.5
) -> Image.Image:
    """Recorta ``imagem`` para ``largura`` x ``altura``, na faixa ``posicao``.

    A única regra de enquadramento: a miniatura de 432px da escolha e o original 4K do arquivo final passam por aqui, e como o ``ImageOps.fit`` trabalha em proporção,
    dão o MESMO quadro. ``posicao`` corre no eixo que sobra (0 = esquerda/topo, 1 = direita/pé), que :func:`eixo_do_corte` informa.
    """
    if eixo_do_corte(imagem.width, imagem.height, largura, altura):
        centro = (posicao, CENTRO_VERTICAL)
    else:
        centro = (0.5, posicao)
    return ImageOps.fit(imagem, (largura, altura), Image.LANCZOS, centering=centro)


def eixo_do_corte(
    origem_largura: int, origem_altura: int, largura: int, altura: int
) -> bool:
    if not origem_altura or not altura:
        return True
    # Empate devolve lateral: com as proporções iguais nada é cortado, e o eixo só decide o texto da dica (a arte larga, o caso comum).
    return (origem_largura / origem_altura) >= (largura / altura)


def corta(origem_largura: int, origem_altura: int, largura: int, altura: int) -> bool:
    """True quando enquadrar a origem no monitor remove alguma parte dela, com meio por cento de folga (a cópia reduzida arredonda um pixel: 1564x880 é a mesma arte 16:9 de 3840x2160)."""
    if not origem_altura or not altura:
        return False
    alvo = largura / altura
    return abs(origem_largura / origem_altura - alvo) > 0.005 * alvo


def da_capa(capa: Path, largura: int, altura: int) -> Image.Image:
    """A capa virando papel de parede: inteira, sobre ela mesma borrada. Só quando o wallhaven não tem nada: cortar 30% da largura de uma capa 2:3 apagaria metade do título, então o corte vai para o FUNDO, que já será borrado."""
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


class Posicoes(NamedTuple):
    """A faixa escolhida (0 a 1) para cada orientação de monitor: por orientação e não por monitor, pois dois em pé mostram o mesmo corte e o id muda quando o monitor troca de porta."""

    retrato: float = 0.5
    paisagem: float = 0.5

    def para(self, monitor: Monitor) -> float:
        return self.retrato if monitor.em_pe else self.paisagem


def _sidecar(game_id: str) -> Path:
    return shared.wallpapers_dir / f"{game_id}.json"


def _ler_sidecar(game_id: str) -> Optional[dict[str, Any]]:
    try:
        dados = ler_json(_sidecar(game_id))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as erro:
        logging.warning("Escolha de papel de parede ilegível (%s): %s", _sidecar(game_id).name, erro)
        return None
    return dados if isinstance(dados, dict) else None


def _posicoes(dados: Optional[dict[str, Any]]) -> Posicoes:
    if not dados:
        return Posicoes()
    return Posicoes(
        float(dados.get("position_portrait", 0.5)),
        float(dados.get("position_landscape", 0.5)),
    )


def _gravar_sidecar(
    game_id: str, name: str, arquivo: Optional[str], posicoes: Posicoes, travado: bool
) -> None:
    dados = {
        "name": name,
        "file": arquivo,
        "position_portrait": posicoes.retrato,
        "position_landscape": posicoes.paisagem,
        "timestamp": int(time.time()),
        # Travado é escolha do usuário: a busca automática nunca mexe, nem quando o jogo é renomeado.
        "locked": travado,
    }
    # tmp + replace: um sidecar truncado se lê como "automático" e entregaria a escolha travada à busca.
    destino = _sidecar(game_id)
    tmp = destino.with_name(f"{destino.name}.{uuid4().hex}.tmp")
    try:
        shared.wallpapers_dir.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(dados), encoding="utf-8")
        tmp.replace(destino)
    except OSError as erro:
        logging.warning("Não foi possível gravar a escolha de parede: %s", erro)
    finally:
        tmp.unlink(missing_ok=True)


def _arquivo_do_sidecar(dados: Optional[dict[str, Any]]) -> Optional[Path]:
    nome = str((dados or {}).get("file") or "")
    # Só um nome solto: um caminho absoluto ou de rede vindo de um backup abriria arquivos fora da pasta.
    if not nome or Path(nome).name != nome:
        return None
    caminho = shared.wallpapers_dir / nome
    return caminho if caminho.is_file() else None


def escolha(game: "Game") -> str:
    """Como a parede deste jogo está decidida: ``auto``, ``manual`` ou ``none``. "Não trocar" é o sidecar travado SEM arquivo; travado com arquivo sumido é escolha perdida, e o jogo volta à busca automática."""
    dados = _ler_sidecar(game.game_id)
    if not dados or not dados.get("locked"):
        return "auto"
    if not dados.get("file"):
        return "none"
    return "manual" if _arquivo_do_sidecar(dados) else "auto"


def imagem_escolhida(game_id: str) -> Optional[Path]:
    return _arquivo_do_sidecar(_ler_sidecar(game_id))


def posicoes_escolhidas(game_id: str) -> Posicoes:
    """As posições de recorte gravadas para ``game_id``, ou o padrão (0.5, 0.5). Usado pela exportação do backup."""
    return _posicoes(_ler_sidecar(game_id))


def salvar_escolha(
    game_id: str, name: str, origem: Path, posicoes: Posicoes
) -> Optional[Path]:
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

    _gravar_sidecar(game_id, name, destino.name, posicoes, travado=True)
    return destino


def nao_trocar(game_id: str, name: str) -> None:
    """Este jogo não mexe na parede. Travado, para a busca não o reencontrar."""
    _apagar_imagens(game_id)
    _gravar_sidecar(game_id, name, None, Posicoes(), travado=True)


def redefinir(game_id: str) -> None:
    """Devolve o jogo à escolha automática."""
    _apagar_imagens(game_id)
    _sidecar(game_id).unlink(missing_ok=True)


def _apagar_imagens(game_id: str, manter: str = "") -> None:
    for sufixo in IMAGE_SUFFIXES:
        arquivo = shared.wallpapers_dir / f"{game_id}{sufixo}"
        if arquivo.name != manter:
            arquivo.unlink(missing_ok=True)


def _fonte(
    game: "Game", largura: int, altura: int, formato: str
) -> Optional[tuple[Path, Posicoes]]:
    """A imagem de partida deste jogo e a faixa dela, baixando se precisar. ``largura`` x ``altura`` é o mínimo dos cortes e ``formato`` é por onde a busca começa.

    ``None`` se o jogo está marcado para não trocar a parede ou se não sobrou nem busca nem capa.
    """
    dados = _ler_sidecar(game.game_id)
    posicoes = _posicoes(dados)

    if dados and dados.get("locked"):
        if not dados.get("file"):
            return None  # "não trocar"
        if arquivo := _arquivo_do_sidecar(dados):
            return arquivo, posicoes
        # A escolha à mão apontava para um arquivo que sumiu: segue para a busca.

    # Uma busca automática que deu certo fica em disco: a sessão seguinte não toca a rede, e a parede aparece junto com o bloqueador.
    if (arquivo := _arquivo_do_sidecar(dados)) and dados.get("name") == game.name:
        return arquivo, posicoes

    if achado := melhor_para(game.name, largura, altura, formato):
        try:
            conteudo = download_bytes(
                str(achado["path"]), timeout=30, max_bytes=MAX_WALLPAPER_BYTES
            )
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
            _gravar_sidecar(
                game.game_id, game.name, destino.name, Posicoes(), travado=False
            )
            return destino, Posicoes()

    # Último degrau: a capa, que não é guardada como fonte (já está em `covers`, e uma cópia envelheceria quando a capa mudasse).
    capa = game.get_cover_path()
    return (capa, Posicoes()) if capa else None


# endregion
# region Aplicar e restaurar

_CHAVE_ORIGINAIS = "session-wallpaper-saved"

# Cada sessão ganha um número e só a corrente pode vestir as telas: a arte é preparada numa thread (segundos), e uma sessão curta acaba antes;
# sem o número, a preparação vestiria os monitores DEPOIS da devolução. Só a thread de UI mexe nele.
_sessao = 0


def _cache() -> Path:
    return shared.wallpapers_dir / "cache"


def _limpar_cache() -> None:
    try:
        for arquivo in _cache().glob("*.jpg"):
            arquivo.unlink(missing_ok=True)
    except OSError:
        pass


def comecar(game: "Game") -> None:
    """Começa a vestir as telas para ``game`` (thread de UI). Sem monitor além do principal, desliga a opção; quem religa é o usuário, nas Preferências."""
    if not window_geometry.has_secondary_monitor():
        shared.schema.set_boolean("session-wallpaper", False)
        return
    threading.Thread(target=aplicar, args=(game, _sessao), daemon=True).start()


def aplicar(game: "Game", sessao: int) -> None:
    """Prepara a arte de ``game`` para cada monitor-alvo, fora da UI; quem a põe na parede é :func:`_vestir`, na thread de UI, onde a sessão é conferida.

    Nunca levanta: é enfeite, e a sessão não pode falhar porque um monitor foi desligado ou o site saiu do ar.
    """
    try:
        with _AreaDeTrabalho() as area:
            if area.em_apresentacao():
                logging.info("Apresentação de slides ligada; parede intocada")
                return
            monitores = alvos(area.ligados())
        if not monitores:
            return

        arranjo = formatos(monitores)
        if not (fonte := _fonte(game, *arranjo.minimo, formato=arranjo.ratio)):
            return
        origem, posicoes = fonte

        _cache().mkdir(parents=True, exist_ok=True)
        carimbo = int(time.time())
        # A capa entra pela composição com fundo borrado; o resto é arte larga o bastante para o corte.
        da_capa_ = origem.parent == shared.covers_dir
        quadros = []
        for monitor in monitores:
            if da_capa_:
                quadro = da_capa(origem, monitor.largura, monitor.altura)
            else:
                with Image.open(origem) as arquivo:
                    quadro = enquadrar(
                        arquivo.convert("RGB"),
                        monitor.largura,
                        monitor.altura,
                        posicoes.para(monitor),
                    )
            # Nome novo a cada sessão: o Windows guarda o papel de parede por caminho, e reescrever o mesmo arquivo deixa a imagem antiga.
            destino = _cache() / (
                f"{game.game_id}-{monitor.largura}x{monitor.altura}-{carimbo}.jpg"
            )
            quadro.save(destino, quality=92)
            quadros.append((monitor.id, destino))
    except Exception as erro:  # pylint: disable=broad-except
        logging.warning("Não foi possível preparar a arte da sessão: %s", erro)
        return

    na_thread_principal(_vestir, sessao, quadros)


def _vestir(sessao: int, quadros: list[tuple[str, Path]]) -> None:
    """Põe na parede o que :func:`aplicar` preparou, na thread de UI: é onde a sessão é conferida sem corrida com :func:`restaurar`."""
    if sessao != _sessao:
        for _monitor, arquivo in quadros:
            try:
                arquivo.unlink(missing_ok=True)
            except OSError:
                pass
        return

    try:
        originais = json.loads(shared.schema.get_string(_CHAVE_ORIGINAIS) or "{}")
    except ValueError:
        originais = {}
    if not isinstance(originais, dict):
        originais = {}

    try:
        with _AreaDeTrabalho() as area:
            # O original de cada monitor é gravado ANTES de vestir: com a chave em disco, um app morto no meio da sessão deixa o caminho de volta.
            # Um monitor que já consta nela (devolução anterior que falhou) fica com o valor de lá: o que mostra agora pode ser a nossa arte.
            for monitor, _arquivo in quadros:
                if monitor not in originais:
                    if (atual := area.papel(monitor)) is not None:
                        originais[monitor] = atual
            if not originais:
                return
            shared.schema.set_string(_CHAVE_ORIGINAIS, json.dumps(originais))

            for monitor, arquivo in quadros:
                # Sem o original não há como voltar: não se veste.
                if monitor in originais:
                    area.vestir(monitor, str(arquivo))
    except Exception as erro:  # pylint: disable=broad-except
        logging.warning("Não foi possível vestir os monitores: %s", erro)


def restaurar() -> None:
    """Devolve cada monitor ao papel de parede que tinha; seguro chamar à toa. Encerra a sessão corrente antes de tudo, mesmo sem nada a devolver: com a arte ainda em preparo a chave está vazia, e a preparação vestiria as telas depois."""
    global _sessao  # pylint: disable=global-statement
    _sessao += 1

    guardados = shared.schema.get_string(_CHAVE_ORIGINAIS)
    if not guardados:
        return

    try:
        originais = json.loads(guardados)
    except ValueError:
        originais = {}
    if not isinstance(originais, dict):
        originais = {}

    try:
        with _AreaDeTrabalho() as area:
            # Vazio também volta: era o monitor só com a cor de fundo, e a IDesktopWallpaper aceita "" como "sem imagem".
            recusados = {
                monitor: caminho
                for monitor, caminho in originais.items()
                if not area.vestir(monitor, str(caminho))
            }
    except OSError as erro:
        # A chave fica: é o único registro dos originais (a sessão seguinte só acrescenta monitores que faltem) e o próximo arranque tenta de novo.
        logging.warning("Não foi possível devolver o papel de parede: %s", erro)
        return

    # Quem o Windows recusou fica na chave (o original no iCloud Drive sem rede, por exemplo); só sai quem voltou de fato. O cache vai embora assim
    # mesmo: a tela não depende dele (o Windows guarda a própria cópia), e mantê-lo para um monitor que nunca mais ligar o faria crescer.
    shared.schema.set_string(
        _CHAVE_ORIGINAIS, json.dumps(recusados) if recusados else ""
    )
    _limpar_cache()


def restaurar_orfaos() -> None:
    if shared.schema.get_string(_CHAVE_ORIGINAIS):
        logging.info("Papel de parede de uma sessão anterior encontrado; desfazendo")
        restaurar()


# endregion


def imagem_para_textura_bytes(imagem: Image.Image) -> bytes:
    """PNG em memória."""
    buffer = BytesIO()
    # Nível 1: o PNG vive alguns milissegundos entre o Pillow e a textura, comprimir é perda de tempo.
    imagem.save(buffer, "png", compress_level=1)
    return buffer.getvalue()
