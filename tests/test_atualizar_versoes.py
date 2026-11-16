# test_atualizar_versoes.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Decisão da combinação compatível e reescrita dos pontos fixados, com fontes simuladas sobre uma cópia do repo."""

import hashlib
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "build-aux" / "windows"))
import atualizar_versoes as av  # noqa: E402
import fontes_de_versao as fontes  # noqa: E402

ARQUIVOS = [
    ".python-version",
    "README.md",
    "requirements.in",
    "requirements-dev.in",
    "requirements.txt",
    "requirements-dev.txt",
    "build-aux/windows/montar_app_qt.py",
    "tools/baixar_qt_sdk.py",
    "build-aux/windows/instalar_inno.ps1",
]
METAINFO = "data/io.github.joaomgabaldi.Cartridges.metainfo.xml.in"
# A <release> do topo, fixa: a do repositório real muda a cada versão.
METAINFO_BASE = """<releases>
    <release version="9.0.1">
      <description translate="no">
        <ul>
          <li>Novidade do usuário.</li>
        </ul>
      </description>
    </release>
    <release version="9.0.0" date="2026-01-01">
      <description translate="no">
        <ul>
          <li>Antiga.</li>
        </ul>
      </description>
    </release>
  </releases>
"""
URL_TOPO = "https://api.github.com/repos/joaomgabaldi/Cartridges/releases/tags/v9.0.1"
SHA_PY_ATUAL = "352e232f25b5120508f11a6dfc1bd9076d3e70c30977d552a63338838c2ae8fb"
SHA_316 = "16" * 32
SHA_TINYTUYA_NOVO = "ab" * 32
SHA_INNO_ATUAL = "0362a383ed217d4c4239b5933866dd96d3eb2102737da92f80f6057a4b40df2f"
SHA_INNO_711 = "8a5a6711c3766a6e5fb74f280ba0e3551e719ce94538d901fdbd1f8f9920b3f0"


def _pinos(arquivo):
    achados = re.findall(r"^(\S+)==(\S+) --hash=sha256:([0-9a-f]{64})$", (RAIZ / arquivo).read_text(encoding="utf-8"), re.M)
    return {n: fontes.Pino(n, v, h) for n, v, h in achados}


DADOS = RAIZ / "tests" / "dados" / "versoes"
LIBS = _pinos(DADOS / "requirements_base.txt")
DEV = _pinos(DADOS / "requirements-dev_base.txt")
# A situação de partida dos cenários, fixa: o repositório real muda a cada atualização e não pode quebrar a suíte.
BASE = {
    "build-aux/windows/montar_app_qt.py": {
        "PYTHON_SHA256": SHA_PY_ATUAL,
        "FFMPEG_VERSAO": "9.0.2",
        "FFMPEG_SHA256": "60f467265b1e312373dbcd92200c2618a74850f98d3d078e94296bb3fa2047ba",
        "FFMPEG_FONTE": "https://github.com/FFmpeg/FFmpeg/commit/946fcce07b",
        "LUDUSAVI_VERSAO": "0.31.0",
        "LUDUSAVI_SHA256": "f47a8ad8c708f01d2eb124704973beffab205e292f5287a10fc4a101f8d68706",
        "LUDUSAVI_LEGAL_SHA256": "9fce11fc44942efdd5969928d89b106c229f9a041d7a713c424a6da981660ebf",
    },
    "tools/baixar_qt_sdk.py": {
        "QT_VERSAO": "6.12.0",
        "QT_DATA": "202609280346",
        "QTBASE_SHA256": "219d1b86def3be418e31d704572bc4acc91b2ec373c65595c9fb12b42bf098dc",
        "QTDECLARATIVE_SHA256": "258146e9972fadbc1162cda31c7d7ed7e627f5022b2a848f2edb84d9c2ce27db",
        "QWK_TAG": "1.5.0",
        "QWK_COMMIT": "35e88f3655720ed0537c7dd1dde243bf4a70c94c",
        "QMSETUP_COMMIT": "85c6c3c783be8af8d3f2fa492748a82da8ec9bad",
    },
}


def _com(libs, **novas):
    """Cópia de `libs` com versões trocadas: nome=(versão, sha)."""
    saida = dict(libs)
    for nome, (versao, sha) in novas.items():
        saida[nome] = fontes.Pino(nome, versao, sha)
    return saida


PYSIDE_613 = _com(LIBS, **{n: ("6.13.0", "c" * 64) for n in ("PySide6", "PySide6_Addons", "PySide6_Essentials", "shiboken6")})


@dataclass
class Mundo:
    """As fontes oficiais simuladas; `para_kwargs()` dá o `ler`/`rodar` falsos de `atualizar`."""

    pythons: dict = field(default_factory=lambda: {"3.15.1": SHA_PY_ATUAL})  # versão -> sha do embutido (None: sem)
    setup: set = field(default_factory=lambda: {"3.15.1"})
    resolucoes: dict = field(default_factory=lambda: {("3.15", None): LIBS})  # (X.Y, PySide6 fixado) -> libs
    qt: dict = field(default_factory=dict)  # versão -> data
    qwk: tuple = ("1.5.0", "35e88f3655720ed0537c7dd1dde243bf4a70c94c", "85c6c3c783be8af8d3f2fa492748a82da8ec9bad")
    ffmpeg: tuple | None = ("9.0.2", "60f467265b1e312373dbcd92200c2618a74850f98d3d078e94296bb3fa2047ba", "946fcce07b" + "0" * 30)
    ludusavi: tuple = ("v0.31.0", {
        "ludusavi-v0.31.0-win64.zip": "f47a8ad8c708f01d2eb124704973beffab205e292f5287a10fc4a101f8d68706",
        "ludusavi-v0.31.0-legal.zip": "9fce11fc44942efdd5969928d89b106c229f9a041d7a713c424a6da981660ebf",
    })
    inno: tuple = ("is-7_1_0", {"innosetup-7.1.0-x64.exe": SHA_INNO_ATUAL})
    release_topo: object = None  # None: não publicada (404); dict: resposta da API; "fora": fonte fora do ar
    dev: dict = field(default_factory=lambda: DEV)  # as bibliotecas só de teste que o pip devolve

    def respostas(self):
        py = "https://www.python.org/api/v2/downloads/"
        r = {
            py + "release/?version=3&is_published=true": [
                {"name": f"Python {v}", "pre_release": False, "resource_uri": f"{py}release/{i}/"}
                for i, v in enumerate(self.pythons)
            ],
            fontes.URL_MANIFESTO_SETUP_PYTHON: [
                {"version": v, "stable": True, "files": [{"platform": "win32", "arch": "x64"}]} for v in self.setup
            ],
        }
        for i, (v, sha) in enumerate(self.pythons.items()):
            url = f"https://www.python.org/ftp/python/{v}/python-{v}-embed-amd64.zip"
            r[py + f"release_file/?release={i}"] = [{"url": url, "sha256_sum": sha}] if sha else []
        for v, data in self.qt.items():
            n = v.replace(".", "")
            pasta = f"https://download.qt.io/online/qtsdkrepository/windows_x86/desktop/qt6_{n}/qt6_{n}_msvc2022_64/"
            r[pasta + "Updates.xml"] = (
                f"<Updates><PackageUpdate><Name>qt.qt6.{n}.win64_msvc2022_64</Name><Version>{v}-0-{data}</Version>"
                f"<DownloadableArchives>qtbase-W.7z, qtdeclarative-W.7z</DownloadableArchives></PackageUpdate></Updates>"
            ).encode()
            for nome in ("qtbase-W.7z", "qtdeclarative-W.7z"):
                url = f"{pasta}qt.qt6.{n}.win64_msvc2022_64/{v}-0-{data}{nome}"
                r[url] = nome.encode()
                r[url + ".sha1"] = hashlib.sha1(nome.encode()).hexdigest().encode()
        qwk = "https://api.github.com/repos/stdware/qwindowkit/"
        r[qwk + "tags?per_page=100"] = [{"name": self.qwk[0], "commit": {"sha": self.qwk[1]}}]
        r[qwk + f"contents/qmsetup?ref={self.qwk[0]}"] = {"type": "submodule", "sha": self.qwk[2]}
        if self.ffmpeg:
            v, sha, commit = self.ffmpeg
            gyan = "https://www.gyan.dev/ffmpeg/builds/"
            r[gyan + "release-version"] = v.encode()
            r[gyan + f"packages/ffmpeg-{v}-essentials_build.zip.sha256"] = sha.encode()
            r[f"https://api.github.com/repos/FFmpeg/FFmpeg/commits/n{v}"] = {"sha": commit}
        for repo, (tag, assets) in (("mtkennerly/ludusavi", self.ludusavi), ("jrsoftware/issrc", self.inno)):
            r[f"https://api.github.com/repos/{repo}/releases?per_page=30"] = [{
                "tag_name": tag, "prerelease": False, "draft": False,
                "assets": [{"name": a, "digest": f"sha256:{h}"} for a, h in assets.items()],
            }]
        return {u: v if isinstance(v, bytes) else json.dumps(v).encode() for u, v in r.items()}

    def para_kwargs(self):
        respostas = self.respostas()

        def ler(url):
            if url == URL_TOPO and self.release_topo == "fora":
                raise fontes.FonteIndisponivel("fora do ar")
            if url == URL_TOPO and self.release_topo is not None:
                return json.dumps(self.release_topo).encode()
            if url not in respostas:
                raise fontes.NaoEncontrado(url)
            return respostas[url]

        hashes = {(p.nome, p.versao): p.sha256 for libs in self.resolucoes.values() for p in libs.values()}

        def rodar(cmd, **kw):
            xy = cmd[cmd.index("--python-version") + 1]
            fixos = [a for a in cmd if "==" in a]
            if any(a.endswith("requirements-dev.in") for a in cmd):  # devolve o que foi fixado + as de teste
                pinos = [fontes.Pino(*a.split("=="), hashes[tuple(a.split("=="))]) for a in fixos] + list(self.dev.values())
            else:
                chave = (xy, fixos[0].split("==")[1] if fixos else None)
                if chave not in self.resolucoes:
                    return subprocess.CompletedProcess(cmd, 1, "", "ResolutionImpossible")
                pinos = list(self.resolucoes[chave].values())
            relatorio = {"install": [
                {"metadata": {"name": p.nome, "version": p.versao},
                 "download_info": {"archive_info": {"hashes": {"sha256": p.sha256}}}} for p in pinos
            ]}
            return subprocess.CompletedProcess(cmd, 0, json.dumps(relatorio), "")

        return {"ler": ler, "rodar": rodar}


@pytest.fixture
def repo_tmp(tmp_path):
    raiz = tmp_path / "repo"
    for nome in ARQUIVOS:
        (raiz / nome).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(RAIZ / nome, raiz / nome)
    # Estrutura real dos arquivos, valores da BASE.
    (raiz / ".python-version").write_text("3.15.1\n", encoding="utf-8", newline="")
    shutil.copyfile(DADOS / "requirements_base.txt", raiz / "requirements.txt")
    shutil.copyfile(DADOS / "requirements-dev_base.txt", raiz / "requirements-dev.txt")

    def reescrever(nome, mudar):
        p = raiz / nome
        p.write_text(mudar(p.read_text(encoding="utf-8", newline="")), encoding="utf-8", newline="")

    for nome, valores in BASE.items():
        for constante, valor in valores.items():
            reescrever(nome, lambda t: av.trocar_constante(t, constante, valor))
    reescrever("README.md", lambda t: re.sub(r"Python \d+\.\d+ com PySide6 \d+(\.\d+)*", "Python 3.15 com PySide6 6.12.0", t))
    reescrever("build-aux/windows/instalar_inno.ps1", lambda t: re.sub(
        r"(\$InnoVersao = ')[0-9.]+'", r"\g<1>7.1.0'",
        re.sub(r"(\$InnoSha256 = ')[0-9A-Fa-f]{64}'", rf"\g<1>{SHA_INNO_ATUAL.upper()}'", t)))
    (raiz / METAINFO).parent.mkdir(parents=True, exist_ok=True)
    (raiz / METAINFO).write_text(METAINFO_BASE, encoding="utf-8", newline="")
    return raiz


def _estilo(dados: bytes):
    return dados.count(b"\r\n"), dados.count(b"\n")


def _confere_fim_de_linha(raiz, antes):
    """Cada arquivo reescrito mantém o fim de linha do original (CRLF inteiro continua CRLF, LF continua LF)."""
    for caminho, dados in _tudo(raiz).items():
        if antes.get(caminho) not in (None, dados):
            era, agora = _estilo(antes[caminho]), _estilo(dados)
            assert (era[0] == era[1] and era[1] > 0) == (agora[0] == agora[1] and agora[1] > 0), caminho
            assert agora[0] in (0, agora[1]), f"{caminho}: fim de linha misturado"


def _tudo(raiz):
    return {p: p.read_bytes() for p in raiz.rglob("*") if p.is_file()}


TINYTUYA_NOVO = Mundo(resolucoes={("3.15", None): _com(LIBS, tinytuya=("1.21.0", SHA_TINYTUYA_NOVO))})


def test_nada_novo_nao_toca_arquivo(repo_tmp):
    antes = _tudo(repo_tmp)
    r = av.atualizar(repo_tmp, gravar=True, **Mundo().para_kwargs())
    assert r.trocas == [] and r.avisos == []
    assert _tudo(repo_tmp) == antes


def test_lib_nova_sobe_so_ela(repo_tmp):
    antes = _tudo(repo_tmp)
    r = av.atualizar(repo_tmp, gravar=True, **TINYTUYA_NOVO.para_kwargs())
    assert r.trocas == [av.Troca("tinytuya", "1.20.0", "1.21.0")]
    assert f"tinytuya==1.21.0 --hash=sha256:{SHA_TINYTUYA_NOVO}" in (repo_tmp / "requirements.txt").read_text(encoding="utf-8")
    mudados = {p.relative_to(repo_tmp).as_posix() for p, b in _tudo(repo_tmp).items() if antes[p] != b}
    assert mudados == {"requirements.txt", METAINFO}  # o changelog ganha o item
    assert (repo_tmp / "requirements-dev.txt").read_text(encoding="utf-8").startswith("-r requirements.txt\n")


def test_python_sem_roda_do_pyside_fica(repo_tmp):
    mundo = Mundo(pythons={"3.16.0": SHA_316, "3.15.1": SHA_PY_ATUAL}, setup={"3.16.0", "3.15.1"})
    r = av.atualizar(repo_tmp, gravar=True, **mundo.para_kwargs())
    assert "python" not in {t.peca for t in r.trocas}
    assert (repo_tmp / ".python-version").read_text(encoding="utf-8") == "3.15.1\n"


def test_python_fora_do_setup_python_fica(repo_tmp):
    mundo = Mundo(pythons={"3.15.2": "22" * 32, "3.15.1": SHA_PY_ATUAL})
    r = av.atualizar(repo_tmp, gravar=True, **mundo.para_kwargs())
    assert r.trocas == []
    assert (repo_tmp / ".python-version").read_text(encoding="utf-8") == "3.15.1\n"


def test_patch_novo_do_python_sobe(repo_tmp):
    mundo = Mundo(pythons={"3.15.2": "22" * 32, "3.15.1": SHA_PY_ATUAL}, setup={"3.15.2", "3.15.1"})
    r = av.atualizar(repo_tmp, gravar=True, **mundo.para_kwargs())
    assert r.trocas == [av.Troca("python", "3.15.1", "3.15.2")]
    assert (repo_tmp / ".python-version").read_text(encoding="utf-8") == "3.15.2\n"
    assert f'PYTHON_SHA256 = "{"22" * 32}"' in (repo_tmp / "build-aux/windows/montar_app_qt.py").read_text(encoding="utf-8")


def test_python_novo_sem_hash_publicado_fica(repo_tmp):
    mundo = Mundo(pythons={"3.15.2": None, "3.15.1": SHA_PY_ATUAL}, setup={"3.15.2", "3.15.1"})
    r = av.atualizar(repo_tmp, gravar=True, **mundo.para_kwargs())
    assert r.trocas == [] and any("3.15.2" in a for a in r.avisos)


def test_python_menor_novo_sobe_tudo_junto(repo_tmp):
    antes = _tudo(repo_tmp)
    mundo = Mundo(
        pythons={"3.16.0": SHA_316, "3.15.1": SHA_PY_ATUAL}, setup={"3.16.0", "3.15.1"},
        resolucoes={("3.16", None): PYSIDE_613, ("3.15", None): LIBS}, qt={"6.13.0": "202612010000"},
    )
    r = av.atualizar(repo_tmp, gravar=True, **mundo.para_kwargs())
    assert {"python", "pyside6", "qt-sdk"} <= {t.peca for t in r.trocas}
    assert 'PYTHON_SHA256 = "' + SHA_316 + '"' in (repo_tmp / "build-aux/windows/montar_app_qt.py").read_text(encoding="utf-8")
    assert (repo_tmp / ".python-version").read_text(encoding="utf-8") == "3.16.0\n"
    qt = (repo_tmp / "tools/baixar_qt_sdk.py").read_bytes().decode("utf-8")
    assert 'QT_VERSAO = "6.13.0"' in qt and 'QT_DATA = "202612010000"' in qt
    assert f'QTBASE_SHA256 = "{hashlib.sha256(b"qtbase-W.7z").hexdigest()}"' in qt
    _confere_fim_de_linha(repo_tmp, antes)  # CRLF no PC (core.autocrlf), LF na CI: vale o do original
    _confere_fim_de_linha(repo_tmp, antes)
    assert "Python 3.16 com PySide6 6.13.0" in (repo_tmp / "README.md").read_text(encoding="utf-8")
    assert "PySide6==6.13.0" in (repo_tmp / "requirements.txt").read_text(encoding="utf-8")


def test_pyside_sem_sdk_do_qt_fica_junto(repo_tmp):
    mundo = Mundo(resolucoes={("3.15", None): PYSIDE_613, ("3.15", "6.12.0"): _com(LIBS, tinytuya=("1.21.0", SHA_TINYTUYA_NOVO))})
    r = av.atualizar(repo_tmp, gravar=True, **mundo.para_kwargs())
    assert not {"pyside6", "qt-sdk"} & {t.peca for t in r.trocas}
    assert any("Qt" in a for a in r.avisos)
    assert r.trocas == [av.Troca("tinytuya", "1.20.0", "1.21.0")]
    assert 'QT_VERSAO = "6.12.0"' in (repo_tmp / "tools/baixar_qt_sdk.py").read_text(encoding="utf-8")


def test_fonte_fora_do_ar_nao_derruba_o_resto(repo_tmp):
    r = av.atualizar(repo_tmp, gravar=True, **replace(TINYTUYA_NOVO, ffmpeg=None).para_kwargs())
    assert [t.peca for t in r.trocas] == ["tinytuya"] and any("ffmpeg" in a for a in r.avisos)


def test_versao_menor_que_a_atual_nunca_entra(repo_tmp):
    mundo = Mundo(ludusavi=("v0.30.0", {"ludusavi-v0.30.0-win64.zip": "1" * 64, "ludusavi-v0.30.0-legal.zip": "2" * 64}),
                  resolucoes={("3.15", None): _com(LIBS, tinytuya=("1.19.0", SHA_TINYTUYA_NOVO))})
    antes = _tudo(repo_tmp)
    r = av.atualizar(repo_tmp, gravar=True, **mundo.para_kwargs())
    assert r.trocas == [] and _tudo(repo_tmp) == antes


def test_ludusavi_novo_com_hash_sobe(repo_tmp):
    mundo = Mundo(ludusavi=("v0.32.0", {"ludusavi-v0.32.0-win64.zip": "1" * 64, "ludusavi-v0.32.0-legal.zip": "2" * 64}))
    r = av.atualizar(repo_tmp, gravar=True, **mundo.para_kwargs())
    assert r.trocas == [av.Troca("ludusavi", "0.31.0", "0.32.0")]
    texto = (repo_tmp / "build-aux/windows/montar_app_qt.py").read_text(encoding="utf-8")
    assert 'LUDUSAVI_VERSAO = "0.32.0"' in texto and f'LUDUSAVI_LEGAL_SHA256 = "{"2" * 64}"' in texto


def test_ludusavi_sem_hash_de_um_asset_fica(repo_tmp):
    mundo = Mundo(ludusavi=("v0.32.0", {"ludusavi-v0.32.0-win64.zip": "1" * 64}))
    r = av.atualizar(repo_tmp, gravar=True, **mundo.para_kwargs())
    assert r.trocas == [] and any("Ludusavi" in a for a in r.avisos)


def test_ffmpeg_novo_traz_fonte_junto(repo_tmp):
    mundo = Mundo(ffmpeg=("9.1", "3" * 64, "abcdef1234" + "0" * 30))
    r = av.atualizar(repo_tmp, gravar=True, **mundo.para_kwargs())
    assert r.trocas == [av.Troca("ffmpeg", "9.0.2", "9.1")]
    texto = (repo_tmp / "build-aux/windows/montar_app_qt.py").read_text(encoding="utf-8")
    assert 'FFMPEG_VERSAO = "9.1"' in texto and 'FFMPEG_FONTE = "https://github.com/FFmpeg/FFmpeg/commit/abcdef1234"' in texto


def test_qwindowkit_novo_sobe(repo_tmp):
    mundo = Mundo(qwk=("1.6", "d" * 40, "e" * 40))
    r = av.atualizar(repo_tmp, gravar=True, **mundo.para_kwargs())
    assert r.trocas == [av.Troca("qwindowkit", "1.5.0", "1.6")]
    texto = (repo_tmp / "tools/baixar_qt_sdk.py").read_text(encoding="utf-8")
    assert 'QWK_TAG = "1.6"' in texto and f'QMSETUP_COMMIT = "{"e" * 40}"' in texto


def test_constante_ausente_ou_repetida_aborta_sem_gravar(repo_tmp):
    alvo = repo_tmp / "build-aux/windows/montar_app_qt.py"
    alvo.write_text(alvo.read_text(encoding="utf-8").replace("FFMPEG_SHA256 = ", "FFMPEG_HASH = "), encoding="utf-8")
    antes = (repo_tmp / "requirements.txt").read_bytes()
    with pytest.raises(av.PontoAusente):
        av.atualizar(repo_tmp, gravar=True, **TINYTUYA_NOVO.para_kwargs())
    assert (repo_tmp / "requirements.txt").read_bytes() == antes


def test_trocar_constante_exige_uma_ocorrencia():
    assert av.trocar_constante('A = "1"\r\nB = "2"\r\n', "A", "9") == 'A = "9"\r\nB = "2"\r\n'
    assert av.trocar_constante('A = "1"  # nota\n', "A", "9") == 'A = "9"  # nota\n'
    for texto in ('B = "1"\n', 'A = "1"\nA = "2"\n', 'XA = "1"\n'):
        with pytest.raises(av.PontoAusente):
            av.trocar_constante(texto, "A", "9")


def test_bom_e_preservado(repo_tmp):
    alvo = repo_tmp / "build-aux/windows/montar_app_qt.py"
    alvo.write_bytes(b"\xef\xbb\xbf" + alvo.read_bytes())
    av.atualizar(repo_tmp, gravar=True, **Mundo(ffmpeg=("9.1", "3" * 64, "a" * 40)).para_kwargs())
    assert alvo.read_bytes().startswith(b"\xef\xbb\xbf") and b'FFMPEG_VERSAO = "9.1"' in alvo.read_bytes()


def test_inno_novo_reescreve_versao_e_hash(repo_tmp):
    antes = _tudo(repo_tmp)
    mundo = Mundo(inno=("is-7_1_1", {"innosetup-7.1.1-x64.exe": SHA_INNO_711}))
    r = av.atualizar(repo_tmp, gravar=True, **mundo.para_kwargs())
    assert r.trocas == [av.Troca("inno-setup", "7.1.0", "7.1.1")]
    texto = (repo_tmp / "build-aux/windows/instalar_inno.ps1").read_bytes().decode("utf-8")
    assert "$InnoVersao = '7.1.1'" in texto and f"$InnoSha256 = '{SHA_INNO_711.upper()}'" in texto
    assert "7.1.0" not in texto and SHA_INNO_ATUAL.upper() not in texto
    _confere_fim_de_linha(repo_tmp, antes)
    # Nenhum workflow é tocado: o GITHUB_TOKEN não pode dar push de arquivo em .github/workflows.
    assert not any(".github" in p.parts for p, b in _tudo(repo_tmp).items() if antes.get(p) != b)


def test_verificar_nao_grava_e_sai_1(repo_tmp, capsys):
    antes = _tudo(repo_tmp)
    assert av.main(["--verificar"], raiz=repo_tmp, **TINYTUYA_NOVO.para_kwargs()) == 1
    assert _tudo(repo_tmp) == antes
    assert "tinytuya: 1.20.0 → 1.21.0" in capsys.readouterr().out


def test_verificar_sem_novidade_sai_0(repo_tmp):
    assert av.main(["--verificar"], raiz=repo_tmp, **Mundo().para_kwargs()) == 0


def test_ponto_ausente_sai_2(repo_tmp, capsys):
    alvo = repo_tmp / "tools/baixar_qt_sdk.py"
    alvo.write_text(alvo.read_text(encoding="utf-8").replace("QT_DATA = ", "QT_DATA2 = "), encoding="utf-8")
    assert av.main([], raiz=repo_tmp, **Mundo().para_kwargs()) == 2
    assert "QT_DATA" in capsys.readouterr().err


def test_json_tem_linha_do_commit(repo_tmp, tmp_path, capsys):
    saida = tmp_path / "versoes.json"
    mundo = replace(TINYTUYA_NOVO, ffmpeg=None)
    assert av.main(["--json", str(saida)], raiz=repo_tmp, **mundo.para_kwargs()) == 0
    dados = json.loads(saida.read_text(encoding="utf-8"))
    assert dados["trocas"] == [{"peca": "tinytuya", "de": "1.20.0", "para": "1.21.0"}]
    assert dados["linha"] == "Versões atualizadas: tinytuya 1.20.0 → 1.21.0"
    assert any("ffmpeg" in a for a in dados["avisos"])
    assert "Aviso: " in capsys.readouterr().out


def test_linha_do_commit():
    r = av.Resultado([av.Troca("tinytuya", "1.20.0", "1.21.0"), av.Troca("ffmpeg", "9.0.2", "9.0.3")], [])
    assert av.linha_do_commit(r) == "Versões atualizadas: tinytuya 1.20.0 → 1.21.0, ffmpeg 9.0.2 → 9.0.3"


# --- rodada de correção 1 ---


def test_python_novo_com_mesmas_versoes_regrava_os_hashes(repo_tmp):
    outros = {n: fontes.Pino(p.nome, p.versao, "9" * 64) for n, p in LIBS.items()}
    mundo = Mundo(pythons={"3.16.0": SHA_316, "3.15.1": SHA_PY_ATUAL}, setup={"3.16.0", "3.15.1"},
                  resolucoes={("3.16", None): outros, ("3.15", None): LIBS})
    r = av.atualizar(repo_tmp, gravar=True, **mundo.para_kwargs())
    assert r.trocas == [av.Troca("python", "3.15.1", "3.16.0")]
    texto = (repo_tmp / "requirements.txt").read_text(encoding="utf-8")
    assert f"tinytuya==1.20.0 --hash=sha256:{'9' * 64}" in texto and SHA_TINYTUYA_NOVO not in texto


def test_mesmo_python_com_hash_novo_regrava_e_avisa(repo_tmp):
    mundo = Mundo(resolucoes={("3.15", None): _com(LIBS, tinytuya=("1.20.0", "9" * 64))})
    r = av.atualizar(repo_tmp, gravar=True, **mundo.para_kwargs())
    assert f"tinytuya==1.20.0 --hash=sha256:{'9' * 64}" in (repo_tmp / "requirements.txt").read_text(encoding="utf-8")
    assert any("hash" in a.lower() for a in r.avisos)


def test_versao_de_lib_com_post_nao_quebra(repo_tmp):
    mundo = Mundo(resolucoes={("3.15", None): _com(LIBS, tinytuya=("1.20.0.post1", SHA_TINYTUYA_NOVO))})
    r = av.atualizar(repo_tmp, gravar=False, **mundo.para_kwargs())
    assert r.trocas == [av.Troca("tinytuya", "1.20.0", "1.20.0.post1")]


def test_erro_inesperado_sai_2_nunca_1(repo_tmp, capsys):
    def ler(url):
        raise RuntimeError("inesperado")

    assert av.main(["--verificar"], raiz=repo_tmp, ler=ler, rodar=Mundo().para_kwargs()["rodar"]) == 2
    assert "inesperado" in capsys.readouterr().err


# --- changelog (Task 8) ---


def _metainfo(raiz):
    return (raiz / METAINFO).read_text(encoding="utf-8")


def _itens_do_topo(raiz):
    return re.findall(r"<li>(.*?)</li>", _metainfo(raiz).split("</release>")[0])


MUNDO_PATCH = Mundo(pythons={"3.15.2": "22" * 32, "3.15.1": SHA_PY_ATUAL}, setup={"3.15.2", "3.15.1"},
                    resolucoes={("3.15", None): _com(LIBS, tinytuya=("1.21.0", SHA_TINYTUYA_NOVO))})


def test_changelog_um_item_por_peca_no_fim_da_lista_do_topo(repo_tmp):
    av.atualizar(repo_tmp, gravar=True, **MUNDO_PATCH.para_kwargs())
    assert _itens_do_topo(repo_tmp) == ["Novidade do usuário.", "Python atualizado para 3.15.2.", "tinytuya atualizada para 1.21.0."]
    assert "<li>Antiga.</li>" in _metainfo(repo_tmp) and _metainfo(repo_tmp).count("atualizad") == 2


def test_changelog_mesma_peca_troca_a_versao_sem_duplicar(repo_tmp):
    av.atualizar(repo_tmp, gravar=True, **TINYTUYA_NOVO.para_kwargs())
    mundo = Mundo(resolucoes={("3.15", None): _com(LIBS, tinytuya=("1.22.0", "cd" * 32))})
    # o requirements já está em 1.21.0 depois da primeira passada; a segunda sobe para 1.22.0
    r = av.atualizar(repo_tmp, gravar=True, **mundo.para_kwargs())
    assert r.trocas == [av.Troca("tinytuya", "1.21.0", "1.22.0")]
    assert _itens_do_topo(repo_tmp) == ["Novidade do usuário.", "tinytuya atualizada para 1.22.0."]


def test_changelog_troca_so_de_hash_nao_gera_item(repo_tmp):
    mundo = Mundo(resolucoes={("3.15", None): _com(LIBS, tinytuya=("1.20.0", "9" * 64))})
    av.atualizar(repo_tmp, gravar=True, **mundo.para_kwargs())
    assert _metainfo(repo_tmp) == METAINFO_BASE


def test_changelog_nada_novo_deixa_o_metainfo_intocado(repo_tmp):
    av.atualizar(repo_tmp, gravar=True, **Mundo().para_kwargs())
    assert _metainfo(repo_tmp) == METAINFO_BASE


def test_changelog_release_publicada_nao_escreve_e_avisa(repo_tmp):
    r = av.atualizar(repo_tmp, gravar=True, **replace(TINYTUYA_NOVO, release_topo={"prerelease": False}).para_kwargs())
    assert r.trocas and _metainfo(repo_tmp) == METAINFO_BASE
    assert ("A versão 9.0.1 já foi publicada: suba a VERSION em kyron/shared.py e abra uma <release> nova "
            "para registrar as atualizações.") in r.avisos
    assert "tinytuya==1.21.0" in (repo_tmp / "requirements.txt").read_text(encoding="utf-8")


def test_changelog_pre_release_ainda_aceita_itens(repo_tmp):
    av.atualizar(repo_tmp, gravar=True, **replace(TINYTUYA_NOVO, release_topo={"prerelease": True}).para_kwargs())
    assert "tinytuya atualizada para 1.21.0." in _itens_do_topo(repo_tmp)


def test_changelog_fonte_fora_nao_escreve_e_avisa(repo_tmp):
    r = av.atualizar(repo_tmp, gravar=True, **replace(TINYTUYA_NOVO, release_topo="fora").para_kwargs())
    assert _metainfo(repo_tmp) == METAINFO_BASE
    assert any("Não foi possível conferir" in a and "9.0.1" in a for a in r.avisos)


def test_changelog_nome_e_escapado_para_xml():
    t = av.Troca("lib<&>", "1", "2")
    assert "<li>lib&lt;&amp;&gt; atualizada para 2.</li>" in av.escrever_changelog(METAINFO_BASE, [t])


def test_changelog_componentes_no_masculino():
    trocas = [av.Troca(p, "1", "2") for p in ("pyside6", "qt-sdk", "qwindowkit", "ffmpeg", "ludusavi", "inno-setup", "pyside6-addons")]
    texto = av.escrever_changelog(METAINFO_BASE, trocas)
    for nome in ("PySide6", "Qt", "QWindowKit", "FFmpeg", "Ludusavi", "Inno Setup"):
        assert f"<li>{nome} atualizado para 2.</li>" in texto
    assert "addons" not in texto


def test_changelog_preserva_crlf():
    base = METAINFO_BASE.replace("\n", "\r\n")
    texto = av.escrever_changelog(base, [av.Troca("python", "1", "2")])
    assert texto.count("\r\n") == texto.count("\n") and "<li>Python atualizado para 2.</li>\r\n" in texto


# --- revisão final ---


def test_pyside6_de_quatro_partes_nao_mexe_no_sdk(repo_tmp):
    mundo = Mundo(resolucoes={("3.15", None): _com(LIBS, PySide6=("6.12.0.1", "c" * 64))})
    r = av.atualizar(repo_tmp, gravar=True, **mundo.para_kwargs())
    assert r.trocas == [av.Troca("pyside6", "6.12.0", "6.12.0.1")] and r.avisos == []
    assert "PySide6==6.12.0.1" in (repo_tmp / "requirements.txt").read_text(encoding="utf-8")
    assert 'QT_VERSAO = "6.12.0"' in (repo_tmp / "tools/baixar_qt_sdk.py").read_text(encoding="utf-8")


def test_pyside6_de_quatro_partes_com_qt_novo_sobe_o_sdk(repo_tmp):
    mundo = Mundo(resolucoes={("3.15", None): _com(PYSIDE_613, PySide6=("6.13.0.1", "c" * 64))},
                  qt={"6.13.0": "202612010000"})
    r = av.atualizar(repo_tmp, gravar=True, **mundo.para_kwargs())
    assert av.Troca("qt-sdk", "6.12.0", "6.13.0") in r.trocas and av.Troca("pyside6", "6.12.0", "6.13.0.1") in r.trocas
    assert 'QT_VERSAO = "6.13.0"' in (repo_tmp / "tools/baixar_qt_sdk.py").read_text(encoding="utf-8")
    assert "Python 3.15 com PySide6 6.13.0 (" in (repo_tmp / "README.md").read_text(encoding="utf-8")


def test_readme_nao_engole_o_ponto_final():
    assert av._README.search("Python 3.15 com PySide6 6.12.0. Depois").group() == "Python 3.15 com PySide6 6.12.0"


def test_changelog_ignora_bibliotecas_so_de_teste(repo_tmp):
    mundo = replace(Mundo(dev=_com(DEV, pytest=("9.3.0", "ee" * 32))), release_topo="fora")
    r = av.atualizar(repo_tmp, gravar=True, **mundo.para_kwargs())
    assert r.trocas == [av.Troca("pytest", "9.2.0", "9.3.0")]
    assert "pytest==9.3.0" in (repo_tmp / "requirements-dev.txt").read_text(encoding="utf-8")
    assert _metainfo(repo_tmp) == METAINFO_BASE and r.avisos == []  # nem consulta a release


def test_changelog_usa_o_nome_como_o_pip_escreve(repo_tmp):
    libs = dict(LIBS)
    libs["pillow"] = fontes.Pino("Pillow", "13.1.0", "ef" * 32)
    av.atualizar(repo_tmp, gravar=True, **Mundo(resolucoes={("3.15", None): libs}).para_kwargs())
    assert "Pillow atualizada para 13.1.0." in _itens_do_topo(repo_tmp)


def test_changelog_qt_e_qwindowkit_nao_se_confundem():
    texto = av.escrever_changelog(METAINFO_BASE, [av.Troca("qwindowkit", "1.5.0", "1.6")])
    texto = av.escrever_changelog(texto, [av.Troca("qt-sdk", "6.12.0", "6.13.0")])
    texto = av.escrever_changelog(texto, [av.Troca("qwindowkit", "1.6", "1.7"), av.Troca("qt-sdk", "6.13.0", "6.14.0")])
    topo = texto.split("</release>")[0]
    assert re.findall(r"<li>(.*?)</li>", topo) == [
        "Novidade do usuário.", "QWindowKit atualizado para 1.7.", "Qt atualizado para 6.14.0."]


def test_changelog_release_nova_sem_lista_ganha_a_lista():
    import xml.etree.ElementTree as ET

    base = METAINFO_BASE.replace(
        """    <release version="9.0.1">
      <description translate="no">
        <ul>
          <li>Novidade do usuário.</li>
        </ul>
      </description>
    </release>""", """    <release version="9.0.2">
    </release>""")
    texto = av.escrever_changelog(base, [av.Troca("python", "1", "2"), av.Troca("tinytuya", "1", "2")])
    assert texto.startswith("""<releases>
    <release version="9.0.2">
      <description translate="no">
        <ul>
          <li>Python atualizado para 2.</li>
          <li>tinytuya atualizada para 2.</li>
        </ul>
      </description>
    </release>
""")
    ET.fromstring(texto)
    # Numa linha só, também vira XML válido.
    ET.fromstring(av.escrever_changelog(base.replace('9.0.2">\n    </release>', '9.0.2"></release>'),
                                        [av.Troca("python", "1", "2")]))
