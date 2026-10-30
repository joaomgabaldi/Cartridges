# test_session_monitors.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""As opções de sessão que usam outras telas, num computador com uma tela só.

Levar a janela para outro monitor e trocar o papel de parede supõem que o jogo
roda no principal e que há mais um monitor para mostrar alguma coisa. Sem esse
segundo monitor, as duas ficam bloqueadas e desligadas — e desligadas de vez:
quando um segundo monitor volta, quem religa é o usuário.
"""

from types import SimpleNamespace

import pytest

from cartridges.utils import session_wallpaper, window_geometry

PRINCIPAL = window_geometry.Monitor("\\\\.\\DISPLAY1", 0, 0, 1920, 1080, True)
SEGUNDO = window_geometry.Monitor("\\\\.\\DISPLAY2", -1080, -512, 1080, 1920, False)
TERCEIRO = window_geometry.Monitor("\\\\.\\DISPLAY3", 1920, -512, 1080, 1920, False)


@pytest.fixture
def ligados(monkeypatch):
    """Troca os monitores que o Windows responde."""

    def trocar(*monitores):
        monkeypatch.setattr(window_geometry, "monitors", lambda: list(monitores))

    return trocar


class TestSessao:
    def test_sem_segundo_monitor_o_papel_de_parede_nao_comeca_e_desliga(
        self, schema, ligados, monkeypatch
    ):
        schema["session-wallpaper"] = True
        ligados(PRINCIPAL)
        iniciadas = []
        monkeypatch.setattr(
            session_wallpaper,
            "threading",
            SimpleNamespace(Thread=lambda **kwargs: iniciadas.append(kwargs)),
        )

        session_wallpaper.comecar(object())

        assert iniciadas == []
        assert schema.get_boolean("session-wallpaper") is False

    def test_com_segundo_monitor_o_papel_de_parede_comeca(
        self, schema, ligados, monkeypatch
    ):
        schema["session-wallpaper"] = True
        ligados(PRINCIPAL, SEGUNDO)
        iniciadas = []

        def thread(**kwargs):
            iniciadas.append(kwargs)
            return SimpleNamespace(start=lambda: None)

        monkeypatch.setattr(session_wallpaper, "threading", SimpleNamespace(Thread=thread))

        session_wallpaper.comecar(object())

        assert len(iniciadas) == 1
        assert schema.get_boolean("session-wallpaper") is True


class TestNumeracao:
    def test_conta_pela_posicao_e_nao_pelo_nome_do_dispositivo(self):
        """Depois de muitas reconexões o Windows chama as telas de DISPLAY22,
        23 e 24, mas as configurações dele continuam dizendo 1, 2 e 3."""
        telas = window_geometry.numbered(
            [
                window_geometry.Monitor("\\\\.\\DISPLAY24", 2560, -573, 1080, 1920, False),
                window_geometry.Monitor("\\\\.\\DISPLAY22", 0, 0, 2560, 1080, True),
                window_geometry.Monitor("\\\\.\\DISPLAY23", -1080, -573, 1080, 1920, False),
            ]
        )

        assert [(tela.device, tela.number) for tela in telas] == [
            ("\\\\.\\DISPLAY22", "1"),
            ("\\\\.\\DISPLAY23", "2"),
            ("\\\\.\\DISPLAY24", "3"),
        ]

    def test_nomes_trocados_entre_as_telas_nao_trocam_os_numeros(self):
        """O Windows troca os nomes DISPLAYn entre as telas (ao acordar, ao
        religar, quando o driver reinicia); a da esquerda continua sendo a 2."""
        esquerda = window_geometry.Monitor("\\\\.\\DISPLAY24", -1080, -573, 1080, 1920, False)
        direita = window_geometry.Monitor("\\\\.\\DISPLAY23", 2560, -573, 1080, 1920, False)
        principal = window_geometry.Monitor("\\\\.\\DISPLAY22", 0, 0, 2560, 1080, True)

        telas = window_geometry.numbered([direita, principal, esquerda])

        assert [(tela.x, tela.number) for tela in telas] == [(0, "1"), (-1080, "2"), (2560, "3")]

    def test_display10_vem_depois_do_display2(self):
        telas = window_geometry.numbered(
            [
                window_geometry.Monitor("\\\\.\\DISPLAY10", 0, 0, 1920, 1080, False),
                window_geometry.Monitor("\\\\.\\DISPLAY2", 0, 0, 1920, 1080, True),
            ]
        )

        assert [tela.device for tela in telas] == ["\\\\.\\DISPLAY2", "\\\\.\\DISPLAY10"]


def test_sem_a_sonda_da_janela():
    from cartridges.utils import window_geometry  # noqa: PLC0415

    for nome in ("_vigiar", "_vigiar_comecar", "_vigiar_parar", "_estado_da_janela", "_vigia_id"):
        assert not hasattr(window_geometry, nome)


def test_nada_le_as_janelas_de_outros_programas():
    """A sonda gravava no log o título da janela em primeiro plano de outros programas."""
    import inspect  # noqa: PLC0415

    from cartridges.utils import window_geometry  # noqa: PLC0415

    fonte = inspect.getsource(window_geometry)
    assert "GetForegroundWindow" not in fonte and "GetWindowTextW" not in fonte
