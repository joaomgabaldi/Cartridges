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


def test_preferencias_bloqueiam_a_fita_sem_configuracao(monkeypatch, schema):
    """Sem fita configurada não há o que ligar, e a tela diz isso."""
    schema.set_boolean("session-fita", True)

    preferencias = _preferencias(monkeypatch)

    assert preferencias.session_fita_switch.get_sensitive() is False
    assert preferencias.session_fita_switch.get_subtitle() == "Nenhum dispositivo configurado"
    assert schema.get_boolean("session-fita") is False


def test_preferencias_liberam_a_fita_e_contam_as_configuradas(monkeypatch, schema):
    """Com fita gravada o interruptor responde, e o subtítulo diz quantas são."""
    session_fita.gravar_fitas(
        [
            session_fita.Fita("Centro", "eb0", "192.168.0.150", "chave"),
            session_fita.Fita("Direita", "eb1", "192.168.0.151", "chave"),
        ]
    )

    preferencias = _preferencias(monkeypatch)

    assert preferencias.session_fita_switch.get_sensitive() is True
    assert preferencias.session_fita_switch.get_subtitle() == "2 dispositivos configurados"


def test_ligar_o_interruptor_arranca_o_ciclo(monkeypatch, schema):
    """Ligar com o app aberto tem de guardar o estado de antes na hora.

    Sem isto, o ciclo só arrancaria no arranque seguinte: a chave
    ``fita-estado-anterior`` ficaria vazia, a sessão seguinte vestiria a cor do
    jogo e o fechamento não teria o que devolver.
    """
    session_fita.gravar_fitas([session_fita.Fita("Centro", "eb0", "1.2.3.4", "k")])
    chamadas = []
    monkeypatch.setattr(session_fita, "reacender", lambda: chamadas.append("reacender"))

    preferencias = _preferencias(monkeypatch)
    assert chamadas == []

    preferencias.session_fita_switch.set_active(True)
    assert chamadas == ["reacender"]

    # Desligar não desfaz nada aqui: quem devolve as fitas é o fechamento.
    preferencias.session_fita_switch.set_active(False)
    assert chamadas == ["reacender"]


def test_abrir_a_tela_com_o_recurso_ligado_nao_arranca(monkeypatch, schema):
    """Abrir as Preferências não é ligar o recurso: construir a tela não acende.

    O ``bind`` do dublê de schema não faz nada, e é justamente ele que acende o
    interruptor no meio do ``__init__``. Imitado aqui para que a construção
    passe pelo mesmo ``notify::active`` do app de verdade — é o que torna este
    teste capaz de pegar um handler ligado cedo demais.
    """
    session_fita.gravar_fitas([session_fita.Fita("Centro", "eb0", "1.2.3.4", "k")])
    schema.set_boolean("session-fita", True)
    monkeypatch.setattr(
        schema,
        "bind",
        lambda chave, widget, prop, _flags: widget.set_property(
            prop, schema.get_boolean(chave)
        ),
    )
    chamadas = []
    monkeypatch.setattr(session_fita, "reacender", lambda: chamadas.append("reacender"))

    preferencias = _preferencias(monkeypatch)

    assert preferencias.session_fita_switch.get_active() is True
    assert chamadas == []


def test_ligar_grava_a_chave_antes_de_arrancar(monkeypatch, schema):
    """A chave tem de estar gravada quando o ``reacender`` roda, e não depois.

    ``reacender`` decide pela chave, via ``ligada()``, e não pelo widget. Deixar
    isso por conta do ``bind`` do GSettings amarraria o recurso à ordem em que
    os handlers foram conectados: invertida, o ciclo não armaria, em silêncio.
    O dublê lê a chave no momento da chamada, que é o instante que importa.
    """
    session_fita.gravar_fitas([session_fita.Fita("Centro", "eb0", "1.2.3.4", "k")])
    vista = []
    monkeypatch.setattr(
        session_fita, "reacender", lambda: vista.append(schema.get_boolean("session-fita"))
    )

    preferencias = _preferencias(monkeypatch)
    preferencias.session_fita_switch.set_active(True)

    assert vista == [True]


def test_o_teste_nao_escreve_em_tela_ja_fechada(monkeypatch, schema):
    """O resultado do "Testar" volta pelo ``idle_add``, e a tela pode ter ido.

    Com o diálogo fechado no meio da conversa com as fitas, o que volta não tem
    onde escrever — e o subtítulo fica no "Testando…" que o clique deixou.

    A thread e o ``idle_add`` são capturados em vez de rodados, como no
    ``test_abrir_nao_faz_rede_na_thread_de_ui``: o que se prova aqui é o que a
    volta faz, e rodar o laço principal de verdade não acrescentaria nada.
    """
    import cartridges.preferences as preferences_module  # noqa: PLC0415

    session_fita.gravar_fitas([session_fita.Fita("Centro", "eb0", "1.2.3.4", "k")])
    monkeypatch.setattr(session_fita, "aplicar", lambda *_args: True)
    monkeypatch.setattr(
        preferences_module,
        "threading",
        # `Event` de verdade: é o sinal de parada do teste, e trocá-lo por um
        # dublê esconderia justamente o botão que vira "parar".
        SimpleNamespace(
            Thread=lambda target, daemon: SimpleNamespace(start=target),
            Event=threading.Event,
        ),
    )
    agendadas = []
    monkeypatch.setattr(
        preferences_module.GLib,
        "idle_add",
        lambda funcao, *args, **_kw: agendadas.append((funcao, args)),
    )
    preferencias = _preferencias(monkeypatch)

    preferencias.testar_fitas()
    assert preferencias.fita_testar_row.get_subtitle() == "Testando…"
    volta, argumentos = agendadas.pop()
    volta(*argumentos)
    assert preferencias.fita_testar_row.get_subtitle() == "Teste concluído"

    preferencias.testar_fitas()
    monkeypatch.setattr(preferences_module.CartridgesPreferences, "is_open", False)
    volta, argumentos = agendadas.pop()

    assert volta(*argumentos) is False
    assert preferencias.fita_testar_row.get_subtitle() == "Testando…"


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


def test_cor_vai_e_volta_entre_o_seletor_e_o_modulo():
    from gi.repository import Gdk  # noqa: PLC0415

    original = session_fita.Cor(340, 1000, 150)
    rgba = session_fita.cor_para_rgba(original)
    assert isinstance(rgba, Gdk.RGBA)

    volta = session_fita.rgba_para_cor(rgba, 150)
    # Matiz e saturação sobrevivem à ida e à volta, com folga de arredondamento.
    assert abs(volta.matiz - original.matiz) <= 2
    assert abs(volta.saturacao - original.saturacao) <= 10
    assert volta.brilho == 150


def test_escolher_a_cor_do_app_nas_preferencias_grava_e_mostra(monkeypatch, schema):
    """Sem botão de aplicar: as Preferências gravam na hora, e a fita acompanha."""
    import cartridges.preferences as preferences_module  # noqa: PLC0415
    from cartridges.metadata_refresh import MetadataRefresh  # noqa: PLC0415

    monkeypatch.setattr(preferences_module, "get_metadata_refresh", MetadataRefresh)
    pedidas = []
    monkeypatch.setattr(session_fita, "previa", pedidas.append)
    preferencias = preferences_module.CartridgesPreferences()

    # Abrir a tela não conta como escolha.
    assert session_fita.tom_do_app() == session_fita.ROXO_DO_APP
    assert not preferencias.fita_cor_app_reset.get_visible()
    assert pedidas == []

    preferencias.fita_cor_app_seletor.set_property(
        "rgba", session_fita.cor_para_rgba(session_fita.Cor(210, 1000, 0))
    )

    matiz, saturacao = session_fita.tom_do_app()
    assert abs(matiz - 210) <= 2
    assert abs(saturacao - 1000) <= 10
    assert preferencias.fita_cor_app_reset.get_visible()
    assert pedidas

    preferencias.voltar_ao_roxo()

    assert session_fita.tom_do_app() == session_fita.ROXO_DO_APP
    assert not preferencias.fita_cor_app_reset.get_visible()


def test_interruptor_da_tela_segue_o_da_iluminacao(monkeypatch, schema):
    _com_fita()
    monkeypatch.setattr(session_fita, "reacender", lambda: None)
    preferencias = _preferencias(monkeypatch)
    linha = preferencias.fita_acompanha_tela_switch
    assert linha.get_title() == "Cor acompanha a tela do jogo"
    assert linha.get_subtitle() == (
        "A cor da iluminação acompanha, devagar, a cor predominante do jogo. "
        "Jogos com cor escolhida manualmente mantêm a cor fixa."
    )
    preferencias.session_fita_switch.set_active(False)
    assert linha.get_sensitive() is False
    preferencias.session_fita_switch.set_active(True)
    assert linha.get_sensitive() is True


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
