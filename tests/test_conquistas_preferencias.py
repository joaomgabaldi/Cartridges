"""A página Conquistas das Preferências."""


def _preferencias(monkeypatch):
    import cartridges.preferences as preferences_module  # noqa: PLC0415
    from cartridges.metadata_refresh import MetadataRefresh  # noqa: PLC0415

    monkeypatch.setattr(preferences_module, "get_metadata_refresh", MetadataRefresh)
    return preferences_module.CartridgesPreferences()


def test_chave_digitada_vai_para_o_schema(monkeypatch, schema):
    preferencias = _preferencias(monkeypatch)
    preferencias.conquistas_chave_row.set_text("  abc123  ")
    assert schema.get_string("conquistas-chave-steam") == "abc123"


def test_chave_guardada_aparece_na_linha(monkeypatch, schema):
    schema.set_string("conquistas-chave-steam", "xyz")
    preferencias = _preferencias(monkeypatch)
    assert preferencias.conquistas_chave_row.get_text() == "xyz"


def test_posicao_escolhida_vai_para_o_schema(monkeypatch, schema):
    preferencias = _preferencias(monkeypatch)
    preferencias.conquistas_posicao_row.set_selected(0)
    assert schema.get_string("conquistas-aviso-posicao") == "superior-esquerdo"
    preferencias.conquistas_posicao_row.set_selected(3)
    assert schema.get_string("conquistas-aviso-posicao") == "inferior-direito"


def test_posicao_guardada_aparece_na_linha(monkeypatch, schema):
    schema.set_string("conquistas-aviso-posicao", "superior-direito")
    preferencias = _preferencias(monkeypatch)
    assert preferencias.conquistas_posicao_row.get_selected() == 1


def test_posicao_estranha_no_schema_cai_no_padrao(monkeypatch, schema):
    schema.set_string("conquistas-aviso-posicao", "meio")
    preferencias = _preferencias(monkeypatch)
    assert preferencias.conquistas_posicao_row.get_selected() == 3


def test_posicao_sem_selecao_nao_levanta_nem_grava(monkeypatch, schema):
    from gi.repository import Gtk  # noqa: PLC0415

    schema.set_string("conquistas-aviso-posicao", "superior-direito")
    preferencias = _preferencias(monkeypatch)
    preferencias.conquistas_posicao_row.set_selected(Gtk.INVALID_LIST_POSITION)
    assert schema.get_string("conquistas-aviso-posicao") == "superior-direito"


def test_botao_de_exemplo_mostra_um_aviso(monkeypatch):
    from cartridges import conquista_aviso  # noqa: PLC0415

    mostrados = []
    monkeypatch.setattr(conquista_aviso, "mostrar", mostrados.append)
    preferencias = _preferencias(monkeypatch)
    preferencias.conquistas_exemplo_row.emit("activated")
    assert len(mostrados) == 1 and mostrados[0] == conquista_aviso.Aviso.exemplo()


def test_posicao_so_responde_com_o_aviso_ligado(monkeypatch):
    # O FakeSchema não implementa ``bind``: o interruptor é quem manda aqui.
    preferencias = _preferencias(monkeypatch)
    preferencias.conquistas_aviso_switch.set_active(True)
    assert preferencias.conquistas_posicao_row.get_sensitive() is True
    preferencias.conquistas_aviso_switch.set_active(False)
    assert preferencias.conquistas_posicao_row.get_sensitive() is False
