# test_shared_canal.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O canal (desenvolvimento ou final) decide a pasta e a chave de registro do app.

Cada teste carrega uma cópia do `shared.py` em `tmp_path`, com o `instalacao.json` ao lado:
nada é gravado no código-fonte e o `cartridges.shared` do processo nunca é recarregado.
"""

import importlib.util
import json
import shutil
from pathlib import Path

import pytest

from cartridges import shared as shared_real

MENSAGEM = "A instalação do Cartridges está danificada. Reinstale o aplicativo."


@pytest.fixture
def carregar(tmp_path, monkeypatch):
    """Carrega a cópia do `shared` com o `instalacao.json` pedido (texto, bytes ou None)."""
    monkeypatch.delenv("CARTRIDGES_DADOS", raising=False)
    monkeypatch.delenv("CARTRIDGES_REGISTRO", raising=False)
    copia = tmp_path / "shared.py"
    shutil.copy(shared_real.__file__, copia)

    def _carregar(conteudo: str | bytes | None):
        arquivo = copia.parent / "instalacao.json"
        arquivo.unlink(missing_ok=True)
        if isinstance(conteudo, str):
            arquivo.write_text(conteudo, encoding="utf-8")
        elif conteudo is not None:
            arquivo.write_bytes(conteudo)
        especificacao = importlib.util.spec_from_file_location("shared_copia", copia)
        modulo = importlib.util.module_from_spec(especificacao)
        especificacao.loader.exec_module(modulo)
        return modulo

    return _carregar


def test_sem_instalacao_json_e_desenvolvimento(carregar):
    modulo = carregar(None)
    assert modulo.canal() == "desenvolvimento"
    assert modulo.app_dir.name == "io.github.joaomgabaldi.Cartridges-dev"
    assert modulo.chave_do_registro.endswith(r"\Cartridges-dev")


def test_canal_final_usa_os_caminhos_reais(carregar):
    # Só calcula caminhos: nada é lido nem criado.
    modulo = carregar(json.dumps({"canal": "final"}))
    assert modulo.canal() == "final"
    assert modulo.app_dir.name == "io.github.joaomgabaldi.Cartridges"
    assert modulo.chave_do_registro == r"Software\GSettings\io\github\joaomgabaldi\Cartridges"
    assert modulo.games_dir == modulo.app_dir / "games"


@pytest.mark.parametrize(
    "conteudo", ["{isto não é json", "[]", '{"canal": 3}', b"\xff\xfe\x00{"]
)
def test_instalacao_corrompida_recusa(carregar, conteudo):
    with pytest.raises(SystemExit, match=MENSAGEM):
        carregar(conteudo)


def test_canal_desconhecido_recusa(carregar):
    with pytest.raises(SystemExit, match=MENSAGEM):
        carregar(json.dumps({"canal": "beta"}))


def test_variaveis_de_ambiente_tem_prioridade(carregar, monkeypatch, tmp_path):
    monkeypatch.setenv("CARTRIDGES_DADOS", str(tmp_path))
    monkeypatch.setenv("CARTRIDGES_REGISTRO", r"Software\CartridgesTestes\x")
    for conteudo in (None, json.dumps({"canal": "final"})):
        modulo = carregar(conteudo)
        assert modulo.app_dir == tmp_path
        assert modulo.chave_do_registro == r"Software\CartridgesTestes\x"


def test_nenhum_instalacao_json_no_codigo_fonte():
    assert not Path(shared_real.__file__).with_name("instalacao.json").exists()
