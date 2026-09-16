# test_session_fita.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""As fitas de LED: o que fica em disco e qual cor cada jogo recebe."""

from types import SimpleNamespace

import pytest
from PIL import Image

from cartridges import shared
from cartridges.utils import session_fita


@pytest.fixture(autouse=True)
def pastas(tmp_path, monkeypatch):
    """Tudo o que o módulo grava vai para uma pasta descartável."""
    monkeypatch.setattr(shared, "fitas_dir", tmp_path / "fitas")
    monkeypatch.setattr(shared, "fitas_arquivo", tmp_path / "fitas.json")
    return tmp_path


def _jogo(tmp_path, game_id="jogo-1", cor=(220, 20, 20)):
    capa = tmp_path / f"{game_id}.png"
    Image.new("RGB", (60, 90), cor).save(capa)
    return SimpleNamespace(game_id=game_id, name="Jogo", get_cover_path=lambda: capa)


def test_sem_configuracao_nao_ha_fitas():
    assert session_fita.fitas() == []


def test_fitas_gravadas_voltam_iguais():
    uma = session_fita.Fita("Centro", "eb00", "192.168.0.150", "chave", "3.3")
    session_fita.gravar_fitas([uma])
    assert session_fita.fitas() == [uma]


def test_arquivo_corrompido_nao_levanta():
    shared.fitas_arquivo.write_text("{lixo", encoding="utf-8")
    assert session_fita.fitas() == []


def test_cor_do_jogo_sai_da_capa(tmp_path, schema):
    cor = session_fita.cor_do_jogo(_jogo(tmp_path))
    assert cor.matiz < 10 or cor.matiz > 350
    assert cor.brilho == schema.get_int("fita-brilho-padrao")


def test_escolha_manual_vence_a_capa(tmp_path, schema):
    jogo = _jogo(tmp_path)
    session_fita.salvar_cor(jogo.game_id, jogo.name, session_fita.Cor(340, 1000, 150))
    cor = session_fita.cor_do_jogo(jogo)
    assert cor == session_fita.Cor(340, 1000, 150)
    assert session_fita.escolhida(jogo.game_id)


def test_redefinir_devolve_o_automatico(tmp_path, schema):
    jogo = _jogo(tmp_path)
    session_fita.salvar_cor(jogo.game_id, jogo.name, session_fita.Cor(340, 1000, 150))
    session_fita.redefinir(jogo.game_id)
    assert not session_fita.escolhida(jogo.game_id)
    assert session_fita.cor_do_jogo(jogo).matiz != 340


def test_jogo_sem_capa_usa_o_roxo_do_app(tmp_path, schema):
    jogo = SimpleNamespace(game_id="sem-capa", name="X", get_cover_path=lambda: None)
    cor = session_fita.cor_do_jogo(jogo)
    assert (cor.matiz, cor.saturacao) == session_fita.ROXO_DO_APP
