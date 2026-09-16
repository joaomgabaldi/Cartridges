# test_session_fita.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""As fitas de LED: o que fica em disco e qual cor cada jogo recebe."""

from pathlib import Path
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


def test_salvar_cor_nao_levanta_sem_permissao(tmp_path, monkeypatch, schema):
    """Quem chama está na thread de UI: disco negado é aviso, nunca exceção."""
    jogo = _jogo(tmp_path)

    def negar(*_args, **_kwargs):
        raise PermissionError("pasta negada")

    monkeypatch.setattr(Path, "mkdir", negar)
    cor = session_fita.Cor(340, 1000, 150)
    assert session_fita.salvar_cor(jogo.game_id, jogo.name, cor) is None
    assert not session_fita.escolhida(jogo.game_id)


def test_redefinir_nao_levanta_quando_o_unlink_falha(tmp_path, monkeypatch, schema):
    jogo = _jogo(tmp_path)
    session_fita.salvar_cor(jogo.game_id, jogo.name, session_fita.Cor(340, 1000, 150))

    def negar(*_args, **_kwargs):
        raise OSError("arquivo em uso")

    monkeypatch.setattr(Path, "unlink", negar)
    assert session_fita.redefinir(jogo.game_id) is None


def test_sidecar_corrompido_volta_para_a_capa(tmp_path, schema):
    jogo = _jogo(tmp_path)
    shared.fitas_dir.mkdir(parents=True, exist_ok=True)
    (shared.fitas_dir / f"{jogo.game_id}.json").write_text("{lixo", encoding="utf-8")
    assert not session_fita.escolhida(jogo.game_id)
    cor = session_fita.cor_do_jogo(jogo)
    assert cor.matiz < 10 or cor.matiz > 350


class FitaFalsa:
    """Um módulo Tuya de mentira, que anota o que mandaram nele."""

    def __init__(self, dps=None, quebrada=False):
        self.dps = dps or {"20": False, "21": "colour", "24": "000003e800b4"}
        self.quebrada = quebrada
        self.recebidos = []

    def status(self):
        if self.quebrada:
            return {"Error": "Network Error: Device Unreachable", "Err": "905"}
        return {"dps": dict(self.dps)}

    def set_multiple_values(self, valores, nowait=False):
        if self.quebrada:
            return {"Error": "Network Error: Device Unreachable", "Err": "905"}
        self.recebidos.append(dict(valores))
        self.dps.update({str(k): v for k, v in valores.items()})
        return {"dps": dict(self.dps)}


@pytest.fixture
def falsas(monkeypatch):
    """Troca as fitas de verdade por módulos de mentira, por id."""
    modulos = {}

    def montar(*fitas_falsas):
        lista = []
        for indice, quebrada in enumerate(fitas_falsas):
            fita = session_fita.Fita(f"Fita {indice}", f"eb{indice}", "1.2.3.4", "k")
            modulos[fita.id] = FitaFalsa(quebrada=quebrada)
            lista.append(fita)
        session_fita.gravar_fitas(lista)
        monkeypatch.setattr(session_fita, "_dispositivo", lambda f: modulos[f.id])
        return modulos

    return montar


def test_cor_vira_hexadecimal_do_jeito_do_modulo():
    assert session_fita.hsv_hex(session_fita.Cor(340, 1000, 150)) == "015403e80096"


def test_hexadecimal_volta_a_ser_cor():
    assert session_fita.cor_de_hex("015403e80096") == session_fita.Cor(340, 1000, 150)


def test_hexadecimal_estranho_vira_nada():
    assert session_fita.cor_de_hex("nao-e-hex") is None


def test_ler_estado_traz_ligada_e_cor(falsas):
    modulos = falsas(False)
    fita = session_fita.fitas()[0]
    assert session_fita.ler_estado(fita) == {"ligada": False, "cor": "000003e800b4"}
    assert modulos


def test_ler_estado_de_fita_fora_do_ar_e_nada(falsas):
    falsas(True)
    assert session_fita.ler_estado(session_fita.fitas()[0]) is None


def test_aplicar_liga_poe_modo_cor_e_manda_a_cor(falsas):
    modulos = falsas(False)
    fita = session_fita.fitas()[0]
    assert session_fita.aplicar(fita, True, "015403e80096") is True
    assert modulos[fita.id].recebidos == [
        {"20": True, "21": "colour", "24": "015403e80096"}
    ]


def test_aplicar_em_fita_fora_do_ar_devolve_falso(falsas):
    falsas(True)
    assert session_fita.aplicar(session_fita.fitas()[0], True, "015403e80096") is False
