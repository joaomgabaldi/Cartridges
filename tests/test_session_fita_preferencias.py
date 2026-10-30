# test_session_fita_preferencias.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""As fitas de LED nas Preferências e no assistente: ainda GTK, saem no plano 7.

Vieram do `test_session_fita.py` na Task 5 do plano 5, sem mudança. Ficam no `TESTES_AINDA_GTK`.
"""

import pytest

from cartridges import shared
from cartridges.utils import session_fita
from tests.apoio_fita import cor_mandada, falsas, pastas, sem_fade, sem_vigia  # noqa: F401


def _preferencias(monkeypatch):
    """A tela de Preferências de verdade, como em ``test_session_monitors``."""
    import cartridges.preferences as preferences_module  # noqa: PLC0415
    from cartridges.metadata_refresh import MetadataRefresh  # noqa: PLC0415

    monkeypatch.setattr(preferences_module, "get_metadata_refresh", MetadataRefresh)
    return preferences_module.CartridgesPreferences()














def test_fechar_o_assistente_com_fita_nova_arranca_o_ciclo(monkeypatch, schema):
    """Configurar a primeira fita com o recurso já ligado também arranca."""
    schema.set_boolean("session-fita", True)
    chamadas = []
    monkeypatch.setattr(session_fita, "reacender", lambda: chamadas.append("reacender"))

    preferencias = _preferencias(monkeypatch)
    # Sem fita, `atualizar_fitas` desligou a chave: não há o que arrancar.
    preferencias.fitas_configuradas()
    assert chamadas == []

    session_fita.gravar_fitas([session_fita.Fita("Centro", "eb0", "1.2.3.4", "k")])
    schema.set_boolean("session-fita", True)
    preferencias.fitas_configuradas()

    assert chamadas == ["reacender"]
    assert preferencias.session_fita_switch.get_sensitive() is True


def _com_fita():
    session_fita.gravar_fitas([session_fita.Fita("Centro", "eb0", "192.168.0.150", "chave")])


def _linhas_do_pulso(preferencias):
    return (
        preferencias.conquistas_pulso_cor_row,
        preferencias.conquistas_pulso_estilo_row,
        preferencias.conquistas_pulso_testar_row,
    )


def test_linhas_do_pulso_desativadas_sem_iluminacao(monkeypatch, schema):
    """Com o piscar ligado, as linhas seguem o interruptor das fitas."""
    _com_fita()
    monkeypatch.setattr(session_fita, "reacender", lambda: None)
    preferencias = _preferencias(monkeypatch)
    # O `bind` do schema é falso nos testes: os interruptores se ligam à mão.
    preferencias.conquistas_iluminacao_switch.set_active(True)
    assert not preferencias.session_fita_switch.get_active()
    assert [linha.get_sensitive() for linha in _linhas_do_pulso(preferencias)] == [False] * 3

    preferencias.session_fita_switch.set_active(True)
    assert [linha.get_sensitive() for linha in _linhas_do_pulso(preferencias)] == [True] * 3

    preferencias.session_fita_switch.set_active(False)
    assert [linha.get_sensitive() for linha in _linhas_do_pulso(preferencias)] == [False] * 3


def test_linhas_do_pulso_desativadas_sem_piscar(monkeypatch, schema):
    _com_fita()
    schema.set_boolean("conquistas-iluminacao", False)
    monkeypatch.setattr(session_fita, "reacender", lambda: None)
    preferencias = _preferencias(monkeypatch)
    # O `bind` do schema é falso nos testes e não preenche os interruptores:
    # liga-se o das fitas à mão, como o usuário faria.
    preferencias.session_fita_switch.set_active(True)
    assert preferencias.conquistas_pulso_testar_row.get_sensitive() is False
    preferencias.conquistas_iluminacao_switch.set_active(True)
    assert preferencias.conquistas_pulso_testar_row.get_sensitive() is True


def test_estilo_do_pulso_gravado_pela_lista(monkeypatch, schema):
    _com_fita()
    preferencias = _preferencias(monkeypatch)
    assert preferencias.conquistas_pulso_estilo_row.get_selected() == 1  # Respirar, o padrão
    preferencias.conquistas_pulso_estilo_row.set_selected(2)
    assert schema.get_string("conquistas-pulso-estilo") == "rapido"


def test_estilo_e_cor_gravados_sao_lidos_ao_abrir(monkeypatch, schema):
    _com_fita()
    schema.set_string("conquistas-pulso-estilo", "longo")
    session_fita.salvar_tom_do_pulso(200, 800)
    preferencias = _preferencias(monkeypatch)
    assert preferencias.conquistas_pulso_estilo_row.get_selected() == 3
    assert preferencias.conquistas_pulso_cor_reset.get_visible() is True
    # Ler o que está gravado não regrava nada nem acende as fitas.
    assert schema.get_string("conquistas-pulso-estilo") == "longo"
    assert session_fita.tom_do_pulso() == (200, 800)


def test_cor_do_pulso_gravada_e_voltar_ao_padrao(monkeypatch, schema):
    _com_fita()
    preferencias = _preferencias(monkeypatch)
    assert preferencias.conquistas_pulso_cor_reset.get_visible() is False
    preferencias.conquistas_pulso_cor_seletor.set_property(
        "rgba", session_fita.cor_para_rgba(session_fita.Cor(200, 800, session_fita.BRILHO_CHEIO))
    )
    assert session_fita.tom_do_pulso() != session_fita.TOM_DO_OURO
    assert preferencias.conquistas_pulso_cor_reset.get_visible() is True
    preferencias.conquistas_pulso_cor_reset.emit("clicked")
    assert session_fita.tom_do_pulso() == session_fita.TOM_DO_OURO
    assert preferencias.conquistas_pulso_cor_reset.get_visible() is False


def test_fechar_o_balao_volta_a_cor_do_app(monkeypatch, schema):
    _com_fita()
    previas = []
    monkeypatch.setattr(session_fita, "previa", lambda cor, *_a: previas.append(cor))
    preferencias = _preferencias(monkeypatch)
    preferencias._abrir_balao_do_pulso()  # o "show" do Popover real precisa de janela
    preferencias.conquistas_pulso_cor_seletor.set_property(
        "rgba", session_fita.cor_para_rgba(session_fita.Cor(200, 800, session_fita.BRILHO_CHEIO))
    )
    assert previas[-1] == session_fita.cor_do_pulso()
    preferencias.conquistas_pulso_cor_balao.emit("closed")
    assert previas[-1] == session_fita.cor_do_app()


def test_abrir_o_balao_mostra_a_cor_do_pulso_nas_fitas(monkeypatch, schema):
    _com_fita()
    session_fita.salvar_tom_do_pulso(200, 800)
    previas = []
    monkeypatch.setattr(session_fita, "previa", lambda cor, *_a: previas.append(cor))
    preferencias = _preferencias(monkeypatch)
    assert previas == []  # abrir as Preferências não acende fita nenhuma

    preferencias._abrir_balao_do_pulso()  # o "show" do Popover real precisa de janela
    assert previas == [session_fita.cor_do_pulso()]


def test_voltar_ao_padrao_com_o_balao_fechado_nao_deixa_previa(monkeypatch, schema):
    """O botão fica fora do balão: sem balão aberto, não há prévia a mostrar."""
    _com_fita()
    session_fita.salvar_tom_do_pulso(200, 800)
    previas = []
    monkeypatch.setattr(session_fita, "previa", lambda cor, *_a: previas.append(cor))
    preferencias = _preferencias(monkeypatch)

    preferencias.conquistas_pulso_cor_reset.emit("clicked")

    assert session_fita.tom_do_pulso() == session_fita.TOM_DO_OURO
    assert previas == []


def test_testar_o_pulso_chama_o_teste(monkeypatch, schema):
    _com_fita()
    chamadas = []
    monkeypatch.setattr(session_fita, "testar_pulso", lambda: chamadas.append("teste"))
    preferencias = _preferencias(monkeypatch)
    preferencias.conquistas_pulso_testar_row.emit("activated")
    assert chamadas == ["teste"]


def test_a_lista_de_estilos_da_tela_cobre_todos_os_estilos():
    import cartridges.preferences as preferences_module  # noqa: PLC0415

    assert set(preferences_module.ESTILOS_NA_TELA) == set(session_fita.ESTILOS_DO_PULSO)








def test_linha_da_calibracao_segue_o_interruptor_da_iluminacao(monkeypatch, schema):
    _com_fita()
    monkeypatch.setattr(session_fita, "reacender", lambda: None)
    preferencias = _preferencias(monkeypatch)
    linha = preferencias.fita_calibrar_row
    assert linha.get_title() == "Calibrar as cores"
    assert linha.get_subtitle() == "Ajusta cada dispositivo para reproduzir as cores como a tela"
    preferencias.session_fita_switch.set_active(False)
    assert linha.get_sensitive() is False
    preferencias.session_fita_switch.set_active(True)
    assert linha.get_sensitive() is True


def test_botao_da_calibracao_abre_o_assistente(monkeypatch, schema):
    import cartridges.preferences as preferences_module  # noqa: PLC0415

    _com_fita()
    monkeypatch.setattr(session_fita, "reacender", lambda: None)
    preferencias = _preferencias(monkeypatch)
    abertos = []

    class Espiao:
        def __init__(self, configuradas):
            abertos.append([fita.id for fita in configuradas])

        def present(self, _pai):
            abertos.append("apresentado")

    monkeypatch.setattr(preferences_module, "AssistenteDeCalibracao", Espiao)
    preferencias.fita_calibrar_button.emit("clicked")
    assert abertos == [["eb0"], "apresentado"]
