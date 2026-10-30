"""A preferência "Abrir o Big Picture ao usar um controle" e a do som, sobre o modelo das Preferências."""

import pytest

from cartridges import shared
from cartridges.modelos.preferencias import SEM_3D, Preferencias


def _preferencias(tem_3d=True):
    p = Preferencias(None, lambda: tem_3d)
    assert p.abrir()
    return p


@pytest.fixture
def com_3d_falso(app_qt):  # noqa: ARG001
    return _preferencias


def test_preferencia_vai_para_o_schema(com_3d_falso):
    p = com_3d_falso()
    p.definir("big-picture-ao-conectar", True)
    assert shared.schema.get_boolean("big-picture-ao-conectar")
    assert p.valores["big-picture-ao-conectar"] is True


def test_textos_da_linha(com_3d_falso):
    # O texto fixo da linha vai ao QML (Task 2); aqui, que o modelo não põe o aviso de 3D quando há 3D.
    p = com_3d_falso()
    assert p.estado["subtituloSem3d"] == ""


def test_cinza_sem_controle(com_3d_falso):
    shared.schema.set_boolean("gamepad", False)
    p = com_3d_falso()
    assert not p.estado["bigPictureAtivo"]
    p.definir("gamepad", True)
    assert p.estado["bigPictureAtivo"]
    p.definir("gamepad", False)
    assert not p.estado["bigPictureAtivo"]


def test_cinza_e_explica_sem_3d(com_3d_falso):
    shared.schema.set_boolean("gamepad", True)
    p = com_3d_falso(tem_3d=False)
    assert not p.estado["bigPictureAtivo"]
    assert p.estado["subtituloSem3d"] == SEM_3D == "Requer uma placa de vídeo com aceleração 3D."
    # Ligar o controle não destrava uma linha que não tem como funcionar.
    p.definir("gamepad", False)
    p.definir("gamepad", True)
    assert not p.estado["bigPictureAtivo"]


def test_som_vai_para_o_schema(com_3d_falso):
    p = com_3d_falso()
    p.definir("big-picture-som", False)
    assert not shared.schema.get_boolean("big-picture-som")


def test_textos_da_linha_do_som(com_3d_falso):
    # Título e subtítulo fixos vão ao QML (Task 2); aqui, o som segue ativo com 3D.
    assert com_3d_falso().estado["somDoBigPictureAtivo"]


def test_som_nao_depende_do_controle(com_3d_falso):
    shared.schema.set_boolean("gamepad", False)
    assert com_3d_falso().estado["somDoBigPictureAtivo"]


def test_som_cinza_e_explica_sem_3d(com_3d_falso):
    p = com_3d_falso(tem_3d=False)
    assert not p.estado["somDoBigPictureAtivo"]
    assert p.estado["subtituloSem3d"] == SEM_3D
