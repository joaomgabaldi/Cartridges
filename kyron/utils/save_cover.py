# save_cover.py
#
# Copyright 2022-2023 kramo
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


import logging
import os
import tempfile
from pathlib import Path
from shutil import copyfile
from typing import Optional
from uuid import uuid4

from PIL import Image, UnidentifiedImageError
from PySide6.QtGui import QImage, QImageReader

from kyron import shared
from kyron.jogo import ANIMATED_SUFFIXES  # reexportado: mora ao lado de get_cover_path
from kyron.utils import copias_animadas
from kyron.utils.enquadramento import escala_sobre_fundo
from kyron.utils.na_tela import entregar_na_tela
from kyron.utils.thread_principal import na_thread_principal


# Formato do Pillow -> sufixo com que a capa animada é guardada.
_SUFIXO_ANIMADO = {"GIF": ".gif", "WEBP": ".webp", "PNG": ".apng"}


def _temporario(sufixo: str) -> Path:
    """Um arquivo temporário novo e vazio, que quem chama apaga."""
    descritor, caminho = tempfile.mkstemp(suffix=sufixo)
    os.close(descritor)
    return Path(caminho)


def convert_cover(cover_path: Optional[Path] = None, resize: bool = True) -> Optional[Path]:
    if not cover_path:
        return None

    if not resize and cover_path.suffix.lower() in Image.registered_extensions():
        return cover_path

    return _convert_readable_cover(cover_path, resize)


def _convert_readable_cover(cover_path: Path, resize: bool, via_qt: bool = False) -> Optional[Path]:
    tmp_path: Optional[Path] = None
    try:
        with Image.open(cover_path) as image:
            # O Pillow recusa contagens absurdas de pixels com DecompressionBombError (nem UnidentifiedImageError nem OSError):
            # escapava e derrubava a thread do importador. Vale como "capa ilegível".
            animated = getattr(image, "is_animated", False)
            fmt = (image.format or "").upper()

            # GIF, WebP animado e APNG ficam como vieram (a biblioteca toca as cópias de ``copias_animadas``):
            # recodificar num GIF de 256 cores dava banding e, no APNG, falha ao salvar.
            if animated and (suffix := _SUFIXO_ANIMADO.get(fmt)):
                tmp_path = _temporario(suffix)
                copyfile(cover_path, tmp_path)
                return tmp_path

            # Outro formato animado não tem pipeline de cópias: vira um still colorido do primeiro quadro.
            if animated:
                image.seek(0)

            # Talvez desnecessário no futuro: https://github.com/python-pillow/Pillow/issues/2663
            if image.mode not in ("RGB", "RGBA"):
                image = image.convert("RGBA")

            tmp_path = _temporario(".tiff")
            (image.resize(shared.image_size) if resize else image).save(
                tmp_path,
                compression="tiff_adobe_deflate",
            )
    except Image.DecompressionBombError:
        # Fora do fallback abaixo: ele regravaria a imagem gigante num TIFF e chamaria `convert_cover` de novo, sem fim.
        logging.warning("Cover refused, image too large: %s", Path(cover_path).name)
        return None
    except (UnidentifiedImageError, OSError, ValueError) as error:
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
        if via_qt:  # a intermediária do Qt também não abriu: sem segunda volta
            logging.warning("Could not convert cover %s: %s", Path(cover_path).name, error)
            return None
        return _convert_pelo_qt(cover_path, resize, error)
    except BaseException:
        # Qualquer outra falha: sem o temporário que ficou pela metade, e quem chamou decide.
        if tmp_path is not None:
            tmp_path.unlink(missing_ok=True)
        raise

    return tmp_path


def _convert_pelo_qt(cover_path: Path, resize: bool, motivo: Exception) -> Optional[Path]:
    """O que o Pillow não lê e o Qt lê: regrava num TIFF e passa de novo por `convert_cover`."""
    intermediaria = _temporario(".tiff")
    resultado: Optional[Path] = None
    try:
        leitor = QImageReader(str(cover_path))
        leitor.setAutoTransform(True)
        imagem: QImage = leitor.read()
        if imagem.isNull() or not imagem.save(str(intermediaria), "TIFF"):
            logging.warning("Could not convert cover %s: %s", Path(cover_path).name, motivo)
            return None
        # Sem redução (`composite_cover`), a TIFF do Qt já é a entrada; com ela, passa pelo Pillow uma vez só.
        resultado = _convert_readable_cover(intermediaria, True, via_qt=True) if resize else intermediaria
        return resultado
    except OSError as erro:
        logging.warning("Could not convert cover %s: %s", Path(cover_path).name, erro)
        return None
    finally:
        # Se devolveu a própria entrada (`resize=False`), apagá-la deixaria quem chamou com um caminho inexistente.
        if resultado is not intermediaria:
            intermediaria.unlink(missing_ok=True)


class UnreadableCoverError(Exception):
    """The candidate cover could not be decoded by Pillow."""


def composite_cover(image_path: Path) -> Image.Image:
    """``image_path`` no formato de capa, para uma capa escolhida de um arquivo (regra em `enquadramento`)."""
    # `convert_cover` devolve None para o que o Pillow não lê; `str(None)` virava um arquivo "None".
    converted = convert_cover(image_path, resize=False)
    if converted is None:
        raise UnreadableCoverError(image_path)
    try:
        with Image.open(converted) as aberta:
            source = aberta.convert("RGBA")
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as error:
        raise UnreadableCoverError(image_path) from error
    finally:
        # `convert_cover` pode devolver a entrada intacta; só o temporário que ele criou é nosso.
        if converted != image_path:
            converted.unlink(missing_ok=True)

    width, height = source.size
    cover_width, cover_height = shared.image_size
    scale = escala_sobre_fundo(width, height, shared.image_size)
    if scale is None:
        return source

    interp = Image.Resampling.BILINEAR
    cover = source.resize((2, 2), interp).resize((cover_width, cover_height), interp)
    x, y = (cover_width - width * scale) / 2, (cover_height - height * scale) / 2
    cover.alpha_composite(source.resize((int(width * scale), int(height * scale)), interp), (int(x), int(y)))
    return cover


def save_cover(game_id: str, cover_path: Path) -> None:
    shared.covers_dir.mkdir(parents=True, exist_ok=True)

    # As cópias reduzidas só são apagadas com a capa nova no lugar: até lá a tela ainda mostra a velha.

    if not cover_path:
        # Remoção explícita: toda forma anterior cai.
        for suffix in (*ANIMATED_SUFFIXES, ".tiff"):
            (shared.covers_dir / f"{game_id}{suffix}").unlink(missing_ok=True)
        entregar_na_tela(_refazer_copias, game_id, None, None)
        return

    # Capa animada mantém a extensão; o resto vira TIFF
    if cover_path.suffix.lower() in ANIMATED_SUFFIXES:
        dest = shared.covers_dir / f"{game_id}{cover_path.suffix.lower()}"
    else:
        dest = shared.covers_dir / f"{game_id}.tiff"

    # Copia para um tmp no mesmo diretório e só então assume o nome final: apagar antes deixava a capa ausente ou
    # truncada (num disco cheio), e uma truncada passa no `is_file()` do SGDB, que nunca mais re-busca. O `replace` é atômico.
    tmp_dest = dest.with_name(f"{dest.name}.{uuid4().hex}.tmp")
    try:
        copyfile(cover_path, tmp_dest)
        tmp_dest.replace(dest)
    finally:
        tmp_dest.unlink(missing_ok=True)

    # As formas de outro sufixo só caem com a nova no lugar.
    for suffix in (*ANIMATED_SUFFIXES, ".tiff"):
        if suffix != dest.suffix:
            (shared.covers_dir / f"{game_id}{suffix}").unlink(missing_ok=True)

    # Apagar, adotar e preparar as cópias numa entrega só, na principal: só a tela larga a cópia velha (``soltar``).
    entregar_na_tela(_refazer_copias, game_id, dest, cover_path)

    # Pode rodar numa thread de trabalho, mas o `update()` do jogo é da principal. A URL com `?v=<mtime_ns>` da grade troca a capa.
    na_thread_principal(_atualizar_jogo, game_id)


def _refazer_copias(game_id: str, dest: Optional[Path], cover_path: Optional[Path]) -> None:
    """Troca as cópias reduzidas do jogo pelas da capa nova (``dest``; ``None`` se a capa saiu). Na thread principal.

    O ``apagar`` invalida todo pedido existente: quem leu a capa velha não sobrevive.
    """
    # Uma capa gravada com sucesso vale mais que a provisória da sessão deixada por uma gravação que falhou (`Jogo.capa_da_sessao`).
    if (store := getattr(shared, "store", None)) is not None and (jogo := store.get(game_id)) is not None:
        jogo.capa_da_sessao = None
    copias_animadas.apagar(game_id)
    if dest is not None and dest.suffix in ANIMATED_SUFFIXES:
        # A prévia da edição pode já ter as cópias desta capa: o ``preparar`` só gera as que faltarem.
        copias_animadas.adotar(cover_path, dest)
        copias_animadas.preparar([(game_id, dest)])


def _atualizar_jogo(game_id: str) -> None:
    store = getattr(shared, "store", None)
    if store is not None and (jogo := store.get(game_id)) is not None:
        jogo.update()
