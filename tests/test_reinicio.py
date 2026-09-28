# test_reinicio.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O app se reabre sozinho depois de agendar uma restauração."""

import subprocess
import sys

from cartridges import main as main_module
from cartridges.utils import single_instance


def test_relancar_abre_o_mesmo_comando_desacoplado(monkeypatch):
    chamadas = []
    monkeypatch.setattr(
        main_module.subprocess, "Popen", lambda args, **kw: chamadas.append((args, kw))
    )
    main_module.relancar()
    args, kw = chamadas[0]
    assert args == [sys.executable, *sys.argv]
    assert kw["creationflags"] & subprocess.DETACHED_PROCESS
    assert kw["close_fds"] is True


def test_main_so_relanca_quando_pedido(monkeypatch):
    eventos = []

    class AppFalso:
        reiniciar = False

        def run(self, _argv):
            return 0

    app = AppFalso()
    monkeypatch.setattr(main_module, "acquire_single_instance", lambda: True)
    monkeypatch.setattr(main_module, "CartridgesApplication", lambda: app)
    monkeypatch.setattr(main_module, "release_single_instance", lambda: eventos.append("release"))
    monkeypatch.setattr(main_module, "relancar", lambda: eventos.append("relancar"))

    assert main_module.main() == 0
    assert eventos == []

    app.reiniciar = True
    main_module.main()
    # O lock sai antes: o processo novo precisa conseguir pegá-lo.
    assert eventos == ["release", "relancar"]


def test_release_sem_lock_nao_faz_nada(monkeypatch):
    monkeypatch.setattr(single_instance, "_handle", None)
    single_instance.release()
    assert single_instance._handle is None
