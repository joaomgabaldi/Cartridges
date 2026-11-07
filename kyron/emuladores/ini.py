# ini.py
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

"""Ler e gravar o idioma e o nome do jogador nos .ini dos emuladores de Steam.

Trabalha em bytes: só a linha da chave muda, o resto do arquivo (Latin-1, GBK, BOM, CRLF ou LF) sai idêntico.
O arquivo é entrada não confiável: lê no máximo 1 MiB e tolera qualquer byte.
"""

import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

LIMITE = 1 << 20
_BOM = b"\xef\xbb\xbf"
_COMENTARIOS = (b"#", b";", b"//")

# nome do arquivo (casefold) -> (seção, chave do AppID, do nome, do idioma)
FORMATOS: dict[str, tuple[str, Optional[str], Optional[str], Optional[str]]] = {
    "steam_emu.ini": ("Settings", "AppId", "UserName", "Language"),
    "codex.ini": ("Settings", "AppId", "UserName", "Language"),
    "ali213.ini": ("Settings", "AppID", "PlayerName", "Language"),
    "configs.user.ini": ("user::general", None, "account_name", "language"),
    "steam_appid.txt": ("", "", None, None),  # o conteúdo inteiro é o AppID
}


@dataclass(frozen=True)
class Valores:
    appid: Optional[str]
    nome: Optional[str]
    idioma: Optional[str]


def _formato(caminho: Path, formato: Optional[str]):
    return FORMATOS.get((formato or caminho.name).casefold())


def _ler_bytes(caminho: Path) -> Optional[bytes]:
    try:
        with open(caminho, "rb") as f:
            dados = f.read(LIMITE + 1)
    except OSError:
        return None
    return dados if len(dados) <= LIMITE else None


def _texto(linha: bytes) -> str:
    return linha.decode("latin-1").strip()


def _cabecalho(linha: bytes) -> Optional[str]:
    t = _texto(linha)
    fim = t.find("]")
    if not t.startswith("[") or fim < 0:
        return None
    resto = t[fim + 1:].strip()  # `[Settings] ; comentário` também é cabeçalho
    return t[1:fim].strip().casefold() if not resto or resto.startswith((";", "#")) else None


def _chave_valor(linha: bytes):
    """(chave em casefold, posição do valor na linha) de uma linha ativa 'chave = valor', ou None."""
    if linha.lstrip().startswith(_COMENTARIOS) or b"=" not in linha:
        return None
    esq, _, dir_ = linha.partition(b"=")
    return _texto(esq).casefold(), len(esq) + 1 + (len(dir_) - len(dir_.lstrip()))


def _procurar(linhas: list[bytes], secao: str, chave: str):
    """(índice do cabeçalho da seção ou None, índice da primeira linha ativa da chave ou None)."""
    secao, chave = secao.casefold(), chave.casefold()
    cabecalho = None
    atual = None
    for i, bruta in enumerate(linhas):
        linha = bruta[len(_BOM):] if i == 0 and bruta.startswith(_BOM) else bruta
        nome = _cabecalho(linha)
        if nome is not None:
            atual = nome
            if nome == secao and cabecalho is None:
                cabecalho = i
        elif atual == secao:
            kv = _chave_valor(linha)
            if kv and kv[0] == chave:
                return cabecalho, i
    return cabecalho, None


def _valor(linha: bytes, inicio: int) -> str:
    return _texto(linha[inicio:])


def ler(caminho: Path, formato: Optional[str] = None) -> Valores:
    fmt = _formato(caminho, formato)
    dados = _ler_bytes(caminho)
    if fmt is None or dados is None:
        return Valores(None, None, None)
    secao, k_appid, k_nome, k_idioma = fmt
    if not secao:
        return Valores(_texto(dados) or None, None, None)
    linhas = dados.split(b"\n")

    def pegar(chave):
        if not chave:
            return None
        _, i = _procurar(linhas, secao, chave)
        return (_valor(linhas[i], _chave_valor(linhas[i])[1]) or None) if i is not None else None

    return Valores(pegar(k_appid), pegar(k_nome), pegar(k_idioma))


_MAX_DLCS = 300  # cada um vira um item do menu da página do jogo
_MAX_NOME_DO_DLC = 200


def _decodificar(valor: bytes) -> str:
    """UTF-8, ou o ANSI do Windows (o ™ e o – da CODEX); o que não se imprime (controle, bidi, NBSP) vira espaço."""
    # shortcut: um .ini em GBK (ALI213 chinês) sai ilegível; detectar a codificação só se aparecer de verdade.
    try:
        texto = valor.decode("utf-8")
    except UnicodeDecodeError:
        texto = valor.decode("cp1252", errors="replace")
    return " ".join("".join(c if c.isprintable() else " " for c in texto).split())


def dlcs(caminho: Path, formato: Optional[str] = None) -> list[tuple[str, str]]:
    """(appID, nome) de cada linha `appID=nome` da seção [DLC], na ordem do arquivo, sem repetir o appID. [] se não há."""
    fmt = _formato(caminho, formato)
    if fmt is None or fmt[0].casefold() != "settings" or (dados := _ler_bytes(caminho)) is None:
        return []
    achados: dict[str, str] = {}
    atual = None
    for i, bruta in enumerate(dados.split(b"\n")):
        linha = bruta[len(_BOM):] if i == 0 and bruta.startswith(_BOM) else bruta
        if (nome := _cabecalho(linha)) is not None:
            atual = nome
        elif atual == "dlc" and (kv := _chave_valor(linha)) and kv[0].isdigit() and kv[0] not in achados:
            if texto := _decodificar(linha[kv[1]:])[:_MAX_NOME_DO_DLC]:
                achados[kv[0]] = texto
                if len(achados) >= _MAX_DLCS:
                    break
    return list(achados.items())


def _gravar(caminho: Path, dados: bytes) -> None:
    # temporário na mesma pasta + os.replace: o jogo nunca vê o arquivo pela metade
    fd, tmp = tempfile.mkstemp(dir=caminho.parent, prefix=caminho.name + ".")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(dados)
        os.replace(tmp, caminho)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def aplicar(caminho: Path, nome: Optional[str], idioma: Optional[str], formato: Optional[str] = None) -> bool:
    """Grava nome e idioma onde diferem. `None` = não mexer. `True` se gravou; `OSError` propaga.

    `ValueError` para valor que quebraria a linha ou o formato (fora do ASCII imprimível, `=`, `;`, `#`).
    """
    for valor in (nome, idioma):
        if valor is not None and not (valor.isascii() and valor.isprintable() and not set(valor) & set("=;#")):
            raise ValueError(f"Valor recusado para o .ini: {valor!r}")
    fmt = _formato(caminho, formato)
    if fmt is None or not fmt[0]:
        return False
    secao, _, k_nome, k_idioma = fmt
    pedidos = [(k, v) for k, v in ((k_nome, nome), (k_idioma, idioma)) if k and v is not None]
    if not pedidos:
        return False

    if not caminho.exists():
        # GSE sem configs.user.ini: só cria dentro de uma pasta steam_settings
        if caminho.parent.name.casefold() != "steam_settings" or caminho.name.casefold() != "configs.user.ini":
            return False
        corpo = f"[{secao}]\n" + "".join(f"{k}={v}\n" for k, v in pedidos)
        _gravar(caminho, corpo.encode("ascii"))
        return True

    dados = _ler_bytes(caminho)
    if dados is None:  # ilegível ou grande demais: melhor não tocar
        return False
    linhas = dados.split(b"\n")
    fim = b"\r" if linhas[0].endswith(b"\r") else b""
    mudou = False
    for chave, valor in pedidos:
        cabecalho, i = _procurar(linhas, secao, chave)
        novo = valor.encode("ascii")
        if i is not None:
            ini_valor = _chave_valor(linhas[i])[1]
            if _valor(linhas[i], ini_valor) == valor:
                continue
            linhas[i] = linhas[i][:ini_valor] + novo + (b"\r" if linhas[i].endswith(b"\r") else b"")
        elif cabecalho is not None:
            linhas.insert(cabecalho + 1, chave.encode("ascii") + b"=" + novo + fim)
        else:
            if linhas[-1] != b"":  # arquivo sem quebra final
                linhas[-1] += fim
                linhas.append(b"")
            linhas[-1:] = [f"[{secao}]".encode("ascii") + fim, chave.encode("ascii") + b"=" + novo + fim, b""]
        mudou = True
    if mudou:
        _gravar(caminho, b"\n".join(linhas))
    return mudou


def nome_valido(texto: str) -> bool:
    return re.fullmatch(r"[A-Za-z0-9_.\-\[\]()!@$&+~^ ]{1,32}", texto) is not None and texto == texto.strip()


def guarda_nome_ou_idioma(caminho: str) -> bool:
    """Pelo nome do arquivo, sem tocar o disco. Fora de FORMATOS só entram os modelos do language.changer, que têm os dois."""
    fmt = FORMATOS.get(Path(caminho).name.casefold())
    return fmt is None or bool(fmt[2] or fmt[3])


def nome_aceito(texto: str) -> bool:
    """O que as telas aceitam no campo do nome: vazio (usa o padrão) ou um nome válido."""
    return not texto.strip() or nome_valido(texto.strip())
