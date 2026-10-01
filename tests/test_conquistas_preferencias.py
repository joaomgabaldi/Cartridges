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
