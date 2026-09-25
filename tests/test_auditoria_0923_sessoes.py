# test_auditoria_0923_sessoes.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Auditoria de 23/09: histórico de sessões (M4, M5, B18, B19, B20, B21, B22)."""

import json
from datetime import date, datetime, timedelta

from cartridges import shared
from cartridges.utils import session_log


def _arquivo():
    return shared.app_dir / "sessions.jsonl"


def _ts(dia: date, hora: int) -> int:
    return int(datetime.combine(dia, datetime.min.time()).timestamp()) + hora * 3600


def test_record_nao_cola_na_linha_sem_quebra_final():
    _arquivo().write_text(
        json.dumps({"game_id": "g", "end": 1_700_000_000, "seconds": 60}), encoding="utf-8"
    )
    session_log.record("g", 120, 1_700_000_500)
    sessoes = session_log.load("g")
    assert sorted(s["seconds"] for s in sessoes) == [60, 120]


def test_mover_jogo_leva_as_linhas_e_nao_toca_as_outras():
    session_log.record("velho", 60, 1_700_000_000)
    session_log.record("outro", 30, 1_700_000_100)
    session_log.mover_jogo("velho", "novo")
    assert session_log.load("velho") == []
    assert [s["seconds"] for s in session_log.load("novo")] == [60]
    assert [s["seconds"] for s in session_log.load("outro")] == [30]


def test_load_descarta_sessao_que_comeca_antes_de_1970():
    session_log.record("g", 1_758_600_000, 1_758_600_000)
    session_log.record("g", 60, 1_758_600_000)
    assert [s["seconds"] for s in session_log.load("g")] == [60]


def test_delete_sobrevive_a_linha_json_que_nao_e_objeto():
    session_log.record("g", 60, 1_700_000_000)
    with _arquivo().open("a", encoding="utf-8") as arquivo:
        arquivo.write("[1, 2]\n")
    session_log.record("g", 90, 1_700_000_900)
    assert session_log.delete("g", 1_700_000_900, 90) is True
    assert [s["seconds"] for s in session_log.load("g")] == [60]


def test_migracao_de_id_leva_as_sessoes(store, write_record):
    from cartridges.store.store import _migrate_game_files  # noqa: PLC0415

    write_record("velho", executable="x")
    session_log.record("velho", 60, 1_700_000_000)
    _migrate_game_files("velho", "novo")
    assert [s["seconds"] for s in session_log.load("novo")] == [60]
    assert session_log.load("velho") == []


def test_cleanup_game_apaga_as_sessoes(store, make_game):
    jogo = make_game(game_id="g1")
    session_log.record("g1", 60, 1_700_000_000)
    store.cleanup_game(jogo)
    assert session_log.load("g1") == []


def test_excluir_pode_preservar_as_sessoes(store, make_game):
    jogo = make_game(game_id="g2", removed=True, status="beaten")
    store.add_game(jogo, {}, run_pipeline=False)
    session_log.record("g2", 60, 1_700_000_000)
    store.excluir(jogo, apagar_sessoes=False)
    assert store.get("g2") is None
    assert [s["seconds"] for s in session_log.load("g2")] == [60]


def test_resumo_usa_os_dias_do_grafico(win):
    from cartridges.session_history import resumo_dos_ultimos_dias  # noqa: PLC0415

    hoje = date(2026, 9, 23)
    # Terminou às 20h de 16/09: fora dos 7 dias de calendário até 23/09.
    sessoes = [{"game_id": "g", "end": _ts(date(2026, 9, 16), 20), "seconds": 7200}]
    sete, trinta = resumo_dos_ultimos_dias(sessoes, hoje)
    assert sete == 0
    assert trinta == 7200


def test_zero_segundos_vira_nenhuma_sessao():
    from cartridges.session_history import tempo_ou_nenhuma  # noqa: PLC0415

    assert tempo_ou_nenhuma(0) == "nenhuma sessão"
    assert tempo_ou_nenhuma(3600) == "1 hora"


def test_tabela_mostra_100_e_carrega_mais(win, monkeypatch):
    from cartridges import session_history  # noqa: PLC0415
    from cartridges.game import Game  # noqa: PLC0415

    for indice in range(250):
        session_log.record("g", 60, 1_700_000_000 + indice * 100)
    jogo = Game({"source": "shortcuts", "game_id": "g", "name": "G", "executable": "x", "added": 0})
    dialogo = session_history.SessionHistoryDialog(jogo)
    assert len(dialogo._rows) == 100
    dialogo.mostrar_mais()
    assert len(dialogo._rows) == 200
    dialogo.mostrar_mais()
    assert len(dialogo._rows) == 250
    assert not dialogo.mais_button.get_visible()


def test_record_concorrente_com_mover_jogo_nao_perde_linha():
    """Achado 3: `record` (thread do jogo que fecha) e `mover_jogo`/`apagar_jogo`
    (threads de import/restore) mexem no mesmo arquivo. Sem uma trava em comum,
    um `record` entre o `read_text` e o `tmp.replace` de uma reescrita se
    perde, e duas reescritas concorrentes disputam o mesmo `.jsonl.tmp`."""
    import threading

    N = 200
    for i in range(N):
        session_log.record("velho", 1, 1_700_000_000 + i)

    erros = []

    def mover():
        for _ in range(50):
            session_log.mover_jogo("velho", "novo")
            session_log.mover_jogo("novo", "velho")

    def gravar():
        try:
            for i in range(N, N + N):
                session_log.record("velho", 1, 1_700_000_000 + i)
        except Exception as erro:  # pylint: disable=broad-exception-caught
            erros.append(erro)

    t1 = threading.Thread(target=mover)
    t2 = threading.Thread(target=gravar)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert erros == []
    total = len(session_log.load("velho")) + len(session_log.load("novo"))
    assert total == 2 * N
