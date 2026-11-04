# test_baixar_qt_sdk.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A extração do SDK só vale depois de terminar: o marcador decide, não os arquivos soltos."""

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import baixar_qt_sdk as sdk  # noqa: E402


def _falsa(chamadas, falhar_no=None):
    def extrair(pacote, destino):
        chamadas.append(pacote.name)
        destino.mkdir(parents=True, exist_ok=True)
        (destino / pacote.name).write_text("x")
        if pacote.name == falhar_no:
            raise OSError("interrompida")

    return extrair


def test_extracao_interrompida_recomeca_do_zero(tmp_path):
    qt = tmp_path / "qt"
    pacotes = [tmp_path / "a.7z", tmp_path / "b.7z"]
    chamadas = []
    with pytest.raises(OSError):
        sdk.extrair_qt(pacotes, qt, _falsa(chamadas, falhar_no="b.7z"))
    assert not (qt / sdk.MARCADOR).exists()
    chamadas.clear()
    sdk.extrair_qt(pacotes, qt, _falsa(chamadas))
    assert chamadas == ["a.7z", "b.7z"] and (qt / sdk.MARCADOR).exists()
    chamadas.clear()
    sdk.extrair_qt(pacotes, qt, _falsa(chamadas))
    assert chamadas == []


def test_pacotes_tem_sha256_fixado():
    assert {nome: sha for nome, (_, sha) in sdk.PACOTES.items()} == {
        "qtbase": "219d1b86def3be418e31d704572bc4acc91b2ec373c65595c9fb12b42bf098dc",
        "qtdeclarative": "258146e9972fadbc1162cda31c7d7ed7e627f5022b2a848f2edb84d9c2ce27db",
    }


def test_nao_baixa_o_sha1_remoto(tmp_path, monkeypatch):
    import hashlib

    monkeypatch.setattr(sdk, "DEPS", tmp_path)
    urls = []
    monkeypatch.setattr(sdk, "_baixar", lambda url: urls.append(url) or b"conteudo")
    sdk.baixar_pacote("qtbase", "qtbase.7z", hashlib.sha256(b"conteudo").hexdigest())
    assert urls == [sdk.BASE + "qtbase.7z"]


def test_sha256_errado_descarta_o_arquivo(tmp_path, monkeypatch):
    monkeypatch.setattr(sdk, "DEPS", tmp_path)
    monkeypatch.setattr(sdk, "_baixar", lambda url: b"adulterado")
    with pytest.raises(RuntimeError):
        sdk.baixar_pacote("qtbase", "qtbase.7z", "0" * 64)
    assert not (tmp_path / "downloads" / "qtbase.7z").exists()


def test_marcador_de_outra_identidade_extrai_de_novo(tmp_path):
    qt = tmp_path / "qt"
    qt.mkdir()
    (qt / sdk.MARCADOR).write_text("outra versao", encoding="utf-8")
    (qt / "sobra.txt").write_text("antiga")
    chamadas = []
    sdk.extrair_qt([tmp_path / "a.7z"], qt, _falsa(chamadas))
    assert chamadas == ["a.7z"] and not (qt / "sobra.txt").exists()
    assert (qt / sdk.MARCADOR).read_text(encoding="utf-8") == sdk._identidade()


def test_marcador_igual_nao_extrai(tmp_path):
    qt = tmp_path / "qt"
    qt.mkdir()
    (qt / sdk.MARCADOR).write_text(sdk._identidade(), encoding="utf-8")
    chamadas = []
    sdk.extrair_qt([tmp_path / "a.7z"], qt, _falsa(chamadas))
    assert chamadas == []


class _Git:
    """O `git` falso: o clone cria as pastas e o `rev-parse` devolve os commits combinados."""

    def __init__(self, qwk=None, qmsetup=None):
        self.qwk, self.qmsetup = qwk or sdk.QWK_COMMIT, qmsetup or sdk.QMSETUP_COMMIT
        self.clones = 0

    def __call__(self, comando, **_):
        if comando[1] == "clone":
            self.clones += 1
            pasta = Path(comando[-1])
            (pasta / "qmsetup").mkdir(parents=True)
            (pasta / "CMakeLists.txt").write_text("x")
            (pasta / "qmsetup" / "CMakeLists.txt").write_text("x")
            return subprocess.CompletedProcess(comando, 0, "", "")
        commit = self.qmsetup if Path(comando[2]).name == "qmsetup" else self.qwk
        return subprocess.CompletedProcess(comando, 0, commit + "\n", "")


def test_qwindowkit_no_commit_fixado_nao_clona(tmp_path, monkeypatch):
    monkeypatch.setattr(sdk, "DEPS", tmp_path)
    git = _Git()
    (tmp_path / "qwindowkit" / "qmsetup").mkdir(parents=True)
    (tmp_path / "qwindowkit" / "CMakeLists.txt").write_text("x")
    (tmp_path / "qwindowkit" / "qmsetup" / "CMakeLists.txt").write_text("x")
    sdk.preparar_qwindowkit(git)
    assert git.clones == 0


def test_qwindowkit_em_outro_commit_clona_de_novo(tmp_path, monkeypatch):
    monkeypatch.setattr(sdk, "DEPS", tmp_path)
    velho = tmp_path / "qwindowkit"
    (velho / "qmsetup").mkdir(parents=True)
    (velho / "CMakeLists.txt").write_text("x")
    (velho / "qmsetup" / "CMakeLists.txt").write_text("x")
    (velho / "velho.txt").write_text("x")
    git = _Git()
    antigo = git.qwk
    git.qwk = "0" * 40  # o checkout existente está noutro commit; o clone novo já traz o fixado

    def rodar(comando, **kw):
        if comando[1] == "clone":
            git.qwk = antigo
        return git(comando, **kw)

    sdk.preparar_qwindowkit(rodar)
    assert git.clones == 1 and not (velho / "velho.txt").exists() and (velho / "CMakeLists.txt").exists()


def test_commit_errado_depois_de_clonar_falha_e_limpa(tmp_path, monkeypatch):
    monkeypatch.setattr(sdk, "DEPS", tmp_path)
    git = _Git(qmsetup="1" * 40)
    with pytest.raises(RuntimeError):
        sdk.preparar_qwindowkit(git)
    assert not (tmp_path / "qwindowkit").exists() and not (tmp_path / "qwindowkit.parcial").exists()
