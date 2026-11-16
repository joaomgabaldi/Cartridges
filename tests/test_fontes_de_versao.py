# test_fontes_de_versao.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Resolução das bibliotecas (relatório do pip) e leitores das fontes oficiais, com respostas gravadas."""

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "build-aux" / "windows"))
import fontes_de_versao as fontes  # noqa: E402

DADOS = Path(__file__).resolve().parent / "dados" / "versoes"
SHA_TINYTUYA = "ac5650c30f1153b1eae0b8d75f67043fb2397a168d3834e47da2d88d2c08c722"


def test_resolver_libs_le_relatorio_do_pip(tmp_path):
    relatorio = (DADOS / "pip_report.json").read_text(encoding="utf-8")
    chamadas = []

    def rodar(cmd, **kw):
        chamadas.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout=relatorio, stderr="")

    pinos = fontes.resolver_libs([tmp_path / "requirements.in"], "3.15", ["PySide6==6.12.0"], rodar)
    assert fontes.Pino("tinytuya", "1.20.0", SHA_TINYTUYA) in pinos
    cmd = chamadas[0]
    for trecho in ("--dry-run", "--only-binary=:all:", "--platform", "win_amd64",
                   "--python-version", "3.15", "--ignore-installed", "PySide6==6.12.0"):
        assert trecho in cmd


def test_resolver_libs_devolve_none_quando_pip_falha(tmp_path):
    rodar = lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, stdout="", stderr="ResolutionImpossible")
    assert fontes.resolver_libs([tmp_path / "r.in"], "3.16", [], rodar) is None


def test_resolver_libs_devolve_none_com_relatorio_ilegivel(tmp_path):
    rodar = lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, stdout="não é json", stderr="")
    assert fontes.resolver_libs([tmp_path / "r.in"], "3.15", [], rodar) is None


def test_gravar_requirements_ordena_e_poe_hash(tmp_path):
    destino = tmp_path / "r.txt"
    fontes.gravar_requirements(destino, [fontes.Pino("b", "2", "bb"), fontes.Pino("A", "1", "aa")], ["-r x.txt"])
    assert destino.read_text(encoding="utf-8") == "-r x.txt\nA==1 --hash=sha256:aa\nb==2 --hash=sha256:bb\n"


# --- leitores das fontes oficiais: respostas reais cortadas em tests/dados/versoes ---

PY = "https://www.python.org/api/v2/downloads/"
QT = "https://download.qt.io/online/qtsdkrepository/windows_x86/desktop/qt6_6120/qt6_6120_msvc2022_64/"
QT_PACOTE = QT + "qt.qt6.6120.win64_msvc2022_64/6.12.0-0-202609280346"
QT_BASE = "qtbase-Windows-Windows_11_24H2-MSVC2022-Windows-Windows_11_24H2-X86_64.7z"
QT_DECL = "qtdeclarative-Windows-Windows_11_24H2-MSVC2022-Windows-Windows_11_24H2-X86_64.7z"
QWK = "https://api.github.com/repos/stdware/qwindowkit/"
GYAN = "https://www.gyan.dev/ffmpeg/builds/"
SHA_FFMPEG = "60f467265b1e312373dbcd92200c2618a74850f98d3d078e94296bb3fa2047ba"


def _d(nome):
    return (DADOS / nome).read_bytes()


def _ler_de(mapa):
    def ler(url):
        if url not in mapa:
            raise fontes.NaoEncontrado(url)
        return mapa[url]

    return ler


def _ler_que_falha(url):
    raise fontes.FonteIndisponivel("sem rede")


def _ler_python():
    return _ler_de({
        PY + "release/?version=3&is_published=true": _d("python_releases.json"),
        PY + "release_file/?release=1165": _d("python_release_files.json"),
    })


def test_python_ignora_pre_release():
    versoes = fontes.versoes_do_python(_ler_python())
    assert versoes[:3] == ["3.15.2", "3.15.1", "3.15.0"]
    assert all(re.fullmatch(r"3\.\d+\.\d+", v) for v in versoes)


def test_python_embutido_traz_o_sha256_do_python_org():
    arq = fontes.python_embutido("3.15.1", _ler_python())
    assert arq == fontes.Arquivo(
        "3.15.1",
        "https://www.python.org/ftp/python/3.15.1/python-3.15.1-embed-amd64.zip",
        "352e232f25b5120508f11a6dfc1bd9076d3e70c30977d552a63338838c2ae8fb",
    )


def test_python_embutido_de_versao_inexistente_e_semhash():
    with pytest.raises(fontes.SemHash):
        fontes.python_embutido("3.15.9", _ler_python())


def test_python_embutido_recusa_versao_malformada():
    with pytest.raises(ValueError):
        fontes.python_embutido("3.15.1/../x", _ler_python())


def test_setup_python_so_conta_finais_win32_x64():
    ler = _ler_de({fontes.URL_MANIFESTO_SETUP_PYTHON: _d("python_versions_manifest.json")})
    assert fontes.versoes_do_setup_python(ler) == {"3.15.2", "3.15.1"}


def _ler_qt(base=b"fake-base", decl=b"fake-decl"):
    sha1 = lambda b: hashlib.sha1(b).hexdigest().encode()
    return _ler_de({
        QT + "Updates.xml": _d("qt_updates.xml"),
        f"{QT_PACOTE}{QT_BASE}": base,
        f"{QT_PACOTE}{QT_BASE}.sha1": sha1(b"fake-base"),
        f"{QT_PACOTE}{QT_DECL}": decl,
        f"{QT_PACOTE}{QT_DECL}.sha1": sha1(b"fake-decl"),
    })


def test_qt_sdk_devolve_data_e_sha256_dos_arquivos_conferidos():
    data, base, decl = fontes.qt_sdk("6.12.0", _ler_qt())
    assert data == "202609280346"
    assert base == hashlib.sha256(b"fake-base").hexdigest()
    assert decl == hashlib.sha256(b"fake-decl").hexdigest()


def test_qt_sdk_ausente_devolve_none():
    assert fontes.qt_sdk("6.99.0", _ler_de({})) is None


def test_qt_sdk_pacote_ausente_no_updates_devolve_none():
    xml = b"<Updates><PackageUpdate><Name>qt.qt6.6120.addons</Name></PackageUpdate></Updates>"
    assert fontes.qt_sdk("6.12.0", _ler_de({QT + "Updates.xml": xml})) is None


def test_qt_sdk_sha1_errado_e_recusado():
    with pytest.raises(fontes.SemHash):
        fontes.qt_sdk("6.12.0", _ler_qt(base=b"adulterado"))


def test_qt_sdk_sem_sha1_publicado_e_recusado():
    ler = _ler_qt()

    def sem_sha1(url):
        if url.endswith(".sha1"):
            raise fontes.NaoEncontrado(url)
        return ler(url)

    with pytest.raises(fontes.SemHash):
        fontes.qt_sdk("6.12.0", sem_sha1)


def test_qwindowkit_devolve_tag_commit_e_qmsetup():
    ler = _ler_de({
        QWK + "tags?per_page=100": _d("github_qwindowkit_tags.json"),
        QWK + "contents/qmsetup?ref=1.5.0": _d("github_qwindowkit_qmsetup.json"),
    })
    assert fontes.qwindowkit(ler) == (
        "1.5.0", "35e88f3655720ed0537c7dd1dde243bf4a70c94c", "85c6c3c783be8af8d3f2fa492748a82da8ec9bad"
    )


def _ler_ffmpeg():
    return _ler_de({
        GYAN + "release-version": _d("gyan_release_version.txt"),
        GYAN + "packages/ffmpeg-9.0.2-essentials_build.zip.sha256": _d("gyan_essentials.zip.sha256"),
        "https://api.github.com/repos/FFmpeg/FFmpeg/commits/n9.0.2": _d("github_ffmpeg_commit.json"),
    })


def test_ffmpeg_traz_zip_e_sha256_do_gyan():
    arq, _ = fontes.ffmpeg(_ler_ffmpeg())
    assert arq == fontes.Arquivo("9.0.2", GYAN + "packages/ffmpeg-9.0.2-essentials_build.zip", SHA_FFMPEG)


def test_ffmpeg_fonte_e_a_de_hoje():
    _, fonte = fontes.ffmpeg(_ler_ffmpeg())
    assert fonte == "https://github.com/FFmpeg/FFmpeg/commit/946fcce07b"  # confirma a regra com o valor atual


def test_ffmpeg_sem_sha256_publicado_e_semhash():
    mapa = {GYAN + "release-version": b"9.0.2", GYAN + "packages/ffmpeg-9.0.2-essentials_build.zip.sha256": b"<html>"}
    with pytest.raises(fontes.SemHash):
        fontes.ffmpeg(_ler_de(mapa))


def _ler_github(repo, arquivo, mudar=None):
    dados = json.loads(_d(arquivo))
    if mudar:
        mudar(dados)
    return _ler_de({f"https://api.github.com/repos/{repo}/releases?per_page=30": json.dumps(dados).encode()})


def test_release_do_github_traz_sha256_do_digest():
    tag, assets = fontes.release_do_github("mtkennerly/ludusavi", _ler_github("mtkennerly/ludusavi", "github_ludusavi.json"))
    assert tag == "v0.31.0"
    assert assets["ludusavi-v0.31.0-win64.zip"] == "f47a8ad8c708f01d2eb124704973beffab205e292f5287a10fc4a101f8d68706"
    assert assets["ludusavi-v0.31.0-legal.zip"] == "9fce11fc44942efdd5969928d89b106c229f9a041d7a713c424a6da981660ebf"


def test_asset_sem_digest_e_recusado():
    def tirar(d):
        for a in d[0]["assets"]:
            a["digest"] = None

    ler = _ler_github("mtkennerly/ludusavi", "github_ludusavi.json", tirar)
    _, assets = fontes.release_do_github("mtkennerly/ludusavi", ler)
    assert assets == {}


def test_release_do_github_ignora_prerelease_e_rascunho():
    def marcar(d):
        d[0]["prerelease"] = True
        d[1]["draft"] = True

    ler = _ler_github("mtkennerly/ludusavi", "github_ludusavi.json", marcar)
    tag, _ = fontes.release_do_github("mtkennerly/ludusavi", ler)
    assert tag == "v0.29.1"


def test_release_do_github_filtra_pelo_prefixo_da_tag():
    ler = _ler_github("jrsoftware/issrc", "github_issrc.json")
    tag, assets = fontes.release_do_github("jrsoftware/issrc", ler, "is-7_")
    assert tag == "is-7_1_1"
    assert "innosetup-7.1.1-x64.exe" in assets


def test_release_do_github_sem_release_valida_e_indisponivel():
    ler = _ler_github("jrsoftware/issrc", "github_issrc.json", lambda d: d.clear())
    with pytest.raises(fontes.FonteIndisponivel):
        fontes.release_do_github("jrsoftware/issrc", ler, "is-7_")


def test_erro_de_rede_vira_fonte_indisponivel():
    with pytest.raises(fontes.FonteIndisponivel):
        fontes.versoes_do_python(_ler_que_falha)


def test_resposta_com_formato_inesperado_vira_fonte_indisponivel():
    ler = _ler_de({PY + "release/?version=3&is_published=true": b'{"nao": "lista"}'})
    with pytest.raises(fontes.FonteIndisponivel):
        fontes.versoes_do_python(ler)


@pytest.mark.rede
def test_fontes_de_verdade_respondem():
    """Chama as fontes oficiais (fora da suíte padrão: `pytest -m rede`)."""
    ler = fontes.ler_da_rede
    assert fontes.versoes_do_python(ler)[0].startswith("3.")
    assert fontes.python_embutido("3.15.1", ler).sha256.startswith("352e232f")
    assert "3.15.1" in fontes.versoes_do_setup_python(ler)
    assert fontes.qt_sdk("6.99.0", ler) is None
    assert fontes.qwindowkit(ler)[0]
    assert fontes.ffmpeg(ler)[0].sha256
    assert fontes.release_do_github("mtkennerly/ludusavi", ler)[0].startswith("v")


# --- robustez dos leitores (Ruling R8) e token do GitHub (Ruling R7) ---


def test_qt_sdk_sem_qtbase_no_pacote_e_indisponivel():
    xml = (b"<Updates><PackageUpdate><Name>qt.qt6.6120.win64_msvc2022_64</Name>"
           b"<Version>6.12.0-0-202609280346</Version><DownloadableArchives>qtsvg-x.7z</DownloadableArchives>"
           b"</PackageUpdate></Updates>")
    with pytest.raises(fontes.FonteIndisponivel):
        fontes.qt_sdk("6.12.0", _ler_de({QT + "Updates.xml": xml}))


def _ler_qwk(tags):
    return _ler_de({
        QWK + "tags?per_page=100": json.dumps([{"name": t, "commit": {"sha": "a" * 40}} for t in tags]).encode(),
        **{QWK + f"contents/qmsetup?ref={t}": json.dumps({"type": "submodule", "sha": "b" * 40}).encode() for t in tags},
    })


def test_qwindowkit_aceita_tag_de_dois_componentes():
    assert fontes.qwindowkit(_ler_qwk(["1.5.0", "1.6", "1.5.9"]))[0] == "1.6"
    assert fontes.qwindowkit(_ler_qwk(["1.5", "1.5.1"]))[0] == "1.5.1"


def test_qwindowkit_sem_tag_valida_e_indisponivel():
    with pytest.raises(fontes.FonteIndisponivel):
        fontes.qwindowkit(_ler_qwk(["latest", "v-teste"]))


def test_release_do_github_descarta_asset_de_nome_estranho():
    def nomes(d):
        d[0]["assets"][0]["name"] = "../../x?y=1"

    ler = _ler_github("mtkennerly/ludusavi", "github_ludusavi.json", nomes)
    _, assets = fontes.release_do_github("mtkennerly/ludusavi", ler)
    assert all(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]*", a) for a in assets)
    assert "ludusavi-v0.31.0-win64.zip" in assets and "../../x?y=1" not in assets


class _Resposta:
    def __init__(self, url):
        self.url = url

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def geturl(self):
        return self.url

    def read(self):
        return b"[]"


@pytest.mark.parametrize("url, com_token", [
    ("https://api.github.com/repos/stdware/qwindowkit/tags", True),
    ("https://www.python.org/api/v2/downloads/", False),
    ("https://github.com/jrsoftware/issrc/releases/download/x.exe", False),
    ("https://api.github.com.exemplo.com/repos/x", False),
])
def test_token_do_github_so_vai_para_a_api(monkeypatch, url, com_token):
    pedidos = []
    monkeypatch.setenv("GITHUB_TOKEN", "segredo")
    monkeypatch.setattr(fontes.urllib.request, "urlopen", lambda p, timeout: pedidos.append(p) or _Resposta(p.full_url))
    fontes.ler_da_rede(url)
    assert pedidos[0].get_header("Authorization") == ("Bearer segredo" if com_token else None)
    if com_token:  # não segue redirecionamento para outro host
        assert "Authorization" not in pedidos[0].headers


def test_sem_token_nao_manda_authorization(monkeypatch):
    pedidos = []
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(fontes.urllib.request, "urlopen", lambda p, timeout: pedidos.append(p) or _Resposta(p.full_url))
    fontes.ler_da_rede("https://api.github.com/repos/x/y/tags")
    assert pedidos[0].get_header("Authorization") is None


# --- revisão final: rede, hashes malformados e ordenação ---


def test_ler_da_rede_recusa_http(monkeypatch):
    monkeypatch.setattr(fontes.urllib.request, "urlopen", lambda *a, **k: pytest.fail("não podia abrir a conexão"))
    with pytest.raises(fontes.FonteIndisponivel, match="https"):
        fontes.ler_da_rede("http://www.python.org/api/v2/downloads/")


def test_ler_da_rede_recusa_redirecionamento_para_http(monkeypatch):
    monkeypatch.setattr(fontes.urllib.request, "urlopen", lambda p, timeout: _Resposta("http://exemplo.com/x"))
    with pytest.raises(fontes.FonteIndisponivel, match="Redirecionamento"):
        fontes.ler_da_rede("https://www.gyan.dev/ffmpeg/builds/release-version")


def test_ler_da_rede_leitura_incompleta_vira_fonte_indisponivel(monkeypatch):
    class _Cortada(_Resposta):
        def read(self):
            raise fontes.http.client.IncompleteRead(b"meio")

    monkeypatch.setattr(fontes.urllib.request, "urlopen", lambda p, timeout: _Cortada(p.full_url))
    with pytest.raises(fontes.FonteIndisponivel):
        fontes.ler_da_rede("https://www.python.org/api/v2/downloads/")


@pytest.mark.parametrize("publicado", [b"abc123", b"z" * 64, b"", b"\xff" * 64])
def test_ffmpeg_hash_malformado_e_semhash(publicado):
    mapa = {GYAN + "release-version": b"9.0.2", GYAN + "packages/ffmpeg-9.0.2-essentials_build.zip.sha256": publicado}
    with pytest.raises(fontes.SemHash):
        fontes.ffmpeg(_ler_de(mapa))


def test_ffmpeg_rede_fora_no_sha256_e_indisponivel():
    def ler(url):
        if url.endswith(".sha256"):
            raise fontes.FonteIndisponivel("sem rede")
        return b"9.0.2"

    with pytest.raises(fontes.FonteIndisponivel) as erro:
        fontes.ffmpeg(ler)
    assert not isinstance(erro.value, fontes.SemHash)


def test_qt_sdk_sha1_malformado_e_semhash():
    def ler(url):
        return b"nao-e-hash" if url.endswith(".sha1") else _ler_qt()(url)

    with pytest.raises(fontes.SemHash):
        fontes.qt_sdk("6.12.0", ler)


def test_versoes_do_python_ordem_numerica():
    dados = [{"name": f"Python {v}", "pre_release": False} for v in ("3.9.20", "3.14.1", "3.10.0", "3.14.0")]
    ler = _ler_de({PY + "release/?version=3&is_published=true": json.dumps(dados).encode()})
    assert fontes.versoes_do_python(ler) == ["3.14.1", "3.14.0", "3.10.0", "3.9.20"]
