"""Chave show-news-button: nasce oculta, vai no backup e manda no feed."""

import xml.etree.ElementTree as ET
from pathlib import Path

from cartridges import shared
from cartridges.modelos.avisos import FilaDeAvisos
from cartridges.modelos.novidades import Novidades
from cartridges.utils import backup
from tests.apoio_novidades import CheckerFalso

_GSCHEMA = Path(__file__).parent.parent / "data" / "io.github.joaomgabaldi.Cartridges.gschema.xml.in"


def test_nasce_oculto():
    chave = ET.parse(_GSCHEMA).find(".//key[@name='show-news-button']")
    assert chave is not None
    assert chave.findtext("default") == "false"


def test_vai_no_backup():
    assert backup._filtrar_chaves(["show-news-button"]) == ["show-news-button"]


def test_feed_acompanha_a_chave(app_qt):
    checker = CheckerFalso()
    novidades = Novidades(FilaDeAvisos(), checker)

    novidades.ligar()
    shared.schema.set_boolean("show-news-button", True)
    novidades.ligar()

    assert checker.chamadas == ["stop", "start"]
