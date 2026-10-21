"""A preferência "Abrir o Big Picture ao usar um controle"."""

from cartridges import big_picture

SUBTITULO = (
    "Abre o Big Picture ao iniciar o aplicativo com um controle conectado "
    "ou ao conectar um controle na biblioteca"
)
SEM_3D = "Requer uma placa de vídeo com suporte a Vulkan."


def _preferencias(monkeypatch, tem_3d=True):
    import cartridges.preferences as preferences_module  # noqa: PLC0415
    from cartridges.metadata_refresh import MetadataRefresh  # noqa: PLC0415

    monkeypatch.setattr(preferences_module, "get_metadata_refresh", MetadataRefresh)
    monkeypatch.setattr(big_picture, "tem_3d", lambda _janela: tem_3d)
    return preferences_module.CartridgesPreferences()


def test_preferencia_vai_para_o_schema(monkeypatch, schema):
    # O FakeSchema não faz bind de verdade: confere que a chave é ligada à linha.
    ligacoes = []
    monkeypatch.setattr(
        schema, "bind", lambda chave, widget, prop, _flags: ligacoes.append((chave, widget, prop))
    )
    p = _preferencias(monkeypatch)
    assert ("big-picture-ao-conectar", p.big_picture_ao_conectar_switch, "active") in ligacoes


def test_textos_da_linha(monkeypatch, schema):
    schema.set_boolean("gamepad", True)
    p = _preferencias(monkeypatch)
    linha = p.big_picture_ao_conectar_switch
    assert linha.get_title() == "Abrir o Big Picture ao usar um controle"
    assert linha.get_subtitle() == SUBTITULO


def test_cinza_sem_controle(monkeypatch, schema):
    schema.set_boolean("gamepad", False)
    p = _preferencias(monkeypatch)
    assert not p.big_picture_ao_conectar_switch.get_sensitive()
    p.gamepad_switch.set_active(True)
    assert p.big_picture_ao_conectar_switch.get_sensitive()
    p.gamepad_switch.set_active(False)
    assert not p.big_picture_ao_conectar_switch.get_sensitive()


def test_cinza_e_explica_sem_3d(monkeypatch, schema):
    schema.set_boolean("gamepad", True)
    p = _preferencias(monkeypatch, tem_3d=False)
    assert not p.big_picture_ao_conectar_switch.get_sensitive()
    assert p.big_picture_ao_conectar_switch.get_subtitle() == SEM_3D
    # Ligar o controle não destrava uma linha que não tem como funcionar.
    p.gamepad_switch.set_active(False)
    p.gamepad_switch.set_active(True)
    assert not p.big_picture_ao_conectar_switch.get_sensitive()


def test_som_vai_para_o_schema(monkeypatch, schema):
    ligacoes = []
    monkeypatch.setattr(
        schema, "bind", lambda chave, widget, prop, _flags: ligacoes.append((chave, widget, prop))
    )
    p = _preferencias(monkeypatch)
    assert ("big-picture-som", p.big_picture_som_switch, "active") in ligacoes


def test_textos_da_linha_do_som(monkeypatch, schema):
    p = _preferencias(monkeypatch)
    linha = p.big_picture_som_switch
    assert linha.get_title() == "Som ao trocar de capa"
    assert linha.get_subtitle() == "Toca um clique curto a cada capa no Big Picture"


def test_som_nao_depende_do_controle(monkeypatch, schema):
    schema.set_boolean("gamepad", False)
    p = _preferencias(monkeypatch)
    assert p.big_picture_som_switch.get_sensitive()


def test_som_cinza_e_explica_sem_3d(monkeypatch, schema):
    p = _preferencias(monkeypatch, tem_3d=False)
    assert not p.big_picture_som_switch.get_sensitive()
    assert p.big_picture_som_switch.get_subtitle() == SEM_3D
