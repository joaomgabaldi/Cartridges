"""Onde o Ubisoft Connect deixa as conquistas neste PC (conferido em 05/10/2026).

- progresso: `%LOCALAPPDATA%\\Ubisoft Game Launcher\\spool\\<conta>\\<productId>.spool`;
- catálogo: `%ProgramData%\\Ubisoft\\Ubisoft Game Launcher\\cache\\achievements\\<productId>_<hash>`,
  um ZIP sem extensão (ao lado ficam cópias extraídas `file_<hash>`, que não interessam);
- jogos instalados: `HKLM\\SOFTWARE\\(WOW6432Node\\)Ubisoft\\Launcher\\Installs\\<productId>`,
  valor `InstallDir` (Playnite, `UplayLibrary.cs`).

O `.spool` e o ZIP só existem depois que o jogo é aberto pelo Ubisoft Connect neste PC.
Tudo aqui olha o disco ou o registro: só em thread (o vigia só lista o `.spool` de um jogo).
"""

import re
import winreg
from pathlib import Path
from typing import Optional

from cartridges.conquistas import arquivos

_INSTALACOES = (
    r"SOFTWARE\WOW6432Node\Ubisoft\Launcher\Installs",
    r"SOFTWARE\Ubisoft\Launcher\Installs",
)
_PRODUTO = re.compile(r"[0-9]{1,10}")


def pasta_do_spool() -> Path:
    return arquivos.pastas_do_sistema().localappdata / "Ubisoft Game Launcher" / "spool"


def pasta_do_cache() -> Path:
    return (
        arquivos.pastas_do_sistema().programdata
        / "Ubisoft"
        / "Ubisoft Game Launcher"
        / "cache"
        / "achievements"
    )


def _mtime(caminho: Path) -> Optional[float]:
    try:
        return caminho.stat().st_mtime
    except OSError:
        return None


def spools(produto: str) -> list[tuple[Path, str]]:
    """Os `.spool` do produto, de cada conta deste PC: ``(arquivo, conta)``."""
    try:
        contas = sorted(pasta for pasta in pasta_do_spool().iterdir() if pasta.is_dir())
    except OSError:
        return []
    achados = []
    for pasta in contas:
        arquivo = pasta / f"{produto}.spool"
        if arquivo.is_file():
            achados.append((arquivo, pasta.name))
    return achados


def spool(produto: str) -> Optional[tuple[Path, str]]:
    """O `.spool` modificado por último (a conta usada por último), ou None."""
    melhor: Optional[tuple[float, Path, str]] = None
    for arquivo, conta in spools(produto):
        quando = _mtime(arquivo)
        if quando is not None and (melhor is None or quando > melhor[0]):
            melhor = (quando, arquivo, conta)
    return (melhor[1], melhor[2]) if melhor is not None else None


def pacote(produto: str) -> Optional[Path]:
    """O ZIP do catálogo do produto (`<productId>_<hash>`), o mais novo, ou None."""
    nome = re.compile(rf"{re.escape(produto)}_[0-9A-Za-z]+")
    try:
        itens = list(pasta_do_cache().iterdir())
    except OSError:
        return None
    melhor: Optional[tuple[float, Path]] = None
    for item in itens:
        if not nome.fullmatch(item.name) or not item.is_file():
            continue
        quando = _mtime(item)
        if quando is not None and (melhor is None or quando > melhor[0]):
            melhor = (quando, item)
    return melhor[1] if melhor is not None else None


def _do_registro() -> dict[str, str]:
    """``productId → InstallDir`` como o registro guarda (texto cru); a chave de 32 bits vence."""
    achados: dict[str, str] = {}
    for caminho in _INSTALACOES:
        try:
            chave = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, caminho)
        except OSError:
            continue
        with chave:
            indice = 0
            while True:
                try:
                    produto = winreg.EnumKey(chave, indice)
                except OSError:
                    break
                indice += 1
                if not _PRODUTO.fullmatch(produto) or produto in achados:
                    continue
                try:
                    with winreg.OpenKey(chave, produto) as subchave:
                        valor = winreg.QueryValueEx(subchave, "InstallDir")[0]
                except OSError:
                    continue
                if isinstance(valor, str) and valor.strip():
                    achados[produto] = valor.strip()
    return achados


def instalacoes() -> dict[str, Path]:
    """``productId → pasta de instalação``. Só pasta absoluta, local e que não é a raiz
    do disco (que pegaria todo jogo instalado nele); caminho de rede nunca é tocado."""
    validas: dict[str, Path] = {}
    for produto, texto in _do_registro().items():
        if arquivos.eh_caminho_de_rede(texto):
            continue
        pasta = arquivos.raiz_de_instalacao(texto)
        if pasta is not None:
            validas[produto] = pasta
    return validas
