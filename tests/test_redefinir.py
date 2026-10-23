# test_redefinir.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Redefinir Cartridges: a pasta do app esvaziada e as configurações no padrão."""

from cartridges import shared
from cartridges.utils import redefinir


def _app(tmp_path, monkeypatch):
    # Fora de `tmp_path` direto: lá moram os schemas compilados da fixture `settings`.
    app = tmp_path / "app"
    app.mkdir()
    monkeypatch.setattr(shared, "app_dir", app)
    return app


def test_sem_agendamento_nada_muda(tmp_path, monkeypatch, settings):
    app = _app(tmp_path, monkeypatch)
    (app / "games").mkdir()
    (app / "games" / "jogo.json").write_text("{}", encoding="utf-8")
    settings[0].set_string("shortcuts-location", "D:\\Atalhos")

    assert redefinir.aplicar_pendente() is None

    assert (app / "games" / "jogo.json").exists()
    assert settings[0].get_string("shortcuts-location") == "D:\\Atalhos"


def test_agendado_esvazia_a_pasta_e_zera_as_configuracoes(tmp_path, monkeypatch, settings):
    app = _app(tmp_path, monkeypatch)
    for pasta in ("games", "contas", "saves/Jogo", "logs", "cache/conquistas"):
        (app / pasta).mkdir(parents=True)
        (app / pasta / "a.txt").write_text("x", encoding="utf-8")
    (app / "sessions.jsonl").write_text("x", encoding="utf-8")
    fora = tmp_path / "saves_fora"
    fora.mkdir()
    (fora / "mapping.yaml").write_text("x", encoding="utf-8")
    principal, estado = settings
    principal.set_string("shortcuts-location", "D:\\Atalhos")
    principal.set_string("pasta-dos-saves", str(fora))
    principal.set_boolean("assistente-concluido", True)
    estado.set_string("sort-mode", "newest")

    redefinir.agendar()
    assert redefinir.aplicar_pendente() is True

    assert list(app.iterdir()) == []
    for chave in ("shortcuts-location", "pasta-dos-saves", "assistente-concluido"):
        assert principal.get_user_value(chave) is None, chave
    assert estado.get_user_value("sort-mode") is None
    # A pasta escolhida fora do app é só esquecida.
    assert (fora / "mapping.yaml").exists()


def test_falha_ao_apagar_avisa_e_nao_repete(tmp_path, monkeypatch, settings):
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


def test_apaga_sobras_da_restauracao_e_mantem_o_estado_de_fora(tmp_path, monkeypatch, settings):
    app = _app(tmp_path, monkeypatch)
    anterior = tmp_path / "app.anterior"
    anterior.mkdir()
    (anterior / "games").mkdir()
    principal, estado = settings
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


def _confirmar(monkeypatch, em_andamento):
    from cartridges.saves import backup_de_saves  # noqa: PLC0415
    from tests.test_saves_ui import _preferencias, _toasts  # noqa: PLC0415

    monkeypatch.setattr(backup_de_saves, "disponivel", lambda: True)
    monkeypatch.setattr(backup_de_saves, "em_andamento", lambda: em_andamento)
    preferencias = _preferencias(monkeypatch)
    avisos = _toasts(preferencias, monkeypatch)
    saidas = []
    monkeypatch.setattr(shared.win.application, "quit", lambda: saidas.append(1), raising=False)
    preferencias._redefinir_respondido(None, "reset")
    return avisos, saidas


def test_confirmar_agenda_e_reinicia(monkeypatch):
    avisos, saidas = _confirmar(monkeypatch, em_andamento=False)

    assert redefinir.ha_pendente()
    assert saidas == [1]
    assert shared.win.application.reiniciar is True
    assert avisos == []


def test_confirmar_com_saves_em_andamento_nao_agenda(monkeypatch):
    avisos, saidas = _confirmar(monkeypatch, em_andamento=True)

    assert not redefinir.ha_pendente()
    assert saidas == []
    assert avisos == ["Aguarde o fim do backup ou da restauração dos saves e tente novamente."]
