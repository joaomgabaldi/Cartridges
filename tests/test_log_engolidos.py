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


def test_sidecar_ilegivel_deixa_aviso_e_ausente_nao(app_dirs, caplog):
    session_fita.shared.fitas_dir.mkdir(parents=True, exist_ok=True)
    (session_fita.shared.fitas_dir / "quebrado.json").write_text("{", encoding="utf-8")

    assert session_fita._ler_sidecar("quebrado") is None  # pylint: disable=protected-access
    assert session_fita._ler_sidecar("ausente") is None  # pylint: disable=protected-access

    mensagens = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("quebrado.json" in m for m in mensagens)
    assert not any("ausente" in m for m in mensagens)
