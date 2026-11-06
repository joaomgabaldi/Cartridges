# test_aplicativo.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O `Aplicativo`: preferências que o QML acompanha."""

import pytest


def test_animacoes_do_sistema_le_o_ajuste_do_windows(monkeypatch):
    import ctypes
    from types import SimpleNamespace

    from kyron import aplicativo as modulo

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



@pytest.mark.parametrize("ligado", [True, False])
def test_mudar_o_autoplay_so_reavalia_o_que_toca(app_qt, monkeypatch, ligado):  # noqa: ARG001
    """As cópias são preparadas com a opção ligada ou não: o "Animar capas" não mexe na tarefa, só no que toca."""
    from kyron import shared  # noqa: PLC0415
    from kyron.aplicativo import Aplicativo  # noqa: PLC0415
    from kyron.utils import copias_animadas  # noqa: PLC0415

    chamadas = []
    monkeypatch.setattr(copias_animadas, "preparar", chamadas.append)
    monkeypatch.setattr(copias_animadas, "encerrar", lambda: chamadas.append("encerrar"))
    shared.schema.set_boolean("cover-autoplay", not ligado)
    aplicativo = Aplicativo()
    avisos = []
    aplicativo.tocarSempreChanged.connect(lambda: avisos.append(aplicativo.tocarSempre))
    shared.schema.set_boolean("cover-autoplay", ligado)
    assert avisos == [ligado]
    assert chamadas == []


def test_a_ligacao_do_autoplay_e_desfeita_ao_destruir_a_janela(app_qt):  # noqa: ARG001
    """A ligação ao `changed::cover-autoplay` não prende o `Aplicativo` nem chama um destruído."""
    import gc  # noqa: PLC0415
    import weakref  # noqa: PLC0415

    from kyron import shared  # noqa: PLC0415
    from kyron.aplicativo import Aplicativo  # noqa: PLC0415

    referencia = weakref.ref(Aplicativo())
    gc.collect()
    assert referencia() is None
    shared.schema.set_boolean("cover-autoplay", not shared.schema.get_boolean("cover-autoplay"))  # não levanta
