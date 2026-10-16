"""Chave news-source: escolhe o site lido pela página Novidades.

O aviso de atualização por jogo continua lendo sempre a FitGirl
(`updates_feed.FEED_URL`); só a página Novidades muda de site.
"""

import xml.etree.ElementTree as ET
from pathlib import Path

from cartridges import shared
from cartridges.utils import news_checker as news_checker_mod
from cartridges.utils.news_checker import NewsChecker
from cartridges.utils.news_feed import NEWS_SOURCES, NewsPost, parse_news, summarize
from cartridges.utils.updates_feed import FEED_URL

_GSCHEMA = Path(__file__).parent.parent / "data" / "io.github.joaomgabaldi.Cartridges.gschema.xml.in"

# Mesmo formato do feed da IGN Brasil: imagem no começo da <description>,
# dc:creator, enclosure e várias <category>, a primeira sendo o jogo.
_IGN_FEED = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/"><channel><title>IGN Brasil</title>
<item><title>Estúdio anuncia um jogo novo</title>
<link>https://br.ign.com/jogo-x/1/estudio-anuncia</link>
<description>&lt;img src="https://sm.ign.com/t/ign_br/news/x.640.jpg" width="120" hspace="5" alt="" vspace="5" align="left" /&gt;
Um resumo curto</description>
<dc:creator>Fulano</dc:creator>
<pubDate>Thu, 15 Oct 2026 23:56:05 +0000</pubDate>
<guid>https://br.ign.com/jogo-x/1/estudio-anuncia</guid>
<enclosure length="0" type="image/jpeg" url="https://sm.ign.com/ign_br/news/x.jpg"/>
<category>Jogo X</category><category>Games</category><category>Notícias</category></item>
</channel></rss>"""


def _post(ts: int) -> NewsPost:
    return NewsPost(str(ts), ts, "t", "", "", "")


def test_chave_nasce_na_fitgirl():
    chave = ET.parse(_GSCHEMA).find(".//key[@name='news-source']")
    assert chave is not None
    assert chave.findtext("default") == '"fitgirl"'
    assert [c.get("value") for c in chave.iter("choice")] == ["fitgirl", "ign-br"]


def test_cada_fonte_tem_seu_endereco():
    # A ordem conta: é a das linhas da lista nas Preferências.
    assert list(NEWS_SOURCES.items()) == [
        ("fitgirl", FEED_URL),
        ("ign-br", "https://br.ign.com/feed.xml"),
    ]


def test_le_o_feed_da_ign():
    (post,) = parse_news(_IGN_FEED)
    assert post.title == "Estúdio anuncia um jogo novo"
    assert post.url == "https://br.ign.com/jogo-x/1/estudio-anuncia"
    assert post.summary == "Um resumo curto"
    assert post.category == "Jogo X"
    assert post.timestamp > 0


def test_busca_no_site_escolhido(monkeypatch):
    urls = []
    monkeypatch.setattr(news_checker_mod, "fetch_news", lambda url: urls.append(url) or [])
    # Sem isto o `_apply` ficaria pendurado no laço e rodaria no meio de outro teste.
    monkeypatch.setattr(news_checker_mod.GLib, "idle_add", lambda *_: None)
    shared.schema.set_string("news-source", "ign-br")
    NewsChecker()._poll_thread()
    assert urls == ["https://br.ign.com/feed.xml"]


def _checker_sem_rede(monkeypatch):
    """Checker cuja leitura nunca termina: nem rede, nem `_apply` no laço."""
    monkeypatch.setattr(news_checker_mod, "fetch_news", lambda url: [])
    monkeypatch.setattr(news_checker_mod.GLib, "idle_add", lambda *_: None)
    return NewsChecker()


def test_trocar_de_site_recomeca_do_zero(monkeypatch):
    checker = _checker_sem_rede(monkeypatch)
    checker._posts = (_post(100),)
    checker._has_unseen = True
    shared.state_schema.set_int64("news-last-seen-ts", 50)
    # A janela escolhe entre lista, carregando e "Sem novidades" ao receber
    # `posts-changed`; nessa hora a busca do site novo já tem de estar no ar,
    # ou a página aberta mostraria um erro falso.
    carregando_no_sinal = []
    checker.connect("posts-changed", lambda c: carregando_no_sinal.append(c.loading))

    checker.on_source_changed()

    assert checker.posts == ()
    assert not checker.has_unseen
    assert shared.state_schema.get_int64("news-last-seen-ts") == 0
    assert carregando_no_sinal == [True]


def test_trocar_de_site_com_a_lista_vazia_tambem_avisa_a_janela(monkeypatch):
    checker = _checker_sem_rede(monkeypatch)
    carregando_no_sinal = []
    checker.connect("posts-changed", lambda c: carregando_no_sinal.append(c.loading))
    checker.on_source_changed()
    assert carregando_no_sinal == [True]


def test_site_trocado_fora_das_preferencias_recomeca_a_referencia():
    # Um backup restaurado na abertura troca o site antes de qualquer sinal:
    # a data de "já visto" ainda é a da FitGirl e não vale para a IGN.
    shared.state_schema.set_int64("news-last-seen-ts", 50)
    shared.schema.set_string("news-source", "ign-br")
    checker = NewsChecker()
    checker._apply([_post(100)], "ign-br")
    assert not checker.has_unseen
    assert shared.state_schema.get_int64("news-last-seen-ts") == 100
    assert shared.state_schema.get_string("news-last-seen-source") == "ign-br"


def test_mesmo_site_mantem_a_referencia():
    shared.state_schema.set_int64("news-last-seen-ts", 50)
    checker = NewsChecker()
    checker._apply([_post(100)], "fitgirl")
    assert checker.has_unseen


def test_paragrafos_nao_grudam():
    assert summarize("<p>Preparem-se</p><p>A Activision anunciou</p>") == (
        "Preparem-se\n\nA Activision anunciou"
    )


def test_resumo_nao_traz_a_materia_inteira():
    # Alguns itens da IGN trazem o artigo completo; a página mostra um resumo
    # e o link, não a matéria de outro site.
    resumo = summarize("<p>" + "palavra " * 500 + "</p>")
    assert len(resumo) <= 601
    assert resumo.endswith("…")


def test_resposta_do_site_antigo_e_descartada(monkeypatch):
    # Uma leitura da FitGirl que volta depois da troca para a IGN não pode
    # entrar na lista nem virar a referência de "já visto" da IGN.
    checker = NewsChecker()
    polls = []
    monkeypatch.setattr(checker, "check_async", lambda: polls.append("poll"))
    shared.schema.set_string("news-source", "ign-br")
    checker._apply([_post(100)], "fitgirl")
    assert checker.posts == ()
    assert shared.state_schema.get_int64("news-last-seen-ts") == 0
    assert polls == ["poll"]


def _preferencias(monkeypatch):
    import cartridges.preferences as preferences_module  # noqa: PLC0415
    from cartridges.metadata_refresh import MetadataRefresh  # noqa: PLC0415

    monkeypatch.setattr(preferences_module, "get_metadata_refresh", MetadataRefresh)
    return preferences_module.CartridgesPreferences()


def test_site_escolhido_vai_para_o_schema(monkeypatch, schema):
    preferencias = _preferencias(monkeypatch)
    preferencias.news_source_row.set_selected(1)
    assert schema.get_string("news-source") == "ign-br"
    preferencias.news_source_row.set_selected(0)
    assert schema.get_string("news-source") == "fitgirl"


def test_site_guardado_aparece_na_linha(monkeypatch, schema):
    schema.set_string("news-source", "ign-br")
    preferencias = _preferencias(monkeypatch)
    assert preferencias.news_source_row.get_selected() == 1


def test_rotulos_da_lista_seguem_a_ordem_das_fontes(monkeypatch):
    modelo = _preferencias(monkeypatch).news_source_row.get_model()
    rotulos = [modelo.get_string(i) for i in range(modelo.get_n_items())]
    assert rotulos == ["FitGirl Repacks", "IGN Brasil"]


def test_linha_do_site_segue_o_botao(monkeypatch):
    preferencias = _preferencias(monkeypatch)
    preferencias.show_news_button_switch.set_active(False)
    assert not preferencias.news_source_row.get_sensitive()
    preferencias.show_news_button_switch.set_active(True)
    assert preferencias.news_source_row.get_sensitive()


def test_quebra_de_linha_sem_tag_nao_vira_paragrafo():
    assert summarize("Uma linha\nque continua") == "Uma linha que continua"
