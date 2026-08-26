# test_session_log.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O arquivo de histórico de sessões: gravar, ler, somar e apagar.

O que está sob teste é o formato, não a interface. Uma linha por sessão é uma
escolha que só se paga se o arquivo continuar legível depois de tudo o que
acontece com um arquivo aberto o tempo todo: um append no meio de uma queda de
energia, uma edição à mão, uma sessão apagada. Cada teste abaixo é uma dessas
situações.
"""

from time import time

import pytest

from cartridges import shared
from cartridges.utils import session_log


def path():
    return shared.app_dir / "sessions.jsonl"


def test_a_session_is_appended_and_read_back():
    session_log.record("imported_1", 3600, end=1_700_000_000)

    assert session_log.load("imported_1") == [
        {"game_id": "imported_1", "end": 1_700_000_000, "seconds": 3600}
    ]


def test_sessions_come_back_newest_first():
    session_log.record("g", 60, end=100)
    session_log.record("g", 60, end=300)
    session_log.record("g", 60, end=200)

    assert [entry["end"] for entry in session_log.load("g")] == [300, 200, 100]


def test_only_the_asked_game_comes_back():
    session_log.record("a", 60, end=100)
    session_log.record("b", 60, end=200)

    assert [entry["game_id"] for entry in session_log.load("a")] == ["a"]
    assert len(session_log.load()) == 2


def test_a_zero_length_session_is_not_recorded():
    """Um jogo que fechou antes de contar um segundo não vira linha nenhuma."""
    session_log.record("g", 0)
    session_log.record("g", -5)

    assert session_log.load("g") == []
    assert not path().exists()


def test_no_file_yet_is_not_an_error():
    """A biblioteca inteira antecede o histórico: ler antes da primeira sessão
    é o caso normal, não uma falha."""
    assert session_log.load() == []
    assert session_log.load("g") == []


def test_a_non_utf8_byte_costs_the_line_not_the_read():
    """Auditoria 26/08, B3: UnicodeDecodeError é ValueError, escapava do guard
    de OSError e quebrava a tela de detalhes de todo jogo com playtime."""
    session_log.record("a", 60, end=1000)
    with path().open("ab") as file:
        file.write(b'{"game_id": "b", "seconds": 1, "end": 2\xff}\n')
    session_log.record("c", 30, end=2000)

    assert {entry["game_id"] for entry in session_log.load()} == {"a", "c"}


def test_an_out_of_range_end_costs_the_line_not_the_dialog():
    """Auditoria 26/08, B2: `end` fora da faixa do fromtimestamp do Windows
    passava no load (que só checava tipo) e derrubava o diálogo de histórico."""
    session_log.record("ok", 60, end=1000)
    with path().open("a", encoding="utf-8") as file:
        file.write('{"game_id": "neg", "seconds": 60, "end": -1}\n')
        file.write('{"game_id": "huge", "seconds": 60, "end": 99999999999999}\n')
        file.write('{"game_id": "negsec", "seconds": -5, "end": 1000}\n')

    assert [entry["game_id"] for entry in session_log.load()] == ["ok"]


def test_an_unreadable_line_is_skipped_not_fatal():
    """Uma linha cortada pela metade (queda no meio do append) ou editada à mão
    não pode levar o resto do histórico junto."""
    session_log.record("g", 60, end=100)
    with path().open("a", encoding="utf-8") as file:
        file.write('{"game_id": "g", "end": 20\n')  # JSON truncado
        file.write("isto não é json\n")
        file.write('{"game_id": "g"}\n')  # sem os campos obrigatórios
    session_log.record("g", 120, end=300)

    assert [entry["seconds"] for entry in session_log.load("g")] == [120, 60]


def test_deleting_removes_exactly_one_line():
    """Duas sessões idênticas são registros distintos: apagar uma mantém a
    outra, ou uma noite jogada duas vezes sumiria de uma vez só."""
    session_log.record("g", 60, end=100)
    session_log.record("g", 60, end=100)
    session_log.record("g", 90, end=200)

    assert session_log.delete("g", 100, 60) is True

    assert [(e["end"], e["seconds"]) for e in session_log.load("g")] == [
        (200, 90),
        (100, 60),
    ]


def test_deleting_something_that_is_not_there_says_so():
    """Quem chama desconta o tempo do total só quando isto devolve True."""
    session_log.record("g", 60, end=100)

    assert session_log.delete("g", 999, 60) is False
    assert session_log.delete("outro", 100, 60) is False
    assert len(session_log.load("g")) == 1


def test_deleting_leaves_no_scratch_file_behind():
    session_log.record("g", 60, end=100)
    session_log.delete("g", 100, 60)

    assert not (shared.app_dir / "sessions.jsonl.tmp").exists()


@pytest.mark.parametrize(
    ("days", "expected"),
    [(7, 3600), (30, 3600 + 1800), (365, 3600 + 1800 + 600)],
)
def test_seconds_since_sums_only_the_window(days, expected):
    now = int(time())
    session_log.record("g", 3600, end=now - 86400)  # ontem
    session_log.record("g", 1800, end=now - 20 * 86400)  # 20 dias atrás
    session_log.record("g", 600, end=now - 200 * 86400)  # 200 dias atrás

    assert session_log.seconds_since(session_log.load("g"), days) == expected


# ---------------------------------------------------------------------------
# A tela do histórico
# ---------------------------------------------------------------------------


def history_game(store):
    from cartridges.game import Game

    game = Game(
        {
            "source": "imported",
            "game_id": "imported_1",
            "name": "Probe",
            "executable": "x.exe",
            "added": 0,
            "playtime": 5400,
        }
    )
    store.games_by_id[game.game_id] = game
    return game


def test_the_history_lists_one_row_per_session(real_window, store):
    from cartridges.session_history import SessionHistoryDialog

    game = history_game(store)
    session_log.record(game.game_id, 3600, end=1_700_000_000)
    session_log.record(game.game_id, 1800, end=1_700_100_000)

    dialog = SessionHistoryDialog(game)

    assert len(dialog._rows) == 2
    # Mais recente primeiro, como a lista que a alimenta
    assert dialog._rows[0].get_title() == "15 de novembro de 2023"


def cache_logo(game, width=300, height=100):
    """Grava um logo real em disco, como um fetch bem-sucedido teria feito."""
    import json

    from gi.repository import GdkPixbuf

    shared.logos_dir.mkdir(parents=True, exist_ok=True)
    path = shared.logos_dir / f"{game.game_id}.png"
    GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, width, height).savev(
        str(path), "png", [], []
    )
    (shared.logos_dir / f"{game.game_id}.json").write_text(
        json.dumps(
            {
                "name": game.name,
                "file": path.name,
                "timestamp": int(time()),
                "locked": False,
            }
        ),
        encoding="utf-8",
    )
    return path


def test_the_logo_takes_the_place_of_the_title(real_window, store):
    """O logo *é* o título quando existe: os dois nunca aparecem juntos.

    A largura tem de ser travada por fora. Um ``set_size_request`` no Picture
    é um piso, não um teto: dentro do box vertical do grupo ele recebia a
    largura inteira e crescia junto na altura — um logo de 201x72 aparecia com
    445x160, ocupando a caixa de diálogo toda.
    """
    from gi.repository import Adw, Gtk

    from cartridges.session_history import SessionHistoryDialog
    from cartridges.utils.game_logo import LOGO_MAX_HEIGHT, logo_display_size

    game = history_game(store)
    cache_logo(game, width=1280, height=458)

    dialog = SessionHistoryDialog(game)

    assert not dialog.group.get_title()
    assert dialog.logo is not None

    clamp = dialog.logo.get_parent()
    assert isinstance(clamp, Adw.Clamp)
    width = clamp.get_maximum_size()
    assert width == logo_display_size(1280, 458)[0]
    # Com a largura presa, a altura sai da proporção do próprio logo
    assert dialog.logo.measure(Gtk.Orientation.VERTICAL, width)[1] == LOGO_MAX_HEIGHT


def test_without_a_cached_logo_the_name_stays(real_window, store):
    from cartridges.session_history import SessionHistoryDialog

    dialog = SessionHistoryDialog(history_game(store))

    assert dialog.group.get_title() == "Probe"
    assert dialog.logo is None


def test_the_history_says_so_when_there_is_nothing_yet(real_window, store):
    """A biblioteca inteira antecede o histórico, então a tela vazia é o estado
    normal no começo e precisa explicar por que está vazia."""
    from cartridges.session_history import SessionHistoryDialog

    dialog = SessionHistoryDialog(history_game(store))

    assert dialog._rows == []
    assert "a partir desta versão" in dialog.group.get_description()


def test_deleting_a_session_takes_its_time_off_the_total(real_window, store):
    """O motivo de a tela existir: uma sessão que contou errado (o jogo deixado
    aberto a noite toda) só podia ser corrigida editando o total à mão."""
    from cartridges.session_history import SessionHistoryDialog

    game = history_game(store)
    session_log.record(game.game_id, 3600, end=1_700_000_000)
    session_log.record(game.game_id, 1800, end=1_700_100_000)

    dialog = SessionHistoryDialog(game)
    dialog.on_delete_response(
        None, "delete", {"end": 1_700_000_000, "seconds": 3600}
    )

    assert game.playtime == 1800
    assert len(dialog._rows) == 1


def test_dismissing_the_confirmation_changes_nothing(real_window, store):
    from cartridges.session_history import SessionHistoryDialog

    game = history_game(store)
    session_log.record(game.game_id, 3600, end=1_700_000_000)

    dialog = SessionHistoryDialog(game)
    dialog.on_delete_response(
        None, "dismiss", {"end": 1_700_000_000, "seconds": 3600}
    )

    assert game.playtime == 5400
    assert len(dialog._rows) == 1


def test_a_session_that_is_already_gone_costs_no_playtime(real_window, store):
    """A linha sumiu entre abrir a tela e confirmar. Descontar mesmo assim
    deixaria o total menor que a soma do que sobrou no histórico."""
    from cartridges.session_history import SessionHistoryDialog

    game = history_game(store)
    session_log.record(game.game_id, 3600, end=1_700_000_000)

    dialog = SessionHistoryDialog(game)
    session_log.delete(game.game_id, 1_700_000_000, 3600)
    dialog.on_delete_response(
        None, "delete", {"end": 1_700_000_000, "seconds": 3600}
    )

    assert game.playtime == 5400
    assert dialog._rows == []


def test_the_playtime_is_clickable_only_when_there_are_sessions(real_window, store):
    """O total abre a lista das sessões que o formaram — e só se elas existem.

    Um total sem sessão nenhuma é o caso comum: toda a biblioteca antes da
    primeira partida jogada por aqui, e o tempo vindo de um backup, que é um
    total sem sessões por natureza.
    """
    game = history_game(store)  # playtime de 5400 s, nenhuma sessão gravada
    label = real_window.details_view_playtime

    real_window.update_playtime_label(game)
    assert label.get_visible() is True
    assert real_window._playtime_clickable is False
    assert label.get_cursor() is None
    assert label.get_tooltip_text() is None

    session_log.record(game.game_id, 5400, end=1_700_000_000)
    real_window.update_playtime_label(game)

    assert real_window._playtime_clickable is True
    assert label.get_cursor() is not None
    assert label.get_tooltip_text() == "Ver o histórico de sessões"
    # O rótulo em si não muda: nem link, nem cor, nem sublinhado — a linha das
    # datas tem de continuar com os três itens desenhados igual.
    assert label.get_use_markup() is False
    assert label.get_text() == "Tempo de jogo: 1,5 horas"


def test_a_game_never_played_shows_no_playtime_at_all(real_window, store):
    game = history_game(store)
    game.playtime = 0

    real_window.update_playtime_label(game)

    assert real_window.details_view_playtime.get_visible() is False


def test_clicking_the_playtime_opens_the_history(real_window, store):
    game = history_game(store)
    session_log.record(game.game_id, 5400, end=1_700_000_000)
    real_window.active_game = game
    real_window.update_playtime_label(game)

    real_window.on_playtime_activated()

    assert real_window.get_visible_dialog() is not None


def test_clicking_a_total_without_sessions_opens_nothing(real_window, store):
    """O gesto fica instalado no rótulo a execução inteira, então quem decide se
    o clique vale é o jogo aberto — senão o clique abriria uma lista vazia."""
    game = history_game(store)
    real_window.active_game = game
    real_window.update_playtime_label(game)

    real_window.on_playtime_activated()

    assert real_window.get_visible_dialog() is None
