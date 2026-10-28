# test_aplicativo.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O `Aplicativo`: preferências que o QML acompanha."""


def test_animacoes_do_sistema_le_o_ajuste_do_windows(monkeypatch):
    import ctypes
    from types import SimpleNamespace

    from cartridges import aplicativo as modulo

    def falso(valor, sucesso=1):
        def spi(acao, _p1, ponteiro, _p2):
            assert acao == 0x1042
            ponteiro.contents.value = valor
            return sucesso
        return SimpleNamespace(user32=SimpleNamespace(SystemParametersInfoW=spi))

    monkeypatch.setattr(ctypes, "windll", falso(0), raising=False)
    assert modulo._animacoes_do_sistema() is False
    monkeypatch.setattr(ctypes, "windll", falso(1), raising=False)
    assert modulo._animacoes_do_sistema() is True
    monkeypatch.setattr(ctypes, "windll", falso(0, sucesso=0), raising=False)
    assert modulo._animacoes_do_sistema() is True, "sem resposta do sistema, anima como antes"
