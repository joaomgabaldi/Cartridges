"""O jogo da EA app no disco (conferido em 15/10/2026).

- registro: `HKLM\\SOFTWARE\\(WOW6432Node\\)EA Games\\<jogo>`, valores `DisplayName` e `Install Dir`;
  é a chave que torna um jogo candidato (o `installerdata.xml` sozinho vem junto em cópias da pasta);
- título: `<Install Dir>\\__Installer\\installerdata.xml`, `<gameTitle locale="pt_BR">` e depois
  `en_US`; sem o arquivo, o `DisplayName`.

Só disco e registro: nunca levanta, só em thread. O teste de emulador fica em `fontes`.
"""

import logging
import os
import re
import unicodedata
import winreg
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

_CHAVES = (
    r"SOFTWARE\EA Games",
    r"SOFTWARE\WOW6432Node\EA Games",
)
_TETO_XML = 2 * 1024 * 1024  # o do Battlefield 6 tem 357 KB
_MARCAS = str.maketrans("", "", "™®©")  # a NFKD transforma ™ em "TM"


@dataclass(frozen=True)
class Candidato:
    pasta: str  # `Install Dir` normalizado (caixa e barra final)
    titulo: str  # o primeiro de `titulos`
    titulos: tuple[str, ...] = ()  # pt_BR, en_US e DisplayName, sem repetir os normalizados


def normalizar(titulo: str) -> str:
    texto = unicodedata.normalize("NFKD", titulo.translate(_MARCAS))
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", texto.casefold())


def _pasta_normalizada(texto: str) -> Optional[str]:
    """None para vazio e para raiz de unidade (uma chave estragada pegaria o disco todo)."""
    if not texto.strip():
        return None
    pasta = Path(texto.strip())
    if pasta.parent == pasta:
        return None
    return os.path.normcase(str(pasta.resolve(strict=False)))


def chaves_do_registro() -> list[tuple[str, str]]:
    """``(DisplayName, Install Dir)`` de cada jogo, sem repetir; erro → ``[]``."""
    achados: list[tuple[str, str]] = []
    try:
        for caminho in _CHAVES:
            try:
                chave = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, caminho, 0, winreg.KEY_READ)
            except OSError:  # vista ausente ou sem permissão: a outra ainda vale
                continue
            with chave:
                indice = 0
                while True:
                    try:
                        nome = winreg.EnumKey(chave, indice)
                    except OSError:
                        break
                    indice += 1
                    try:
                        with winreg.OpenKey(chave, nome, 0, winreg.KEY_READ) as sub:
                            titulo = winreg.QueryValueEx(sub, "DisplayName")[0]
                            pasta = winreg.QueryValueEx(sub, "Install Dir")[0]
                    except OSError:
                        continue
                    par = (titulo if isinstance(titulo, str) else "", pasta)
                    if isinstance(pasta, str) and par not in achados:
                        achados.append(par)
    except OSError:
        return []
    return achados


def _titulos_do_xml(pasta: Path) -> list[str]:
    """Os ``gameTitle`` pt_BR e en_US, nesta ordem; sem o arquivo (caso normal) ou ilegível, ``[]``."""
    arquivo = pasta / "__Installer" / "installerdata.xml"
    try:
        if arquivo.stat().st_size > _TETO_XML:
            return []
        raiz = ET.parse(arquivo).getroot()
    except FileNotFoundError:
        return []
    except Exception as erro:  # pylint: disable=broad-exception-caught
        logging.warning("installerdata.xml da EA ilegível: %s", type(erro).__name__)
        return []
    achados = []
    for idioma in ("pt_BR", "en_US"):
        for item in raiz.iter("gameTitle"):
            if item.get("locale") == idioma and (item.text or "").strip():
                achados.append(item.text.strip())
                break
    return achados


def _sem_repetir(titulos: list[str]) -> tuple[str, ...]:
    vistos: dict[str, str] = {}
    for titulo in titulos:
        chave = normalizar(titulo)
        if chave and chave not in vistos:
            vistos[chave] = titulo
    return tuple(vistos.values())


def candidato(
    pastas: list[Path],
    chaves: Callable[[], list[tuple[str, str]]] = chaves_do_registro,
) -> Optional[Candidato]:
    """O jogo cuja chave `EA Games` aponta para uma das ``pastas`` (a do exe e as acima)."""
    try:
        lidas = chaves()
    except Exception as erro:  # pylint: disable=broad-exception-caught
        logging.warning("Falha ao reconhecer o jogo da EA: %s", type(erro).__name__)
        return None
    por_pasta = {}
    for titulo, instalacao in lidas:
        # Uma chave estragada não derruba as outras.
        try:
            normal = _pasta_normalizada(instalacao)
            if normal is not None:
                por_pasta.setdefault(normal, titulo)
        except Exception as erro:  # pylint: disable=broad-exception-caught
            logging.warning("Chave da EA ignorada: %s", type(erro).__name__)
    for pasta in pastas:
        try:
            normal = _pasta_normalizada(str(pasta))
            if normal in por_pasta:
                titulos = _sem_repetir([*_titulos_do_xml(pasta), por_pasta[normal].strip()])
                return Candidato(pasta=normal, titulo=titulos[0], titulos=titulos) if titulos else None
        except Exception as erro:  # pylint: disable=broad-exception-caught
            logging.warning("Falha ao reconhecer o jogo da EA: %s", type(erro).__name__)
    return None
