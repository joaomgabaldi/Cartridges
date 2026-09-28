"""Erros que o app contorna em silêncio, mas que escondem perda ou quebra.

Um arquivo da biblioteca que não pôde ser lido é contornado (o app segue),
mas tem de deixar rastro no log. A ausência do arquivo continua sem aviso:
é o estado normal de quem nunca configurou aquilo.
"""

import logging

from cartridges import main as main_module
from cartridges.utils import session_fita


def test_jogo_com_json_invalido_deixa_aviso(store, app_dirs, caplog):
    (app_dirs.games / "imported_9.json").write_text("{not json", encoding="utf-8")

    main_module.CartridgesApplication.load_games_from_disk(None)

    aviso = next(r for r in caplog.records if "imported_9.json" in r.getMessage())
    assert aviso.levelno == logging.WARNING


def test_jogo_que_o_hltb_nao_conhece_nao_deixa_rastro_de_erro(
    monkeypatch, store, make_game, caplog
):
    # "Não encontrado" é resposta, não erro: eram 6 tracebacks por abertura no
    # log de quem usa. Uma falha de verdade continua com o rastro.
    from types import SimpleNamespace  # noqa: PLC0415

    from cartridges.store.managers import hltb_manager  # noqa: PLC0415
    from cartridges.utils import hltb, hltb_backfill  # noqa: PLC0415

    caplog.set_level(logging.DEBUG)
    store.add_game(make_game(game_id="a", name="a", has_hltb_times=False, hltb_id=None), {})
    store.add_game(make_game(game_id="b", name="b", has_hltb_times=False, hltb_id=None), {})
    erros = {"a": hltb.HLTBGameNotFoundError(), "b": hltb.HLTBUnavailableError("fora")}

    def buscar(_helper, nome, _hltb_id):
        raise erros[nome]

    monkeypatch.setattr(hltb_backfill, "fetch_times", buscar)
    monkeypatch.setattr(hltb_backfill, "shared_helper", lambda: None)
    monkeypatch.setattr(
        hltb_backfill.threading,
        "Thread",
        lambda target, args, daemon: SimpleNamespace(start=lambda: target(*args)),
    )
    sweep = hltb_backfill.HLTBBackfill()
    try:
        sweep.run_async()
    finally:
        sweep.stop()

    manager = hltb_manager.HLTBManager.__new__(hltb_manager.HLTBManager)
    monkeypatch.setattr(manager, "_fetch", lambda game: buscar(None, game.name, None))
    monkeypatch.setattr(hltb_manager.shared.schema, "get_boolean", lambda _k: True)
    for game_id in ("a", "b"):
        manager.main(store[game_id], {})

    rastros = {
        r.getMessage().rsplit(" ", 1)[-1]
        for r in caplog.records
        if "HowLongToBeat" in r.getMessage() and r.exc_info
    }
    assert rastros == {"b"}


def test_sidecar_ilegivel_deixa_aviso_e_ausente_nao(app_dirs, caplog):
    session_fita.shared.fitas_dir.mkdir(parents=True, exist_ok=True)
    (session_fita.shared.fitas_dir / "quebrado.json").write_text("{", encoding="utf-8")

    assert session_fita._ler_sidecar("quebrado") is None  # pylint: disable=protected-access
    assert session_fita._ler_sidecar("ausente") is None  # pylint: disable=protected-access

    mensagens = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("quebrado.json" in m for m in mensagens)
    assert not any("ausente" in m for m in mensagens)
