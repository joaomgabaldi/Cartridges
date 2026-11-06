# test_updates_checker.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O verificador de atualizações, sem GLib e sem rede: o feed é sempre um falso."""

import threading
import time
from types import SimpleNamespace

from PySide6.QtCore import QEventLoop, QTimer

from kyron import shared
from kyron.modelos.avisos import FilaDeAvisos
from kyron.utils import updates_checker
from kyron.utils.updates_feed import DigestEntry, UpdatePost


def _rodar_ate(condicao, limite=5.0) -> bool:
    fim = time.monotonic() + limite
    while not condicao() and time.monotonic() < fim:
        laco = QEventLoop()
        QTimer.singleShot(10, laco.quit)
        laco.exec()
    return condicao()


def _post(*nomes: str) -> UpdatePost:
    return UpdatePost(
        identifier="p1",
        timestamp=1000,
        title="Digest",
        entries=tuple(DigestEntry(name=n, url=f"https://x/{n}") for n in nomes),
    )


def _jogo_falso(make_game, **campos):
    """O `FakeGame` da conftest (não se importa a conftest: ela roda de novo) com a regra do `has_update`."""
    base = type(make_game())

    class JogoFalso(base):
        # A regra é do `Jogo`; o falso só precisa refletir o carimbo.
        @property
        def has_update(self) -> bool:
            return self.track_updates and self.update_available_ts > 0

    return JogoFalso(**campos)


def test_aviso_de_atualizacao_vai_para_a_fila(monkeypatch, store, make_game) -> None:
    avisos = FilaDeAvisos()
    monkeypatch.setattr(shared, "aplicativo", SimpleNamespace(avisos=avisos), raising=False)
    # `&` e `<` num nome não podem ser tratados como marcação
    jogo = _jogo_falso(make_game, game_id="a", name="Tom & Jerry", track_updates=True, update_available_ts=0, update_dismissed_ts=0, update_url="")
    store.add_game(jogo, {})
    monkeypatch.setattr(updates_checker, "fetch_feed", lambda: [_post("Tom & Jerry")])

    verificador = updates_checker.UpdatesChecker()
    try:
        verificador.check_async()
        assert _rodar_ate(lambda: avisos.visivel)
    finally:
        verificador.stop()

    assert avisos.texto == "Atualização para Tom & Jerry disponível"
    assert (jogo.update_available_ts, jogo.update_url, jogo.saves, jogo.updates) == (1000, "https://x/Tom & Jerry", 1, 1)


def test_verificador_para_no_stop(monkeypatch, store, make_game) -> None:
    liberar = threading.Event()
    chamado = threading.Event()

    def travado():
        chamado.set()
        liberar.wait(10)
        return [_post("a")]

    avisos = FilaDeAvisos()
    monkeypatch.setattr(shared, "aplicativo", SimpleNamespace(avisos=avisos), raising=False)
    jogo = make_game(game_id="a", name="a", track_updates=True, update_available_ts=0, update_dismissed_ts=0, update_url="")
    store.add_game(jogo, {})
    monkeypatch.setattr(updates_checker, "fetch_feed", travado)
    shared.schema.set_int("updates-check-interval", 12)

    verificador = updates_checker.UpdatesChecker()
    verificador.start()
    assert chamado.wait(5)
    inicio = time.monotonic()
    verificador.stop()
    assert time.monotonic() - inicio < 1
    assert verificador._timer is None  # noqa: SLF001

    liberar.set()
    _rodar_ate(lambda: False, 0.3)
    # O resultado que chega depois do `stop` é descartado
    assert not avisos.visivel and jogo.saves == 0


def test_intervalo_enorme_nao_estoura_o_temporizador(monkeypatch) -> None:
    """`threading.Timer` recusa mais que `TIMEOUT_MAX`: a chave vai até 2147483647 horas."""
    shared.schema.set_int("updates-check-interval", 2147483647)
    verificador = updates_checker.UpdatesChecker()
    try:
        verificador._armar()  # noqa: SLF001
        assert verificador._timer.interval == threading.TIMEOUT_MAX  # noqa: SLF001
        assert verificador._timer.is_alive()
    finally:
        verificador._cancelar_timer()  # noqa: SLF001
