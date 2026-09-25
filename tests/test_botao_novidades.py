"""Chave show-news-button: nasce oculta, vai no backup e manda no feed."""

import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace

from cartridges import shared
from cartridges.main import CartridgesApplication
from cartridges.utils import backup

_GSCHEMA = Path(__file__).parent.parent / "data" / "page.kramo.Cartridges.gschema.xml.in"


def test_nasce_oculto():
    chave = ET.parse(_GSCHEMA).find(".//key[@name='show-news-button']")
    assert chave is not None
    assert chave.findtext("default") == "false"


def test_vai_no_backup():
    assert backup._filtrar_chaves(["show-news-button"]) == ["show-news-button"]


def test_feed_acompanha_a_chave():
    chamadas = []
    checker = SimpleNamespace(
        start=lambda: chamadas.append("start"), stop=lambda: chamadas.append("stop")
    )
    app = SimpleNamespace(news_checker=checker)

    CartridgesApplication.on_show_news_changed(app)
    shared.schema.set_boolean("show-news-button", True)
    CartridgesApplication.on_show_news_changed(app)

    assert chamadas == ["stop", "start"]
