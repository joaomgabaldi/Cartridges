# test_redefinir.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Redefinir Cartridges: a pasta do app esvaziada e as configurações no padrão."""

from kyron import shared
from kyron.utils import redefinir


def _app(tmp_path, monkeypatch):
    app = tmp_path / "app"
    app.mkdir()
    monkeypatch.setattr(shared, "app_dir", app)
    return app


def test_sem_agendamento_nada_muda(tmp_path, monkeypatch, schema):
    app = _app(tmp_path, monkeypatch)
    (app / "games").mkdir()
    (app / "games" / "jogo.json").write_text("{}", encoding="utf-8")
    schema.set_string("shortcuts-location", "D:\\Atalhos")

    assert redefinir.aplicar_pendente() is None

    assert (app / "games" / "jogo.json").exists()
    assert schema.get_string("shortcuts-location") == "D:\\Atalhos"


def test_agendado_esvazia_a_pasta_e_zera_as_configuracoes(tmp_path, monkeypatch, schema, state_schema):
    app = _app(tmp_path, monkeypatch)
    for pasta in ("games", "contas", "saves/Jogo", "logs", "cache/conquistas"):
        (app / pasta).mkdir(parents=True)
        (app / pasta / "a.txt").write_text("x", encoding="utf-8")
    (app / "sessions.jsonl").write_text("x", encoding="utf-8")
    fora = tmp_path / "saves_fora"
    fora.mkdir()
    (fora / "mapping.yaml").write_text("x", encoding="utf-8")
    principal, estado = schema, state_schema
    principal.set_string("shortcuts-location", "D:\\Atalhos")
    principal.set_string("pasta-dos-saves", str(fora))
    principal.set_boolean("assistente-concluido", True)
    estado.set_string("sort-mode", "newest")

    padrao = {"shortcuts-location": "", "pasta-dos-saves": "", "assistente-concluido": False}
    redefinir.agendar()
    assert redefinir.aplicar_pendente() is True

    assert list(app.iterdir()) == []
    for chave in ("shortcuts-location", "pasta-dos-saves", "assistente-concluido"):
        assert principal.get_value(chave) == padrao[chave], chave
    assert estado.get_string("sort-mode") == "last_played"
    # A pasta escolhida fora do app é só esquecida.
    assert (fora / "mapping.yaml").exists()


def test_falha_ao_apagar_avisa_e_nao_repete(tmp_path, monkeypatch, schema):
    app = _app(tmp_path, monkeypatch)
    (app / "games").mkdir()
    redefinir.agendar()

    def recusar(_pasta):
        raise PermissionError("em uso")

    monkeypatch.setattr(redefinir, "_apagar_pasta", recusar)

    assert redefinir.aplicar_pendente() is False
    assert isinstance(redefinir.falha, PermissionError)
    # Repetir sozinho numa abertura futura apagaria o que viesse depois.
    assert not redefinir.ha_pendente()


def test_apaga_sobras_da_restauracao_e_mantem_o_estado_de_fora(tmp_path, monkeypatch, schema, state_schema):
    app = _app(tmp_path, monkeypatch)
    anterior = tmp_path / "app.anterior"
    anterior.mkdir()
    (anterior / "games").mkdir()
    principal, estado = schema, state_schema
    principal.set_string("fita-estado-anterior", "{}")
    principal.set_string("session-wallpaper-saved", "{}")
    estado.set_string("steam-limiter-tokens-history", "[]")
    redefinir.agendar()

    assert redefinir.aplicar_pendente() is True

    assert not anterior.exists()
    assert list(app.iterdir()) == []
    assert principal.get_string("fita-estado-anterior") == "{}"
    assert principal.get_string("session-wallpaper-saved") == "{}"
    assert estado.get_string("steam-limiter-tokens-history") == "[]"
