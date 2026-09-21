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


def lay_out(dialog, width=1040):
    """Aloca o conteúdo como a caixa de diálogo faz: largura fixa, altura
    natural (a caixa não tem altura fixa, segue a tabela)."""
    from gi.repository import Gdk, Gtk

    content = dialog.get_child()
    rect = Gdk.Rectangle()
    rect.x, rect.y = 0, 0
    rect.width = width
    rect.height = content.measure(Gtk.Orientation.VERTICAL, width)[1]
    content.size_allocate(rect, -1)
    return content


def bounds(widget, content):
    ok, rect = widget.compute_bounds(content)
    assert ok
    return rect


@pytest.mark.parametrize(
    ("source", "shown"),
    [
        # 5,2:1, como o do Dawnwalker: manda o teto de altura (120).
        ((2858, 552), (621, 120)),
        # 10:1: a altura de 120 daria 1200 de largura; manda a largura útil
        # da caixa (1040 menos as margens de 24). 992 / 10 = 99,2 de altura,
        # que a medida do GTK arredonda para cima.
        ((4000, 400), (992, 100)),
    ],
)
def test_the_logo_takes_the_place_of_the_title(real_window, store, source, shown):
    """O logo *é* o título quando existe: os dois nunca aparecem juntos.

    A largura é travada por fora, pelo clamp: um ``set_size_request`` no
    Picture é piso, não teto, e ele cresceria junto na altura. A altura sai da
    proporção do próprio logo — nunca esticado.
    """
    from gi.repository import Adw, Gtk

    from cartridges.session_history import SessionHistoryDialog

    game = history_game(store)
    cache_logo(game, width=source[0], height=source[1])

    dialog = SessionHistoryDialog(game)

    assert dialog.name_label is None
    clamp = dialog.logo.get_parent()
    assert isinstance(clamp, Adw.Clamp)
    assert clamp.get_maximum_size() == shown[0]
    assert dialog.logo.measure(Gtk.Orientation.VERTICAL, shown[0])[1] == shown[1]


def test_without_a_cached_logo_the_name_is_the_title(real_window, store):
    from cartridges.session_history import SessionHistoryDialog

    dialog = SessionHistoryDialog(history_game(store))

    assert dialog.logo is None
    assert dialog.name_label.get_label() == "Probe"


def test_the_header_bar_shows_no_title_but_the_dialog_keeps_its_name(
    real_window, store
):
    """O logo abre a tela logo abaixo da barra, e um título ali ficava colado
    nele. Só a barra deixa de mostrar: o diálogo continua com nome, que é o
    da janela e o que o leitor de tela anuncia."""
    from gi.repository import Adw

    from cartridges.session_history import SessionHistoryDialog

    dialog = SessionHistoryDialog(history_game(store))

    def header_bars(widget):
        if isinstance(widget, Adw.HeaderBar):
            yield widget
        child = widget.get_first_child()
        while child is not None:
            yield from header_bars(child)
            child = child.get_next_sibling()

    (bar,) = header_bars(dialog.get_child())
    assert bar.get_show_title() is False
    assert dialog.get_title() == "Histórico de sessões"


def test_the_logo_and_the_summary_span_the_whole_dialog(real_window, store):
    """Logo e resumo ficam numa faixa própria, centralizados na largura toda,
    acima das duas colunas — e não em cima só da tabela."""
    from cartridges.session_history import SessionHistoryDialog

    game = history_game(store)
    cache_logo(game, width=2858, height=552)
    session_log.record(game.game_id, 3600, end=int(time()))

    dialog = SessionHistoryDialog(game)
    content = lay_out(dialog)

    for widget in (dialog.logo, dialog.summary):
        rect = bounds(widget, content)
        assert abs(rect.get_x() + rect.get_width() / 2 - 520) <= 1
    assert dialog.summary.get_label().startswith("Últimos 7 dias")

    summary = bounds(dialog.summary, content)
    columns_top = bounds(dialog.columns, content).get_y()
    assert summary.get_y() + summary.get_height() <= columns_top


def test_the_history_says_so_when_there_is_nothing_yet(real_window, store):
    """A biblioteca inteira antecede o histórico, então a tela vazia é o estado
    normal no começo e precisa explicar por que está vazia."""
    from cartridges.session_history import SessionHistoryDialog

    dialog = SessionHistoryDialog(history_game(store))

    assert dialog._rows == []
    assert dialog.summary.get_label() == "Nenhuma sessão registrada."
    assert dialog.columns.get_visible() is False


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


# -- Gráfico de horas por dia ----------------------------------------------------


def local_ts(*args):
    from datetime import datetime

    return int(datetime(*args).timestamp())


def test_a_session_across_midnight_is_split_between_the_two_days():
    from datetime import date

    # 23h às 1h: uma hora em cada dia, e não duas no dia em que terminou.
    sessions = [{"end": local_ts(2026, 9, 11, 1), "seconds": 7200}]

    assert session_log.daily_seconds(
        sessions, date(2026, 9, 9), date(2026, 9, 11)
    ) == [
        (date(2026, 9, 9), 0),
        (date(2026, 9, 10), 3600),
        (date(2026, 9, 11), 3600),
    ]


def test_only_the_part_of_a_session_inside_the_range_counts():
    from datetime import date

    # Começou antes da faixa (dia 9, 22h) e termina dentro dela (dia 10, 2h).
    sessions = [{"end": local_ts(2026, 9, 10, 2), "seconds": 4 * 3600}]

    assert session_log.daily_seconds(sessions, date(2026, 9, 10), date(2026, 9, 10)) == [
        (date(2026, 9, 10), 2 * 3600)
    ]


def test_an_inverted_range_has_no_days():
    from datetime import date

    assert session_log.daily_seconds([], date(2026, 9, 10), date(2026, 9, 9)) == []


def test_the_periods_end_today_and_all_starts_at_the_first_session():
    from datetime import date

    from cartridges.session_history import period_range

    today = date(2026, 9, 19)
    sessions = [
        {"end": local_ts(2026, 9, 18, 20), "seconds": 60},
        {"end": local_ts(2026, 3, 2, 1), "seconds": 7200},  # começou dia 1º
    ]

    assert period_range(sessions, "week", today) == (date(2026, 9, 13), today)
    assert period_range(sessions, "month", today) == (date(2026, 8, 21), today)
    assert period_range(sessions, "all", today) == (date(2026, 3, 1), today)
    # Relógio adiantado não inverte a faixa
    future = [{"end": local_ts(2027, 1, 1), "seconds": 60}]
    assert period_range(future, "all", today) == (today, today)


def test_week_and_month_do_not_reach_before_the_first_session():
    """Um histórico que só começou há 2 dias não ganha dias vazios só porque
    o período escolhido é "semana" ou "mês"."""
    from datetime import date

    from cartridges.session_history import period_range

    today = date(2026, 9, 19)
    sessions = [{"end": local_ts(2026, 9, 17, 12), "seconds": 60}]

    assert period_range(sessions, "week", today) == (date(2026, 9, 17), today)
    assert period_range(sessions, "month", today) == (date(2026, 9, 17), today)


def test_the_x_axis_labels_the_first_and_last_day_without_crowding():
    from datetime import date, timedelta

    from cartridges.session_history import PlaytimeChart

    chart = PlaytimeChart()
    for count in (1, 2, 7, 30, 31, 61):
        chart.days = [(date(2026, 1, 1) + timedelta(days=i), 0) for i in range(count)]
        labeled = chart.labeled_indices()
        assert labeled[0] == 0 and labeled[-1] == count - 1
        assert len(labeled) <= 7
        assert labeled == sorted(set(labeled))

    # Por mês: só dias 1º, então nenhum mês aparece duas vezes.
    chart.days = [(date(2026, 1, 15) + timedelta(days=i), 0) for i in range(400)]
    labels = [chart._label_for(chart.days[i][0]) for i in chart.labeled_indices()]
    assert all(chart.days[i][0].day == 1 for i in chart.labeled_indices())
    assert len(labels) == len(set(labels)) <= 7


def test_the_chart_follows_the_period_and_hides_without_sessions(real_window, store):
    import cairo

    from cartridges.session_history import SessionHistoryDialog

    game = history_game(store)
    dialog = SessionHistoryDialog(game)
    assert dialog.columns.get_visible() is False

    session_log.record(game.game_id, 3600)
    # Uma sessão antiga também: sem ela, a única sessão (de hoje) seria a
    # primeira já registrada, e o corte de dias vazios reduziria a faixa a 1
    # dia — o que este teste é sobre é a troca de período, não o corte.
    session_log.record(game.game_id, 60, end=int(time()) - 100 * 86400)
    dialog.rebuild()
    assert dialog.columns.get_visible() is True
    assert len(dialog.chart.days) == 30
    assert dialog.chart_total.get_label() == "1 hora no período"

    dialog.period.set_active_name("week")
    assert len(dialog.chart.days) == 7

    # Desenhar num surface de verdade: os três períodos, sem exceção.
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 500, 300)
    for period in ("week", "month", "all"):
        dialog.period.set_active_name(period)
        dialog.chart.draw(None, cairo.Context(surface), 500, 300)


def history_with_sessions(store, count):
    from cartridges.session_history import SessionHistoryDialog

    game = history_game(store)
    for i in range(count):
        session_log.record(game.game_id, 3600, end=int(time()) - i * 86400)
    return SessionHistoryDialog(game)


def test_the_chart_panel_is_as_tall_as_the_table(real_window, store):
    """O painel inteiro — seletor de período, total e desenho — ocupa a mesma
    faixa vertical da tabela: começa e termina junto com ela."""
    dialog = history_with_sessions(store, 7)
    content = lay_out(dialog)

    table = bounds(dialog.table, content)
    panel = bounds(dialog.chart_panel, content)
    assert panel.get_y() == table.get_y()
    assert panel.get_height() == table.get_height()


def test_a_long_table_scrolls_and_the_panel_stops_with_it(real_window, store):
    """Passou de ~8 linhas, a tabela rola dentro da faixa em vez de esticar a
    caixa de diálogo, e o painel do gráfico para na mesma altura."""
    from gi.repository import Gtk

    dialog = history_with_sessions(store, 30)
    content = lay_out(dialog)

    visible = bounds(dialog.table.get_ancestor(Gtk.ScrolledWindow), content)
    assert visible.get_height() <= 440
    assert dialog.table.measure(Gtk.Orientation.VERTICAL, -1)[1] > visible.get_height()
    assert bounds(dialog.chart_panel, content).get_height() == visible.get_height()


def test_with_one_session_the_chart_keeps_a_readable_height(real_window, store):
    """Uma tabela de uma linha não arrasta o gráfico junto: ele fica no piso
    legível, e a tabela fica mais baixa que o painel, sem esticar o fundo."""
    dialog = history_with_sessions(store, 1)
    content = lay_out(dialog)

    assert bounds(dialog.chart, content).get_height() >= 240
    table = bounds(dialog.table, content)
    assert table.get_height() < bounds(dialog.chart_panel, content).get_height()


def test_the_playtime_is_underlined_only_when_it_opens_something(real_window, store):
    game = history_game(store)
    real_window.update_playtime_label(game)
    assert not real_window.details_view_playtime.has_css_class("playtime-clickable")

    session_log.record(game.game_id, 5400, end=1_700_000_000)
    real_window.update_playtime_label(game)
    assert real_window.details_view_playtime.has_css_class("playtime-clickable")
