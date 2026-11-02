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
    session_log.record("g", 60, end=1_700_000_100)
    session_log.record("g", 60, end=1_700_000_300)
    session_log.record("g", 60, end=1_700_000_200)

    assert [entry["end"] for entry in session_log.load("g")] == [
        1_700_000_300,
        1_700_000_200,
        1_700_000_100,
    ]


def test_only_the_asked_game_comes_back():
    session_log.record("a", 60, end=1_700_000_100)
    session_log.record("b", 60, end=1_700_000_200)

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
    session_log.record("a", 60, end=1_700_001_000)
    with path().open("ab") as file:
        file.write(b'{"game_id": "b", "seconds": 1, "end": 2\xff}\n')
    session_log.record("c", 30, end=1_700_002_000)

    assert {entry["game_id"] for entry in session_log.load()} == {"a", "c"}


def test_an_out_of_range_end_costs_the_line_not_the_dialog():
    """Auditoria 26/08, B2: `end` fora da faixa do fromtimestamp do Windows
    passava no load (que só checava tipo) e derrubava o diálogo de histórico."""
    session_log.record("ok", 60, end=1_700_000_000)
    with path().open("a", encoding="utf-8") as file:
        file.write('{"game_id": "neg", "seconds": 60, "end": -1}\n')
        file.write('{"game_id": "huge", "seconds": 60, "end": 99999999999999}\n')
        file.write('{"game_id": "negsec", "seconds": -5, "end": 1000}\n')

    assert [entry["game_id"] for entry in session_log.load()] == ["ok"]


def test_an_unreadable_line_is_skipped_not_fatal():
    """Uma linha cortada pela metade (queda no meio do append) ou editada à mão
    não pode levar o resto do histórico junto."""
    session_log.record("g", 60, end=1_700_000_100)
    with path().open("a", encoding="utf-8") as file:
        file.write('{"game_id": "g", "end": 20\n')  # JSON truncado
        file.write("isto não é json\n")
        file.write('{"game_id": "g"}\n')  # sem os campos obrigatórios
    session_log.record("g", 120, end=1_700_000_300)

    assert [entry["seconds"] for entry in session_log.load("g")] == [120, 60]


def test_deleting_removes_exactly_one_line():
    """Duas sessões idênticas são registros distintos: apagar uma mantém a
    outra, ou uma noite jogada duas vezes sumiria de uma vez só."""
    session_log.record("g", 60, end=1_700_000_100)
    session_log.record("g", 60, end=1_700_000_100)
    session_log.record("g", 90, end=1_700_000_200)

    assert session_log.delete("g", 1_700_000_100, 60) is True

    assert [(e["end"], e["seconds"]) for e in session_log.load("g")] == [
        (1_700_000_200, 90),
        (1_700_000_100, 60),
    ]


def test_b17_apagar_sessao_com_byte_nao_utf8_no_arquivo():
    alheia = b'{"game_id": "caf\xe9", "end": 5, "seconds": 5}\n'
    alvo = b'{"game_id": "g", "end": 10, "seconds": 60}\n'
    path().write_bytes(alheia + alvo)

    assert session_log.delete("g", 10, 60) is True
    # O texto volta ao disco com o fim de linha do sistema; o que importa é o
    # byte não-UTF-8 da linha alheia voltar igual.
    assert path().read_bytes().replace(b"\r\n", b"\n") == alheia


def test_deleting_something_that_is_not_there_says_so():
    """Quem chama desconta o tempo do total só quando isto devolve True."""
    session_log.record("g", 60, end=1_700_000_100)

    assert session_log.delete("g", 999, 60) is False
    assert session_log.delete("outro", 100, 60) is False
    assert len(session_log.load("g")) == 1


def test_deleting_leaves_no_scratch_file_behind():
    session_log.record("g", 60, end=100)
    session_log.delete("g", 100, 60)

    assert not (shared.app_dir / "sessions.jsonl.tmp").exists()


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


def test_the_periods_end_on_the_last_day_played_and_all_starts_at_the_first_session():
    """Depois do último dia jogado só há dias vazios: num jogo zerado eles
    cresceriam para sempre."""
    from datetime import date

    from cartridges.session_history import period_range

    today = date(2026, 10, 13)
    last = date(2026, 9, 18)
    sessions = [
        {"end": local_ts(2026, 9, 18, 20), "seconds": 60},
        {"end": local_ts(2026, 3, 2, 1), "seconds": 7200},  # começou dia 1º
    ]

    assert period_range(sessions, "week", today) == (date(2026, 9, 12), last)
    assert period_range(sessions, "month", today) == (date(2026, 8, 20), last)
    assert period_range(sessions, "all", today) == (date(2026, 3, 1), last)
    # Relógio adiantado não inverte a faixa nem passa de hoje
    future = [{"end": local_ts(2027, 1, 1), "seconds": 60}]
    assert period_range(future, "all", today) == (today, today)


def test_a_session_ending_at_midnight_does_not_add_an_empty_day():
    from datetime import date

    from cartridges.session_history import period_range

    sessions = [{"end": local_ts(2026, 9, 19), "seconds": 3600}]  # 23h → 0h
    assert period_range(sessions, "all", date(2026, 10, 13)) == (
        date(2026, 9, 18),
        date(2026, 9, 18),
    )


def test_a_long_pause_becomes_a_break_and_a_short_one_stays():
    from datetime import date, timedelta

    from cartridges.session_history import LACUNA_MAXIMA, sem_lacunas_longas

    inicio = date(2025, 10, 1)

    def dias(*jogados):
        total = max(jogados) + 1
        return [(inicio + timedelta(days=i), 60 if i in jogados else 0) for i in range(total)]

    # Uma pausa curta (até LACUNA_MAXIMA dias vazios) fica inteira.
    curta = dias(0, LACUNA_MAXIMA + 1)
    assert sem_lacunas_longas(curta) == (curta, frozenset())

    # Um ano parado: ficam o primeiro e o último dia vazio, com a quebra entre eles.
    longa = dias(0, 1, 366)
    resultado, quebras = sem_lacunas_longas(longa)
    assert resultado == [longa[0], longa[1], longa[2], longa[365], longa[366]]
    assert quebras == frozenset({2})
    assert sum(s for _d, s in resultado) == sum(s for _d, s in longa)


def test_week_and_month_do_not_reach_before_the_first_session():
    """Um histórico que só começou há 2 dias não ganha dias vazios só porque
    o período escolhido é "semana" ou "mês"."""
    from datetime import date

    from cartridges.session_history import period_range

    today = date(2026, 9, 19)
    sessions = [
        {"end": local_ts(2026, 9, 17, 12), "seconds": 60},
        {"end": local_ts(2026, 9, 19, 12), "seconds": 60},
    ]

    assert period_range(sessions, "week", today) == (date(2026, 9, 17), today)
    assert period_range(sessions, "month", today) == (date(2026, 9, 17), today)


def _grava_linhas(handler, quantas):
    import logging  # noqa: PLC0415

    for i in range(quantas):
        handler.emit(logging.LogRecord("t", logging.INFO, __file__, 1, f"linha {i} " + "x" * 50, None, None))


def test_sem_limite_grava_alem_de_max_bytes(tmp_path, monkeypatch):
    from cartridges.logging.session_file_handler import SessionFileHandler  # noqa: PLC0415

    monkeypatch.setattr(SessionFileHandler, "MAX_BYTES", 500)
    handler = SessionFileHandler(tmp_path / "cartridges.log", sem_limite=True)
    try:
        _grava_linhas(handler, 100)
        assert handler.capped is False
    finally:
        handler.close()
    assert "linha 99 " in (tmp_path / "cartridges.log").read_text(encoding="utf-8")


def test_limite_continua_por_padrao(tmp_path, monkeypatch):
    from cartridges.logging.session_file_handler import SessionFileHandler  # noqa: PLC0415

    monkeypatch.setattr(SessionFileHandler, "MAX_BYTES", 500)
    handler = SessionFileHandler(tmp_path / "cartridges.log")
    try:
        _grava_linhas(handler, 100)
        assert handler.capped is True
    finally:
        handler.close()
