# apoio_abertura.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O `app.main()` de verdade sobre um `AplicacaoQt` falso: a ordem das etapas sem janela nem laço de eventos.

Não importa o `conftest` nem outro teste.
"""

from types import SimpleNamespace


class _Sinal:
    def __init__(self) -> None:
        self.ligados: list = []

    def connect(self, funcao) -> None:
        self.ligados.append(funcao)


class AppFalso:
    """O bastante do `AplicacaoQt` para o `main()`."""

    def __init__(self, *_argumentos) -> None:
        self.aboutToQuit = _Sinal()  # noqa: N815
        self.saindo = _Sinal()

    def setApplicationName(self, *_argumentos) -> None:  # noqa: N802
        pass

    setApplicationDisplayName = setWindowIcon = setApplicationName  # noqa: N815

    def screens(self) -> list:
        return []

    def exec(self) -> int:
        return 0


def preparar_main(monkeypatch, abrir, eventos: list) -> None:
    """Troca no `app` tudo o que o `main()` faria de verdade (trava, log, estilo, backup, assistente, `_abrir`, `relancar`).

    ``abrir(app, argv, abertura)`` faz o papel do `_abrir`; ``eventos`` recebe "log", "release" e "relancar".
    """
    from kyron import app as modulo_app  # noqa: PLC0415
    from kyron.utils import single_instance  # noqa: PLC0415

    monkeypatch.setattr(single_instance, "acquire", lambda: True)
    monkeypatch.setattr(single_instance, "release", lambda: eventos.append("release"))
    monkeypatch.setattr(single_instance, "watch_second_launch", lambda _avisar: None)
    monkeypatch.setattr(modulo_app, "AplicacaoQt", AppFalso)
    # O estilo dos Controls é global no processo: os testes QML seguintes não podem herdá-lo.
    monkeypatch.setattr(modulo_app, "QQuickStyle", SimpleNamespace(setStyle=lambda _estilo: None))
    monkeypatch.setattr(modulo_app, "_configurar_log", lambda: eventos.append("log"))
    monkeypatch.setattr(modulo_app, "_abrir", abrir)
    monkeypatch.setattr(modulo_app, "relancar", lambda: eventos.append("relancar"))
    monkeypatch.setattr(modulo_app.backup, "ha_pendente", lambda: False)
    monkeypatch.setattr(modulo_app.backup, "aplicar_pendente", lambda progresso=None: None)  # noqa: ARG005
    monkeypatch.setattr(modulo_app.redefinir, "aplicar_pendente", lambda: None)
    # A pasta de dados está vazia: sem isto o `main()` pararia no assistente da primeira abertura.
    monkeypatch.setattr(modulo_app.assistente, "precisa_mostrar", lambda: False)
