# fontes_de_versao.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Descobre as versões mais novas das peças do build e o SHA-256 que o próprio publicador informa.

Resolver nunca instala nada: `pip install --dry-run --report -`, só rodas binárias (nunca sdist), para o
Python e a plataforma do app (win_amd64).
"""

import hashlib
import http.client
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from functools import wraps
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class Pino:
    nome: str
    versao: str
    sha256: str


def resolver_libs(
    arquivos_in: list[Path],
    python: str,
    restricoes: list[str] | None = None,
    rodar=subprocess.run,
) -> list[Pino] | None:
    """Pinos (com SHA-256 da roda escolhida) de tudo o que os `.in` puxam; `None` se o pip não resolver.

    `python` é "3.15"; `restricoes` são linhas extras como "PySide6==6.12.0".
    """
    cmd = [
        sys.executable, "-m", "pip", "install", "--dry-run", "--quiet", "--report", "-",
        "--only-binary=:all:", "--platform", "win_amd64", "--python-version", python,
        "--ignore-installed", "--disable-pip-version-check",
    ]
    for arquivo in arquivos_in:
        cmd += ["-r", str(arquivo)]
    cmd += restricoes or []
    resultado = rodar(cmd, capture_output=True, text=True, encoding="utf-8")
    if resultado.returncode != 0:
        return None
    try:
        itens = json.loads(resultado.stdout)["install"]
        return [
            Pino(
                i["metadata"]["name"],
                i["metadata"]["version"],
                i["download_info"]["archive_info"]["hashes"]["sha256"],
            )
            for i in itens
        ]
    except (ValueError, KeyError, TypeError):
        return None


def _normalizado(nome: str) -> str:
    return re.sub(r"[-_.]+", "-", nome).lower()


def texto_requirements(pinos: list[Pino], cabecalho: list[str]) -> str:
    """`nome==versao --hash=sha256:…`, por nome normalizado; o `cabecalho` (ex.: "-r requirements.txt") vai antes."""
    linhas = list(cabecalho)
    for p in sorted(pinos, key=lambda p: _normalizado(p.nome)):
        linhas.append(f"{p.nome}=={p.versao} --hash=sha256:{p.sha256}")
    return "\n".join(linhas) + "\n"


def gravar_requirements(destino: Path, pinos: list[Pino], cabecalho: list[str]) -> None:
    destino.write_text(texto_requirements(pinos, cabecalho), encoding="utf-8", newline="\n")


# --- fontes oficiais ---
#
# Tudo o que chega da rede é dado não confiável: versões passam por regex estrita, hashes têm de ser 64 hex
# (SHA-256) ou 40 hex (SHA-1 do Qt), e só se fala https. `ler` é a costura de teste (URL -> bytes).


class FonteIndisponivel(Exception):
    """A fonte não respondeu, respondeu fora do formato ou não existe."""


class NaoEncontrado(FonteIndisponivel):
    """HTTP 404: o recurso não existe (o Qt usa isso para dizer que a versão não existe)."""


class SemHash(Exception):
    """A fonte não publica um hash utilizável, ou o arquivo não confere com o que ela publicou."""


@dataclass(frozen=True)
class Arquivo:
    versao: str
    url: str
    sha256: str


_VERSAO = re.compile(r"\d+\.\d+\.\d+")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_SHA1 = re.compile(r"[0-9a-f]{40}")
_TAG = re.compile(r"[A-Za-z0-9._-]{1,64}")
_ASSET = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,127}")
_REPO = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")

URL_MANIFESTO_SETUP_PYTHON = "https://raw.githubusercontent.com/actions/python-versions/main/versions-manifest.json"
_PYTHON_API = "https://www.python.org/api/v2/downloads/"
_QT_RAIZ = "https://download.qt.io/online/qtsdkrepository/windows_x86/desktop/"
_GYAN = "https://www.gyan.dev/ffmpeg/builds/"


def ler_da_rede(url: str) -> bytes:
    if not url.startswith("https://"):
        raise FonteIndisponivel(f"Endereço sem https: {url}")
    pedido = urllib.request.Request(url, headers={"User-Agent": "Kyron-build"})
    token = os.environ.get("GITHUB_TOKEN")
    if token and urllib.parse.urlsplit(url).hostname == "api.github.com":
        # Sem token a API aceita 60 chamadas por hora; "unredirected" não leva o token a outro host.
        pedido.add_unredirected_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(pedido, timeout=60) as resposta:
            if not resposta.geturl().startswith("https://"):  # redirecionamento para http
                raise FonteIndisponivel(f"Redirecionamento sem https em {url}")
            return resposta.read()
    except urllib.error.HTTPError as erro:
        if erro.code == 404:
            raise NaoEncontrado(f"{url}: não encontrado") from erro
        raise FonteIndisponivel(f"{url}: HTTP {erro.code}") from erro
    except (urllib.error.URLError, OSError, http.client.HTTPException) as erro:  # HTTPException: IncompleteRead etc.
        raise FonteIndisponivel(f"{url}: {erro}") from erro


def _formato_conferido(funcao):
    """Resposta fora do formato esperado (JSON/XML ilegível, campo faltando) vira `FonteIndisponivel`."""

    @wraps(funcao)
    def interna(*args, **kw):
        try:
            return funcao(*args, **kw)
        except (KeyError, TypeError, AttributeError, IndexError, json.JSONDecodeError, ET.ParseError) as erro:
            raise FonteIndisponivel(f"{funcao.__name__}: resposta fora do formato esperado ({erro!r})") from erro

    return interna


def _versao_valida(versao: str) -> str:
    if not _VERSAO.fullmatch(versao):
        raise ValueError(f"Versão inválida: {versao!r}")
    return versao


def _chave(versao: str) -> tuple[int, ...]:
    """Chave numérica; o patch que falta conta como 0 ("1.6" == "1.6.0")."""
    numeros = tuple(int(n) for n in versao.split("."))
    return numeros + (0,) * (3 - len(numeros))


def _lista(ler, url: str) -> list:
    dados = json.loads(ler(url))
    if not isinstance(dados, list):
        raise TypeError("esperava uma lista")
    return dados


def _sha256_ou_none(valor) -> str | None:
    return valor if isinstance(valor, str) and _SHA256.fullmatch(valor) else None


def _texto_ascii(dados: bytes) -> str:
    try:
        return dados.decode("ascii").strip()
    except UnicodeDecodeError as erro:
        raise FonteIndisponivel("resposta não é texto ASCII") from erro


@_formato_conferido
def versoes_do_python(ler: Callable[[str], bytes] = ler_da_rede) -> list[str]:
    """Versões finais `3.x.y` publicadas no python.org, da mais nova para a mais velha."""
    achadas = set()
    for r in _lista(ler, _PYTHON_API + "release/?version=3&is_published=true"):
        achado = re.fullmatch(r"Python (3\.\d+\.\d+)", r["name"])
        if achado and r["pre_release"] is False:
            achadas.add(achado.group(1))
    return sorted(achadas, key=_chave, reverse=True)


@_formato_conferido
def python_embutido(versao: str, ler: Callable[[str], bytes] = ler_da_rede) -> Arquivo:
    """`python-{v}-embed-amd64.zip` com o `sha256_sum` que o python.org publica."""
    _versao_valida(versao)
    id_ = None
    for r in _lista(ler, _PYTHON_API + "release/?version=3&is_published=true"):
        if r["name"] == f"Python {versao}" and r["pre_release"] is False:
            achado = re.fullmatch(r"https://www\.python\.org/api/v2/downloads/release/(\d+)/", r["resource_uri"])
            id_ = achado.group(1) if achado else None
    if id_ is None:
        raise SemHash(f"Python {versao} não consta no python.org")
    nome = f"python-{versao}-embed-amd64.zip"
    url = f"https://www.python.org/ftp/python/{versao}/{nome}"
    for f in _lista(ler, _PYTHON_API + f"release_file/?release={id_}"):
        if f["url"] == url:
            sha = _sha256_ou_none(f["sha256_sum"])
            if sha:
                return Arquivo(versao, url, sha)
    raise SemHash(f"O python.org não publica o SHA-256 de {nome}")


@_formato_conferido
def versoes_do_setup_python(ler: Callable[[str], bytes] = ler_da_rede) -> set[str]:
    """Versões finais que o `actions/setup-python` consegue instalar no Windows x64."""
    return {
        e["version"]
        for e in _lista(ler, URL_MANIFESTO_SETUP_PYTHON)
        if e["stable"] is True
        and _VERSAO.fullmatch(e["version"])
        and any(f["platform"] == "win32" and f["arch"] == "x64" for f in e["files"])
    }


def _sha1_conferido(ler, url_arquivo: str) -> bytes:
    """Baixa o arquivo e confere o SHA-1 que o Qt publica ao lado dele (`.sha1`)."""
    try:
        publicado = _texto_ascii(ler(url_arquivo + ".sha1")).split()[0].lower()
    except (NaoEncontrado, IndexError) as erro:
        raise SemHash(f"O Qt não publica o SHA-1 de {url_arquivo}") from erro
    if not _SHA1.fullmatch(publicado):
        raise SemHash(f"SHA-1 publicado ilegível para {url_arquivo}")
    conteudo = ler(url_arquivo)
    if hashlib.sha1(conteudo).hexdigest() != publicado:
        raise SemHash(f"O arquivo baixado não confere com o SHA-1 publicado: {url_arquivo}")
    return conteudo


@_formato_conferido
def qt_sdk(versao: str, ler: Callable[[str], bytes] = ler_da_rede) -> tuple[str, str, str] | None:
    """`(QT_DATA, QTBASE_SHA256, QTDECLARATIVE_SHA256)`; `None` se o Qt não tem essa versão para MSVC 2022 x64.

    O Qt só publica SHA-1: o arquivo é baixado inteiro (na memória), conferido e só então se grava o SHA-256 dele.
    """
    _versao_valida(versao)
    n = versao.replace(".", "")
    pasta = f"{_QT_RAIZ}qt6_{n}/qt6_{n}_msvc2022_64/"
    try:
        xml = ET.fromstring(ler(pasta + "Updates.xml"))
    except NaoEncontrado:
        return None
    pacote = next((p for p in xml.findall("PackageUpdate") if p.findtext("Name") == f"qt.qt6.{n}.win64_msvc2022_64"), None)
    if pacote is None:
        return None
    versao_do_pacote = pacote.findtext("Version", "")
    achado = re.fullmatch(rf"{re.escape(versao)}-\d+-(\d{{12}})", versao_do_pacote)
    if not achado:
        raise FonteIndisponivel(f"Version do pacote Qt ilegível: {versao_do_pacote!r}")
    arquivos = [a.strip() for a in pacote.findtext("DownloadableArchives", "").split(",")]
    hashes = []
    for prefixo in ("qtbase-", "qtdeclarative-"):
        nome = next((a for a in arquivos if a.startswith(prefixo)), None)
        if nome is None:
            raise FonteIndisponivel(f"O pacote do Qt {versao} não traz {prefixo}*.7z")
        if not re.fullmatch(r"[A-Za-z0-9._-]+\.7z", nome):
            raise FonteIndisponivel(f"Nome de arquivo do Qt ilegível: {nome!r}")
        url = f"{pasta}qt.qt6.{n}.win64_msvc2022_64/{versao_do_pacote}{nome}"
        hashes.append(hashlib.sha256(_sha1_conferido(ler, url)).hexdigest())
    return achado.group(1), hashes[0], hashes[1]


@_formato_conferido
def qwindowkit(ler: Callable[[str], bytes] = ler_da_rede) -> tuple[str, str, str]:
    """`(tag, commit, commit_do_qmsetup)`: a tag `X.Y[.Z]` mais nova de `stdware/qwindowkit`."""
    base = "https://api.github.com/repos/stdware/qwindowkit/"
    tags = [t for t in _lista(ler, base + "tags?per_page=100") if re.fullmatch(r"\d+\.\d+(\.\d+)?", t["name"])]
    if not tags:
        raise FonteIndisponivel("stdware/qwindowkit: nenhuma tag de versão")
    tag = max(tags, key=lambda t: _chave(t["name"]))
    commit = tag["commit"]["sha"]
    qmsetup = json.loads(ler(base + f"contents/qmsetup?ref={tag['name']}"))
    if qmsetup["type"] != "submodule" or not (_SHA1.fullmatch(commit) and _SHA1.fullmatch(qmsetup["sha"])):
        raise FonteIndisponivel("commit ou submódulo do QWindowKit fora do formato")
    return tag["name"], commit, qmsetup["sha"]


@_formato_conferido
def ffmpeg(ler: Callable[[str], bytes] = ler_da_rede) -> tuple[Arquivo, str]:
    """Build essentials do gyan.dev (com o `.sha256` dele) e a URL do commit da tag `n<versão>` do FFmpeg."""
    versao = _texto_ascii(ler(_GYAN + "release-version"))
    if not re.fullmatch(r"\d+\.\d+(\.\d+)?", versao):
        raise FonteIndisponivel(f"Versão do ffmpeg ilegível: {versao!r}")
    url = f"{_GYAN}packages/ffmpeg-{versao}-essentials_build.zip"
    # Só a ausência ou um conteúdo ilegível vira SemHash; a rede fora do ar sobe como FonteIndisponivel.
    try:
        partes = ler(url + ".sha256").decode("ascii", "replace").split()
    except NaoEncontrado:
        partes = []
    sha = partes[0].lower() if partes else ""
    if not _SHA256.fullmatch(sha):
        raise SemHash(f"O gyan.dev não publica o SHA-256 do ffmpeg {versao}")
    commit = json.loads(ler(f"https://api.github.com/repos/FFmpeg/FFmpeg/commits/n{versao}"))["sha"]
    if not (isinstance(commit, str) and _SHA1.fullmatch(commit)):
        raise FonteIndisponivel("commit da tag do FFmpeg fora do formato")
    return Arquivo(versao, url, sha), f"https://github.com/FFmpeg/FFmpeg/commit/{commit[:10]}"


@_formato_conferido
def release_do_github(repo: str, ler: Callable[[str], bytes] = ler_da_rede, prefixo_da_tag: str = "") -> tuple[str, dict[str, str]]:
    """Tag da release mais nova (sem prerelease nem rascunho) e `{asset: sha256}` do campo `digest`."""
    if not _REPO.fullmatch(repo):
        raise ValueError(f"Repositório inválido: {repo!r}")
    for r in _lista(ler, f"https://api.github.com/repos/{repo}/releases?per_page=30"):
        tag = r["tag_name"]
        if r["draft"] or r["prerelease"] or not _TAG.fullmatch(tag) or not tag.startswith(prefixo_da_tag):
            continue
        assets = {}
        for a in r["assets"]:
            digest = a.get("digest")
            if (isinstance(digest, str) and digest.startswith("sha256:") and _SHA256.fullmatch(digest[7:])
                    and isinstance(a["name"], str) and _ASSET.fullmatch(a["name"])):
                assets[a["name"]] = digest[7:]
        return tag, assets
    raise FonteIndisponivel(f"{repo}: nenhuma release final com a tag {prefixo_da_tag!r}")
