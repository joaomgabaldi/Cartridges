"""O leitor da página inicial do ElAmigos para a página de Novidades."""

from calendar import timegm

from kyron.utils import elamigos_feed
from kyron.utils.elamigos_feed import parse_page

# Um recorte do formato real: blocos por data, novos acima do <hr>, updates abaixo, e o arquivo alfabético depois do <h4>.
_PAGINA = """
<!-- Marker1-Start -->
<h1>07.11.2026</h1>
<h3>Silica ElAmigos <a href="data/Silica_MULTi10_-_ElAmigos.html">DOWNLOAD</a></h3>
<hr>
<h3>Forza Horizon 6 Premium Edition ElAmigos +[Update 479.874] <a href="data/Forza.html">DOWNLOAD</a></h3>
<h3>007 First Light ElAmigos [Update 1.3.0] +[Update 1.3.2.H1] <a href="data/007.html">DOWNLOAD</a></h3>
<h3>Malicioso ElAmigos <a href="javascript:alert(1)">DOWNLOAD</a></h3>
<br>
<h1>01.11.2026</h1>
<h3>Silica ElAmigos <a href="data/Silica_MULTi10_-_ElAmigos.html">DOWNLOAD</a></h3>
<h3>Reka Deluxe Edition ElAmigos <a href="data/Reka.html">DOWNLOAD</a></h3>
<hr>
<h1>01.09.2026</h1>
<h3>Antigo ElAmigos <a href="data/Antigo.html">DOWNLOAD</a></h3>
<h4>Full log of updates</h4>
<hr><hr><hr>
<h3>60 Parsecs ElAmigos [Build 15.04.2026] <a href="data/60.html">DOWNLOAD</a></h3>
"""

_AGORA = timegm((2026, 11, 7, 12, 0, 0))


def _ler(pagina=_PAGINA):
    return parse_page(pagina, now=_AGORA)


def test_le_nome_marca_link_e_data():
    posts = _ler()
    forza = next(p for p in posts if p.title == "Forza Horizon 6 Premium Edition")
    assert forza.summary == "Update 479.874"
    assert forza.url == "https://elamigos.site/data/Forza.html"
    assert forza.category == "ElAmigos"
    assert forza.timestamp == timegm((2026, 11, 7, 12, 0, 0))


def test_varias_marcas_viram_um_resumo():
    jogo = next(p for p in _ler() if p.title == "007 First Light")
    assert jogo.summary == "Update 1.3.0, Update 1.3.2.H1"


def test_lancamento_sem_marca_tem_resumo_vazio():
    assert next(p for p in _ler() if p.title == "Silica").summary == ""


def test_link_fora_de_http_fica_sem_link():
    assert next(p for p in _ler() if p.title == "Malicioso").url == ""


def test_repetido_vale_o_mais_novo():
    silicas = [p for p in _ler() if p.title == "Silica"]
    assert len(silicas) == 1
    assert silicas[0].timestamp == timegm((2026, 11, 7, 12, 0, 0))


def test_corta_trinta_dias_e_ignora_o_arquivo():
    titulos = {p.title for p in _ler()}
    assert "Reka Deluxe Edition" in titulos
    assert "Antigo" not in titulos  # mais de 30 dias
    assert "60 Parsecs" not in titulos  # arquivo alfabético, sem data


def test_ordem_do_mais_novo():
    stamps = [p.timestamp for p in _ler()]
    assert stamps == sorted(stamps, reverse=True)


def test_data_no_futuro_e_descartada():
    assert _ler("<h1>01.01.2030</h1><h3>Futuro ElAmigos <a href='data/f.html'>DOWNLOAD</a></h3>") == []


def test_html_quebrado_nao_levanta():
    assert _ler("<h1>07.11.2026<h3>Sem fim ElAmigos <a href=") == []
    assert _ler("") == []
    # Um <h1> sem data dentro do <h3> não troca a data do item por None.
    jogos = _ler('<h1>07.11.2026</h1><h3>Jogo <h1>x</h1> ElAmigos <a href="data/a.html">DOWNLOAD</a></h3>')
    assert [p.timestamp for p in jogos] == [timegm((2026, 11, 7, 12, 0, 0))]


def test_fetch_usa_o_transporte_comum(monkeypatch):
    monkeypatch.setattr(elamigos_feed, "fetch_feed_text", lambda url: _PAGINA)
    monkeypatch.setattr(elamigos_feed, "time", lambda: _AGORA)
    assert elamigos_feed.fetch_elamigos()
