"""O catálogo de um jogo da Ubisoft Connect, a partir do ZIP do cache do launcher.

O ZIP (`cache\\achievements\\<productId>_<hash>`, sem extensão) traz `<idioma>_loc.txt`
(UTF-8 com BOM, uma conquista por linha: `id⇥nome⇥descrição`) e `<id>.png`, conferidos em
05/10/2026. Não há raridade nem conquista oculta, e o ícone é um só: a bloqueada usa
o mesmo, em cinza (a página aplica o filtro). Os ícones são extraídos para o cache do app,
porque a página só sabe abrir um arquivo ou uma URL.

Só disco: roda em thread (varredura). O vigia, na thread principal, só lê o cache.
"""

import logging
import re
import time
import zipfile
import zlib
from pathlib import Path
from typing import Optional

from cartridges import shared
from cartridges.conquistas import catalogo
from cartridges.conquistas.catalogo import Catalogo, ConquistaInfo
from cartridges.conquistas.ubisoft import locais
from cartridges.conquistas.ubisoft.spool import PREFIXO
from cartridges.utils.gravar_atomico import gravar_atomico

_ZIP_MAXIMO = 20 * 1024 * 1024
_ENTRADAS_MAXIMAS = 2000
_LOC_MAXIMO = 1024 * 1024
# O mesmo teto dos ícones baixados (`icones._MAX_BYTES`).
_PNG_MAXIMO = 512 * 1024
_ID_MAXIMO = 2**31
_LOC = re.compile(r"([A-Za-z]{2}(?:-[A-Za-z0-9]{2,4})?)_loc\.txt")
_PNG = re.compile(r"([0-9]{1,10})\.png", re.IGNORECASE)
_ID = re.compile(r"[0-9]{1,10}")
_PREFERIDOS = ("pt-br", "en-us")
_ERROS_DO_ZIP = (
    OSError,
    zipfile.BadZipFile,
    zipfile.LargeZipFile,
    RuntimeError,
    NotImplementedError,
    EOFError,
    zlib.error,
    ValueError,
)


class _Ilegivel(Exception):
    """O ZIP não serve: grande demais, com entradas demais ou sem nenhum idioma legível."""


def chave(produto: str) -> str:
    return f"ubisoft-{produto}"


def pasta_dos_icones(produto: str) -> Path:
    return shared.conquistas_cache_dir / "ubisoft" / produto


def _ler_entrada(arquivo: zipfile.ZipFile, info: zipfile.ZipInfo, teto: int) -> Optional[bytes]:
    """O conteúdo da entrada, ou None se passar do teto (o declarado ou o real)."""
    if info.file_size > teto:
        return None
    with arquivo.open(info) as entrada:
        dados = entrada.read(teto + 1)
    return dados if len(dados) <= teto else None


def _linhas_do_loc(dados: bytes) -> dict[int, tuple[str, str]]:
    conquistas: dict[int, tuple[str, str]] = {}
    for linha in dados.decode("utf-8-sig", errors="replace").splitlines():
        partes = linha.split("\t", 2)
        if len(partes) != 3 or not _ID.fullmatch(partes[0].strip()):
            continue
        id_ = int(partes[0].strip())
        if 0 < id_ <= _ID_MAXIMO and id_ not in conquistas:
            conquistas[id_] = (partes[1].strip(), partes[2].strip())
    return conquistas


def _escolher(idiomas: dict[str, dict[int, tuple[str, str]]]) -> dict[int, tuple[str, str]]:
    """pt-BR; senão en-US; senão o primeiro idioma com conquistas, em ordem alfabética."""
    por_nome = {nome.casefold(): conquistas for nome, conquistas in idiomas.items()}
    for preferido in _PREFERIDOS:
        if por_nome.get(preferido):
            return por_nome[preferido]
    for nome in sorted(por_nome):
        if por_nome[nome]:
            return por_nome[nome]
    return {}


def _ler_zip(caminho: Path) -> tuple[dict[int, tuple[str, str]], dict[int, bytes]]:
    if caminho.stat().st_size > _ZIP_MAXIMO:
        raise _Ilegivel("ZIP grande demais")
    idiomas: dict[str, dict[int, tuple[str, str]]] = {}
    icones: dict[int, bytes] = {}
    with zipfile.ZipFile(caminho) as arquivo:
        infos = arquivo.infolist()
        if len(infos) > _ENTRADAS_MAXIMAS:
            raise _Ilegivel("entradas demais")
        for info in infos:
            nome = info.filename
            # Só nomes simples: nada de pasta, `..` ou barra (nada sai da pasta do produto).
            if info.is_dir() or "/" in nome or "\\" in nome or ".." in nome:
                continue
            if achado := _LOC.fullmatch(nome):
                dados = _ler_entrada(arquivo, info, _LOC_MAXIMO)
                if dados is None:
                    logging.info("Catálogo de conquistas da Ubisoft: idioma grande demais; ignorado")
                    continue
                idiomas[achado.group(1)] = _linhas_do_loc(dados)
            elif achado := _PNG.fullmatch(nome):
                dados = _ler_entrada(arquivo, info, _PNG_MAXIMO)
                if dados is None:
                    logging.info("Catálogo de conquistas da Ubisoft: ícone grande demais; ignorado")
                    continue
                icones[int(achado.group(1))] = dados
    conquistas = _escolher(idiomas)
    if not conquistas:
        raise _Ilegivel("sem idioma legível")
    return conquistas, icones


def _gravar_icone(destino: Path, dados: bytes) -> bool:
    """Grava como `icones._resolver`: duas varreduras podem gravar o mesmo ícone."""
    try:
        gravar_atomico(destino, dados, outro_igual_basta=True)
    except OSError as erro:
        logging.info("Ícone de conquista da Ubisoft não gravado: %s", type(erro).__name__)
        return False
    return True


def _montar(produto: str, caminho: Path) -> Catalogo:
    conquistas, icones = _ler_zip(caminho)
    pasta = pasta_dos_icones(produto)
    pasta.mkdir(parents=True, exist_ok=True)
    infos = []
    for id_ in sorted(conquistas):
        titulo, descricao = conquistas[id_]
        icone = ""
        if id_ in icones:
            destino = pasta / f"{id_}.png"
            if _gravar_icone(destino, icones[id_]):
                icone = str(destino)
        infos.append(ConquistaInfo(f"{PREFIXO}{id_}", titulo, descricao, icone, "", False))
    return Catalogo(tuple(infos), int(time.time()), False)


def obter(produto: str) -> tuple[Optional[Catalogo], bool]:
    """O catálogo do produto e se ele foi refeito agora. Nunca levanta.

    Refaz só quando o ZIP é mais novo que o catálogo guardado (o Ubisoft Connect o regrava
    ao fechar o jogo); sem ZIP, ou com ZIP ruim, vale o guardado.
    """
    guardado = catalogo.em_cache(chave(produto))
    try:
        caminho = locais.pacote(produto)
        if caminho is None:
            return guardado, False
        if guardado is not None and guardado.obtido_em >= int(caminho.stat().st_mtime):
            return guardado, False
        novo = _montar(produto, caminho)
        catalogo.guardar(chave(produto), novo)
        return novo, True
    except (_Ilegivel, *_ERROS_DO_ZIP) as erro:
        logging.info("Catálogo de conquistas da Ubisoft ilegível (%s): %s", produto, type(erro).__name__)
        return guardado, False
    except Exception:  # pylint: disable=broad-exception-caught
        logging.warning("Falha ao montar o catálogo de conquistas da Ubisoft (%s)", produto, exc_info=True)
        return guardado, False
