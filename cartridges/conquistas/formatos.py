"""Os arquivos em que os emuladores de Steam (e a Steam) gravam as conquistas.

Um leitor por formato, todos com a mesma saída: o que está desbloqueado, com o
nome interno da conquista (o "API name" da Steam) e a hora em segundos Unix.
Transcrito de `parse-achievement-formats.ts` e `parse-achievement-file.ts` do
Hydra Launcher (hydralauncher/hydra, licença MIT), que mantém esses formatos
contra arquivos reais há anos.

Nenhum leitor levanta. O jogo pode estar gravando o arquivo no instante da
leitura, e um arquivo pela metade vale "nada novo agora", não um erro: a leitura
seguinte, com o arquivo inteiro, pega o que faltou. E o histórico só soma, então
uma leitura vazia nunca apaga o que já foi guardado.
"""

import json
import logging
import re
import stat
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from cartridges.conquistas import keyvalues, schema_da_steam


@dataclass(frozen=True)
class Desbloqueio:
    """Uma conquista desbloqueada, do jeito que o arquivo a descreve."""

    nome: str
    # Segundos Unix. Zero quando o arquivo não diz quando foi.
    quando: int


PADRAO = "padrao"
ONLINEFIX = "onlinefix"
GOLDBERG = "goldberg"
USERSTATS = "userstats"
RLD = "rld"
SKIDROW = "skidrow"
TRES_DM = "3dm"
ALI213 = "ali213"
CREAMAPI = "creamapi"
RAZOR1911 = "razor1911"
STEAM = "steam"
STEAM_STATS = "steam-stats"

_DESBLOQUEADA = re.compile(r"\bunlocked\s*=\s*true\b", re.IGNORECASE)
# O limite do que o histórico aceita; acima disso a hora vale 0 ("sem data").
_HORA_MAXIMA = 2**63
_HORA = re.compile(r"(?:^|[{,\s])time\s*=\s*(\d+)", re.IGNORECASE)
_ESTADO_DA_STEAM = re.compile(r"^UserGameStats_(\d+)_(\d+)\.bin$", re.IGNORECASE)


def _linhas(caminho: Path) -> list[str]:
    texto = caminho.read_text(encoding="utf-8", errors="replace")
    if texto.startswith("\ufeff"):
        texto = texto[1:]
    return re.split(r"[\r\n]+", texto)


def _ler_ini(caminho: Path) -> dict[str, dict[str, str]]:
    """INI lido à mão, como no Hydra: seções repetidas recomeçam, `=` pode
    aparecer dentro do valor, e uma linha sem seção cai na seção ``""``."""
    secoes: dict[str, dict[str, str]] = {}
    atual = ""
    for linha in _linhas(caminho):
        linha = linha.strip()
        if not linha or linha.startswith(("#", ";")):
            continue
        if linha.startswith("[") and linha.endswith("]"):
            atual = linha[1:-1]
            secoes[atual] = {}
            continue
        nome, _sep, valor = linha.partition("=")
        secoes.setdefault(atual, {})[nome.strip()] = valor.strip()
    return secoes


def _ler_json(caminho: Path) -> Any:
    return json.loads(caminho.read_text(encoding="utf-8-sig"))


def _inteiro(valor: Any) -> int:
    try:
        return int(float(str(valor).strip() or 0))
    except (TypeError, ValueError, OverflowError):
        return 0


def _hora_do_hydra(valor: Any) -> int:
    """A regra de `parseUnlockTime`: texto de 7 dígitos vale mil vezes mais."""
    if isinstance(valor, str) and len(valor.strip()) == 7:
        return _inteiro(valor) * 1000
    return _inteiro(valor)


def _hexadecimal(valor: Any) -> Optional[int]:
    """Um inteiro de 32 bits gravado em hexadecimal, little-endian."""
    try:
        dados = bytes.fromhex(str(valor).strip())
    except ValueError:
        return None
    if not dados:
        return None
    return int.from_bytes(dados[:4].ljust(4, b"\0"), "little")


def _padrao(caminho: Path, chave_feita: str = "Achieved", chave_hora: str = "UnlockTime"):
    return [
        Desbloqueio(nome, _inteiro(campos.get(chave_hora)))
        for nome, campos in _ler_ini(caminho).items()
        if campos.get(chave_feita) == "1"
    ]


def _onlinefix(caminho: Path) -> list[Desbloqueio]:
    achados = []
    for nome, campos in _ler_ini(caminho).items():
        if campos.get("achieved") == "true":
            achados.append(Desbloqueio(nome, _inteiro(campos.get("timestamp"))))
        elif campos.get("Achieved") == "true":
            achados.append(Desbloqueio(nome, _hora_do_hydra(campos.get("TimeUnlocked", ""))))
    return achados


def _creamapi(caminho: Path) -> list[Desbloqueio]:
    return [
        Desbloqueio(nome, _hora_do_hydra(campos.get("unlocktime", "")))
        for nome, campos in _ler_ini(caminho).items()
        if campos.get("achieved") == "true"
    ]


def _skidrow(caminho: Path) -> list[Desbloqueio]:
    achados = []
    for nome, valor in _ler_ini(caminho).get("Achievements", {}).items():
        partes = valor.split("@")
        if partes[0] == "1":
            achados.append(Desbloqueio(nome, _inteiro(partes[-1])))
    return achados


def _goldberg(caminho: Path) -> list[Desbloqueio]:
    dados = _ler_json(caminho)
    if isinstance(dados, list):
        return [
            Desbloqueio(str(item.get("name", "")), _inteiro(item.get("earned_time")))
            for item in dados
            if isinstance(item, dict) and item.get("earned")
        ]
    if isinstance(dados, dict):
        return [
            Desbloqueio(str(nome), _inteiro(item.get("earned_time")))
            for nome, item in dados.items()
            if isinstance(item, dict) and item.get("earned")
        ]
    return []


def _tres_dm(caminho: Path) -> list[Desbloqueio]:
    secoes = _ler_ini(caminho)
    horas = secoes.get("Time", {})
    return [
        Desbloqueio(nome, _hexadecimal(horas.get(nome, "")) or 0)
        for nome, estado in secoes.get("State", {}).items()
        if estado == "0101"
    ]


def _rld(caminho: Path) -> list[Desbloqueio]:
    achados = []
    for nome, campos in _ler_ini(caminho).items():
        if nome == "Steam" or not campos.get("State"):
            continue
        if _hexadecimal(campos["State"]) == 1:
            achados.append(Desbloqueio(nome, _hexadecimal(campos.get("Time", "")) or 0))
    return achados


def _userstats(caminho: Path) -> list[Desbloqueio]:
    achados = []
    for nome, valor in _ler_ini(caminho).get("ACHIEVEMENTS", {}).items():
        if not _DESBLOQUEADA.search(valor):
            continue
        if hora := _HORA.search(valor):
            achados.append(Desbloqueio(nome.replace('"', ""), int(hora.group(1))))
    return achados


def _razor1911(caminho: Path) -> list[Desbloqueio]:
    achados = []
    for linha in _linhas(caminho):
        partes = linha.split(" ")
        if len(partes) >= 2 and partes[1] == "1":
            achados.append(Desbloqueio(partes[0], _inteiro(partes[2] if len(partes) > 2 else 0)))
    return achados


def _steam(caminho: Path) -> list[Desbloqueio]:
    """O cache da biblioteca da Steam. O Hydra lê só ``vecHighlight``; aqui
    entram todas as listas ``vec…``, porque as desbloqueadas ocultas e as que
    não estão em destaque moram nas outras."""
    achados = []
    for item in _ler_json(caminho):
        if not (isinstance(item, list) and len(item) == 2 and item[0] == "achievements"):
            continue
        for chave, lista in (item[1].get("data") or {}).items():
            if not (chave.startswith("vec") and isinstance(lista, list)):
                continue
            for conquista in lista:
                if isinstance(conquista, dict) and conquista.get("bAchieved"):
                    achados.append(
                        Desbloqueio(str(conquista.get("strID", "")), _inteiro(conquista.get("rtUnlocked")))
                    )
    return achados


# O schema (até algumas centenas de KB) muda só quando a Steam o regrava, e o
# estado muda a cada conquista: o schema já interpretado fica guardado por
# (caminho, mtime, tamanho). A varredura de abertura lê em outra thread.
_SCHEMAS_GUARDADOS = 8
_schemas: "OrderedDict[tuple[str, int, int], tuple]" = OrderedDict()
_trava_dos_schemas = threading.Lock()


def _tem_bit_ligado(bloco: Any) -> bool:
    if not isinstance(bloco, dict):
        return False
    bits = bloco.get("data")
    return not isinstance(bits, bool) and isinstance(bits, int) and bool(bits & 0xFFFFFFFF)


def _conquistas_do_schema(arquivo: Path, appid: str) -> tuple:
    """As conquistas do schema da Steam; ``()`` se ele não existe, e levanta
    ValueError se não pôde ser lido (esse caso nunca fica guardado)."""
    try:
        info = arquivo.stat()
    except OSError:
        return ()
    if not stat.S_ISREG(info.st_mode):
        return ()
    chave = (str(arquivo), info.st_mtime_ns, info.st_size)
    with _trava_dos_schemas:
        if chave in _schemas:
            _schemas.move_to_end(chave)
            return _schemas[chave]
    schema = keyvalues.ler(arquivo)
    if schema is None:
        raise ValueError("schema da Steam ilegível")
    achadas = tuple(schema_da_steam.conquistas(schema, appid))
    with _trava_dos_schemas:
        _schemas[chave] = achadas
        _schemas.move_to_end(chave)
        while len(_schemas) > _SCHEMAS_GUARDADOS:
            _schemas.popitem(last=False)
    return achadas


def _steam_stats(caminho: Path) -> list[Desbloqueio]:
    """O estado que a própria Steam guarda em `appcache\\stats`, o mesmo que ela
    grava no instante do desbloqueio. Ele só diz bloco e bit; o nome vem do
    schema do jogo, que mora na mesma pasta."""
    achado = _ESTADO_DA_STEAM.match(caminho.name)
    if achado is None:
        return []
    estado = keyvalues.ler(caminho)
    if estado is None:
        if not caminho.exists():
            raise FileNotFoundError(caminho)
        raise ValueError("estado da Steam ilegível")
    cache = estado.get("cache")
    # Estado sem nenhum bit ligado (o jogo ainda sem conquistas): nem olha o schema.
    if not isinstance(cache, dict) or not any(_tem_bit_ligado(bloco) for bloco in cache.values()):
        return []
    appid = achado.group(2)
    arquivo_do_schema = caminho.with_name(f"UserGameStatsSchema_{appid}.bin")
    achados = []
    for conquista in _conquistas_do_schema(arquivo_do_schema, appid):
        bloco = cache.get(conquista.bloco)
        if not isinstance(bloco, dict):
            continue
        bits = bloco.get("data")
        if isinstance(bits, bool) or not isinstance(bits, int):
            continue
        if not ((bits & 0xFFFFFFFF) >> conquista.bit) & 1:
            continue
        horas = bloco.get("AchievementTimes")
        quando = horas.get(str(conquista.bit), 0) if isinstance(horas, dict) else 0
        if isinstance(quando, bool) or not isinstance(quando, int):
            quando = 0
        achados.append(Desbloqueio(conquista.nome, quando))
    return achados


_LEITORES: dict[str, Callable[[Path], list[Desbloqueio]]] = {
    PADRAO: _padrao,
    ONLINEFIX: _onlinefix,
    GOLDBERG: _goldberg,
    USERSTATS: _userstats,
    RLD: _rld,
    SKIDROW: _skidrow,
    TRES_DM: _tres_dm,
    ALI213: lambda caminho: _padrao(caminho, "HaveAchieved", "HaveAchievedTime"),
    CREAMAPI: _creamapi,
    RAZOR1911: _razor1911,
    STEAM: _steam,
    STEAM_STATS: _steam_stats,
}


def _hora_valida(quando: Any) -> int:
    """A hora, ou 0 ("sem data") se for negativa ou grande demais para o histórico."""
    try:
        return int(quando) if 0 <= quando < _HORA_MAXIMA else 0
    except (TypeError, ValueError, OverflowError):
        return 0


def ler_ou_none(caminho: Path, formato: str) -> Optional[list[Desbloqueio]]:
    """Como `ler`, mas diz quando a leitura falhou.

    Devolve None se o arquivo não pôde ser lido ou entendido (em uso por outro
    programa, gravado pela metade). Devolve ``[]`` se o arquivo não existe, se o
    formato é desconhecido ou se ele foi lido sem nada desbloqueado. Nunca levanta.
    """
    leitor = _LEITORES.get(formato)
    if leitor is None:
        logging.warning("Formato de conquistas desconhecido: %s", formato)
        return []
    try:
        desbloqueios = leitor(caminho)
    except FileNotFoundError:
        return []
    except (
        OSError,
        ValueError,
        TypeError,
        AttributeError,
        KeyError,
        IndexError,
        ArithmeticError,
        RecursionError,
    ) as erro:
        logging.info("Conquistas ilegíveis em %s (%s): %s", caminho, formato, erro)
        return None
    return [
        Desbloqueio(d.nome.strip(), _hora_valida(d.quando)) for d in desbloqueios if d.nome.strip()
    ]


def ler(caminho: Path, formato: str) -> list[Desbloqueio]:
    """As conquistas desbloqueadas em ``caminho``. Nunca levanta."""
    return ler_ou_none(caminho, formato) or []
