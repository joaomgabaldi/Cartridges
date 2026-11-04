# test_iss_final.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O `.iss` do canal final, que roda por cima da versão GTK em modo silencioso pelo atualizador.

Lê o texto renderizado e resolve os `#ifdef` à mão, sem o ISCC: um `[InstallDelete]` a mais apaga algo do usuário,
um a menos mistura as árvores e uma página ou `MsgBox` trava a atualização.
"""

import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from cartridges import shared

_RAIZ = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("montar_app_qt", _RAIZ / "build-aux" / "windows" / "montar_app_qt.py")
montar_app_qt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(montar_app_qt)

_DIRETIVA = re.compile(r"^#(ifdef|ifndef|else|endif)\b\s*(\w*)")


def _ramo(texto: str, *definidos: str) -> str:
    """O texto depois do pré-processador do Inno para os `#ifdef`, sem as linhas das diretivas."""
    vivos: list[bool] = []
    saida = []
    for linha in texto.splitlines():
        achou = _DIRETIVA.match(linha)
        if not achou:
            if all(vivos):
                saida.append(linha)
        elif achou[1] == "ifdef":
            vivos.append(achou[2] in definidos)
        elif achou[1] == "ifndef":
            vivos.append(achou[2] not in definidos)
        elif achou[1] == "else":
            vivos[-1] = not vivos[-1]
        else:
            vivos.pop()
    assert not vivos, "#ifdef sem #endif"
    return "\n".join(saida)


def _secao(texto: str, nome: str) -> str:
    achou = re.search(rf"^\[{nome}\]\n(.*?)(?=^\[\w+\]$|\Z)", texto, re.M | re.S)
    return achou[1] if achou else ""


def _sem_comentarios(secao: str) -> list[str]:
    return [l for l in secao.splitlines() if l.strip() and not l.startswith(";")]


@pytest.fixture
def renderizado(tmp_path):
    return montar_app_qt.renderizar_iss(tmp_path / "qt-final").read_text(encoding="utf-8-sig")


@pytest.fixture
def final(renderizado):
    return _ramo(renderizado, "Repo", "PastaApp")


@pytest.fixture
def instalacao(final):
    """O `[Code]` que roda ao instalar, sem comentários: tudo antes do desinstalador."""
    antes, separador, _ = _secao(final, "Code").partition("procedure CurUninstallStepChanged")
    assert separador
    return "\n".join(l for l in antes.splitlines() if not l.lstrip().startswith("//"))


def _apagados(iss: str) -> set[str]:
    linhas = _sem_comentarios(_secao(iss, "InstallDelete"))
    pastas = {re.fullmatch(r'Type: filesandordirs; Name: "\{app\}\\(\w+)"', l)[1] for l in linhas}
    assert len(pastas) == len(linhas)
    return pastas


def test_iss_final_apaga_a_arvore_do_gtk_e_a_do_qt(final):
    assert _apagados(final) == {"bin", "etc", "lib", "share", "python", "app", "licencas"}


def test_iss_de_desenvolvimento_apaga_so_a_arvore_do_qt(renderizado):
    assert _apagados(_ramo(renderizado, "DESENVOLVIMENTO", "Repo", "PastaApp")) == {"bin", "python", "lib", "app"}


def test_iss_final_nao_apaga_dados_nem_registro_ao_instalar(final, instalacao):
    # Fica a migração da instalação "só para mim" (D97), que lê {localappdata} só para não apagar os dados e
    # só toca a chave de desinstalação dela no HKCU.
    assert not _secao(final, "Registry") and not _secao(final, "UninstallDelete")
    assert "GSettings" not in instalacao
    for secao in ("Setup", "InstallDelete", "Files", "Icons", "Run"):
        texto = _secao(final, secao)
        assert "{localappdata}" not in texto and "HKCU" not in texto and "HKEY_CURRENT_USER" not in texto
    dados = [l.strip() for l in instalacao.splitlines() if "{localappdata}" in l]
    assert dados == ["Dados := Normalizar(ExpandConstant('{localappdata}\\io.github.joaomgabaldi.Cartridges'));"]
    assert "(Pos(Pasta, Dados) = 1) or (Pos(Dados, Pasta) = 1)" in instalacao
    # `Dados` só aparece na guarda: nada a apaga.
    assert not re.search(r"\b(?:DelTree|ApagarItem|ApagarInstalacaoAntiga|DeleteFile)\(Dados", instalacao)
    registro = [l.strip() for l in instalacao.splitlines() if re.search(r"\bHKCU\b", l)]
    assert registro and all("ChaveDoUsuario" in l for l in registro), registro
    assert "HKEY_CURRENT_USER" not in instalacao


def test_iss_final_sem_nvidia_nem_pagina_extra(final, instalacao):
    assert "nvidia" not in final.lower()
    assert not re.search(r"Create\w*Page\b|\bInitializeWizard\b|\bShouldSkipPage\b", final)
    assert "MsgBox" not in instalacao
    # Nada de esperar um programa externo no meio da instalação silenciosa.
    assert not re.search(r"\bExec\w*\(", final)


def test_iss_final_reabre_o_app_tambem_em_silencio(final):
    # O atualizador conta com o app reaberto no fim da instalação silenciosa.
    assert "skipifsilent" not in _secao(final, "Run")


def test_iss_final_mantem_o_appid_e_o_exe(final):
    assert "AppId={{88FC7AF8-9F74-40EC-AAED-FA6356261CBB}\n" in final
    assert "DefaultDirName={autopf64}\\Cartridges Revamped\n" in final
    assert '#define MyAppExeName "Cartridges.exe"' in final
    assert 'Filename: "{app}\\bin\\{#MyAppExeName}"' in _secao(final, "Run")
    for linha in _sem_comentarios(_secao(final, "Icons")):
        assert 'Filename: "{app}\\bin\\{#MyAppExeName}"' in linha
    assert '#define MyAppName "Cartridges"' in final
    assert "OutputBaseFilename=Cartridges Windows\n" in final


def test_iss_final_empacota_a_pasta_montada(final, renderizado):
    assert 'Source: "{#PastaApp}\\*"; DestDir: "{app}"' in _secao(final, "Files")
    assert "..\\..\\" not in final
    # Os dois canais exigem os /D: sem eles o ISCC para, em vez de empacotar outra pasta.
    assert renderizado.index("#ifndef Repo") < renderizado.index("#ifdef DESENVOLVIMENTO")


def test_iss_usa_a_versao_do_shared(renderizado):
    assert "@VERSION@" not in renderizado
    assert f'#define MyAppVersion "{shared.VERSION}"' in renderizado


def test_workflow_final_monta_o_canal_final_so_na_main():
    """O `instalador.yml` não pode rodar aqui: o que dá para garantir é o texto."""
    texto = (_RAIZ / ".github" / "workflows" / "instalador.yml").read_text(encoding="utf-8")
    assert "if: github.ref == 'refs/heads/main'" in texto
    assert "--canal final" in texto and "DESENVOLVIMENTO" not in texto and "--canal desenvolvimento" not in texto
    assert texto.index("data_da_release.py") < texto.index("--canal final")
    assert not re.search(r"msys|meson|gtk-corrigido|patched-gtk|versao_do_dia", texto, re.I)
    # A pasta montada roda sozinha na CI antes de virar instalador.
    verificacao = r"_dist\qt-final\python\python.exe -B build-aux\windows\verificar_pasta.py _dist\qt-final"
    assert texto.index("--canal final") < texto.index(verificacao) < texto.index("ISCC.exe")
    # Num job com `contents: write`, nada de dependência sem versão.
    assert "--no-deps py7zr==1.1.4 " in texto


def test_verificacao_exige_o_que_a_capa_de_video_usa():
    texto = (_RAIZ / "build-aux" / "windows" / "verificar_pasta.py").read_text(encoding="utf-8")
    for exigido in ("libwebp_anim", "capa_video.converter(", "pyca/cryptography", "CARTRIDGES_DADOS", "CARTRIDGES_REGISTRO"):
        assert exigido in texto, exigido


def test_verificacao_recusa_o_canal_final_fora_da_ci(tmp_path):
    # A pasta do canal final aponta para os dados reais: nesta máquina ela nunca roda.
    pacote = tmp_path / "app" / "cartridges"
    pacote.mkdir(parents=True)
    (pacote / "instalacao.json").write_text(json.dumps({"canal": "final"}), encoding="utf-8")
    ambiente = {k: v for k, v in os.environ.items() if k != "GITHUB_ACTIONS"}
    resultado = subprocess.run(
        [sys.executable, "-I", "-X", "utf8", str(_RAIZ / "build-aux" / "windows" / "verificar_pasta.py"), str(tmp_path)],
        env=ambiente, capture_output=True, encoding="utf-8", timeout=60, check=False,
    )  # fmt: skip
    assert resultado.returncode != 0
    assert "só roda na CI" in resultado.stderr
