"""O catálogo de conquistas: Steam, arquivo do jogo, raridade e cache."""

import json
import logging
import threading
import time

import pytest
from requests.exceptions import ConnectionError as ErroDeConexao

from cartridges.conquistas import catalogo
from cartridges.conquistas.catalogo import Catalogo, ConquistaInfo

SCHEMA = {
    "game": {
        "gameName": "Jogo",
        "availableGameStats": {
            "achievements": [
                {
                    "name": "ACH_A",
                    "displayName": "Primeira",
                    "description": "Faça algo.",
                    "hidden": 0,
                    "icon": "https://cdn/a.jpg",
                    "icongray": "https://cdn/a_g.jpg",
                },
                {
                    "name": "ACH_B",
                    "displayName": "Segredo",
                    "hidden": 1,
                    "icon": "https://cdn/b.jpg",
                    "icongray": "https://cdn/b_g.jpg",
                },
            ]
        },
    }
}
PORCENTAGENS = {
    "achievementpercentages": {
        "achievements": [{"name": "ACH_A", "percent": "55.5"}, {"name": "ACH_B", "percent": 4.1}]
    }
}
INFO = ConquistaInfo("ACH_L", "Local", "", "", "", False)


def _pedidos(respostas):
    """Um `_pedir` falso: a primeira chave de ``respostas`` contida na URL decide."""

    def pedir(url):
        for trecho, resposta in respostas.items():
            if trecho in url:
                if isinstance(resposta, Exception):
                    raise resposta
                return resposta
        raise AssertionError(f"pedido inesperado: {url}")

    return pedir


def test_ler_schema_da_steam():
    infos = catalogo.ler_schema_da_steam(SCHEMA)
    assert [i.nome for i in infos] == ["ACH_A", "ACH_B"]
    assert infos[0].titulo == "Primeira" and infos[0].descricao == "Faça algo."
    assert infos[1].oculta and infos[1].descricao == ""


def test_schema_sem_conquistas():
    assert catalogo.ler_schema_da_steam({"game": {}}) == []
    assert catalogo.ler_schema_da_steam(None) == []


def test_porcentagens_e_raras():
    infos = catalogo.com_porcentagens(
        catalogo.ler_schema_da_steam(SCHEMA), catalogo.ler_porcentagens(PORCENTAGENS)
    )
    assert [i.porcentagem for i in infos] == [55.5, 4.1]
    assert [i.rara for i in infos] == [False, True]


def test_steam_settings_idiomas_e_icones(tmp_path):
    pasta = tmp_path / "steam_settings"
    (pasta / "images").mkdir(parents=True)
    (pasta / "images" / "a.jpg").write_bytes(b"jpg")
    arquivo = pasta / "achievements.json"
    arquivo.write_text(
        json.dumps(
            [
                {
                    "name": "ACH_A",
                    "displayName": {"english": "First", "brazilian": "Primeira"},
                    "description": {"english": "Do it"},
                    "hidden": "0",
                    "icon": "images/a.jpg",
                    "icon_gray": "images/a_g.jpg",
                },
                {"name": "ACH_B", "displayName": "Hidden", "hidden": "1", "icon": "https://x/b.jpg"},
            ]
        ),
        encoding="utf-8",
    )
    a, b = catalogo.ler_steam_settings(arquivo)
    assert (a.titulo, a.descricao) == ("Primeira", "Do it")
    assert a.icone == str(pasta / "images" / "a.jpg")
    assert a.icone_cinza == ""  # o arquivo não existe
    assert b.oculta and b.icone_cinza == "https://x/b.jpg"


def test_cache_ida_e_volta():
    cat = Catalogo((ConquistaInfo("ACH_A", "A", "d", "i", "g", True, 3.5),), 1000, True)
    catalogo._gravar_cache("570", cat)
    assert catalogo.em_cache("570") == cat


def test_vencido():
    cat = Catalogo((), 1000, False)
    assert not catalogo.vencido(cat, 1000 + catalogo.VALIDADE - 1, "")
    assert catalogo.vencido(cat, 1000 + catalogo.VALIDADE, "")


def test_impressao_da_chave():
    assert catalogo._impressao("") == ""
    assert catalogo._impressao("A") != catalogo._impressao("B")
    assert catalogo._impressao("A") == catalogo._impressao("A") != ""
    assert len(catalogo._impressao("A")) == 16


def test_cache_feito_com_a_chave_a_vale_para_a_e_vence_para_b():
    impressao_a = catalogo._impressao("A")
    cat = Catalogo((INFO,), 1000, True, impressao_a)
    assert not catalogo.vencido(cat, 1010, impressao_a)
    assert catalogo.vencido(cat, 1010, catalogo._impressao("B"))
    assert catalogo.vencido(cat, 1010, "")  # chave removida: renova


def test_cache_feito_sem_chave_vence_quando_uma_chave_aparece():
    cat = Catalogo((INFO,), 1000, False)
    assert catalogo.vencido(cat, 1010, catalogo._impressao("A"))


def test_impressao_vai_para_o_cache():
    cat = Catalogo((INFO,), 1000, False, catalogo._impressao("A"))
    catalogo._gravar_cache("570", cat)
    assert catalogo.em_cache("570") == cat


def test_cache_antigo_sem_impressao_le_como_vazia():
    destino = catalogo._arquivo_do_cache("570")
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps({"obtido_em": 1, "com_chave": True, "conquistas": []}))
    assert catalogo.em_cache("570") == Catalogo((), 1, True, "")


def test_impressao_de_tipo_errado_no_cache_e_ilegivel():
    destino = catalogo._arquivo_do_cache("570")
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(
        json.dumps({"obtido_em": 1, "com_chave": True, "conquistas": [], "impressao_da_chave": 7})
    )
    assert catalogo.em_cache("570") is None


def test_chave_recusada_nao_e_repetida_por_sete_dias(monkeypatch, schema):
    schema.set_string("conquistas-chave-steam", "ruim")
    monkeypatch.setattr(catalogo, "_local", lambda _exe: [INFO])
    monkeypatch.setattr(
        catalogo,
        "_pedir",
        _pedidos({"GetSchemaForGame": catalogo.ChaveRecusada(), "GetGlobal": PORCENTAGENS}),
    )
    assert catalogo.renovar("570", "", agora=10).chave_recusada
    monkeypatch.setattr(catalogo, "_pedir", _pedidos({}))  # qualquer pedido falha o teste
    assert [i.nome for i in catalogo.obter("570", "", agora=20).catalogo.conquistas] == ["ACH_L"]
    monkeypatch.setattr(catalogo, "_pedir", _pedidos({"GetSchemaForGame": SCHEMA, "GetGlobal": {}}))
    schema.set_string("conquistas-chave-steam", "outra")
    assert catalogo.obter("570", "", agora=20).catalogo.com_chave


def test_chave_nunca_vai_para_o_log(monkeypatch, schema, caplog):
    schema.set_string("conquistas-chave-steam", "SEGREDO123")
    url = f"{catalogo._API}/GetSchemaForGame/v2/?key=SEGREDO123&appid=570&l=brazilian"
    monkeypatch.setattr(catalogo, "_local", lambda _exe: [INFO])
    monkeypatch.setattr(
        catalogo,
        "_pedir",
        _pedidos({"GetSchemaForGame": ErroDeConexao(f"Max retries exceeded with url: {url}"), "GetGlobal": {}}),
    )
    with caplog.at_level(logging.DEBUG):
        catalogo.renovar("570", "", agora=10)
    assert "ConnectionError" in caplog.text
    assert "SEGREDO123" not in caplog.text


def test_com_chave_sem_rede_e_sem_cache_usa_o_arquivo_do_jogo(monkeypatch, schema):
    schema.set_string("conquistas-chave-steam", "abc")
    monkeypatch.setattr(catalogo, "_local", lambda _exe: [INFO])
    monkeypatch.setattr(
        catalogo,
        "_pedir",
        _pedidos({"GetSchemaForGame": ErroDeConexao(), "GetGlobal": ErroDeConexao()}),
    )
    cat = catalogo.renovar("570", "", agora=10).catalogo
    assert [i.nome for i in cat.conquistas] == ["ACH_L"]
    # Falha de rede não é veredito: na próxima abertura a chave é tentada de novo.
    assert catalogo.vencido(cat, 11, catalogo._impressao("abc"))


def test_criacao_do_limitador_e_uma_so(monkeypatch):
    monkeypatch.setattr(catalogo, "_limitador", None)
    criados = []

    class Falso:
        def __init__(self):
            time.sleep(0.02)  # alarga a janela da corrida
            criados.append(self)

    monkeypatch.setattr(catalogo, "SteamWebApiLimiter", Falso)
    achados = []
    fios = [threading.Thread(target=lambda: achados.append(catalogo._limite())) for _ in range(8)]
    for fio in fios:
        fio.start()
    for fio in fios:
        fio.join()
    assert len(criados) == 1 and all(item is criados[0] for item in achados)


def test_renovar_com_chave(monkeypatch, schema):
    schema.set_string("conquistas-chave-steam", "abc")
    monkeypatch.setattr(
        catalogo, "_pedir", _pedidos({"GetSchemaForGame": SCHEMA, "GetGlobal": PORCENTAGENS})
    )
    renovacao = catalogo.renovar("570", "", agora=5000)
    cat = renovacao.catalogo
    assert cat.com_chave and cat.obtido_em == 5000 and not renovacao.chave_recusada
    assert [i.porcentagem for i in cat.conquistas] == [55.5, 4.1]
    assert catalogo.em_cache("570") == cat


def test_sem_chave_usa_o_arquivo_do_jogo(monkeypatch):
    monkeypatch.setattr(catalogo, "_local", lambda _exe: [INFO])
    monkeypatch.setattr(catalogo, "_pedir", _pedidos({"GetGlobal": PORCENTAGENS}))
    cat = catalogo.renovar("570", "", agora=10).catalogo
    assert [i.nome for i in cat.conquistas] == ["ACH_L"]
    assert not cat.com_chave


def test_chave_recusada_cai_no_arquivo_do_jogo(monkeypatch, schema):
    schema.set_string("conquistas-chave-steam", "ruim")
    monkeypatch.setattr(catalogo, "_local", lambda _exe: [INFO])
    monkeypatch.setattr(
        catalogo,
        "_pedir",
        _pedidos({"GetSchemaForGame": catalogo.ChaveRecusada(), "GetGlobal": PORCENTAGENS}),
    )
    renovacao = catalogo.renovar("570", "", agora=10)
    assert renovacao.chave_recusada
    assert [i.nome for i in renovacao.catalogo.conquistas] == ["ACH_L"]


def test_rede_fora_fica_com_o_cache(monkeypatch, schema):
    schema.set_string("conquistas-chave-steam", "abc")
    anterior = Catalogo((INFO,), 1, True)
    catalogo._gravar_cache("570", anterior)
    monkeypatch.setattr(catalogo, "_pedir", _pedidos({"GetSchemaForGame": ErroDeConexao()}))
    assert catalogo.renovar("570", "", agora=10**9).catalogo == anterior


def test_obter_usa_o_cache_valido(monkeypatch):
    cat = Catalogo((INFO,), 1000, False)
    catalogo._gravar_cache("570", cat)
    monkeypatch.setattr(catalogo, "_pedir", _pedidos({}))  # qualquer pedido falha o teste
    assert catalogo.obter("570", "", agora=1010).catalogo == cat


def test_sem_fonte_nenhuma_nao_cria_cache(monkeypatch):
    monkeypatch.setattr(catalogo, "_local", lambda _exe: [])
    monkeypatch.setattr(catalogo, "_pedir", _pedidos({"GetGlobal": PORCENTAGENS}))
    assert catalogo.renovar("570", "", agora=10).catalogo is None
    assert catalogo.em_cache("570") is None


@pytest.mark.parametrize("hidden", [1, "1", True])
def test_oculta_em_qualquer_grafia(hidden):
    payload = {"game": {"availableGameStats": {"achievements": [{"name": "A", "hidden": hidden}]}}}
    assert catalogo.ler_schema_da_steam(payload)[0].oculta


# --- "nunca levanta": o que a rede ou o disco podem trazer ---------------------


@pytest.mark.parametrize(
    "percent", [float("inf"), float("nan"), "1e999", "nan", 10**400, "abc", None]
)
def test_porcentagem_que_nao_e_finita_e_ignorada(percent):
    payload = {
        "achievementpercentages": {
            "achievements": [{"name": "RUIM", "percent": percent}, {"name": "OK", "percent": 7}]
        }
    }
    assert catalogo.ler_porcentagens(payload) == {"OK": 7.0}


def _cache_com(**campos):
    base = {"obtido_em": 1, "com_chave": False, "conquistas": []}
    return json.dumps({**base, **campos})


_CONQUISTA = {
    "nome": "A",
    "titulo": "A",
    "descricao": "",
    "icone": "",
    "icone_cinza": "",
    "oculta": False,
}


@pytest.mark.parametrize(
    "texto",
    [
        _cache_com(conquistas=[{**_CONQUISTA, "porcentagem": "muita"}]),
        _cache_com(conquistas=[{**_CONQUISTA, "porcentagem": 1e999}]),
        _cache_com(conquistas=[{**_CONQUISTA, "porcentagem": 10**400}]),
        _cache_com(conquistas=[{**_CONQUISTA, "nome": 7}]),
        _cache_com(conquistas=["A"]),
        _cache_com(conquistas=5),
        '{"obtido_em": 1e999, "com_chave": false, "conquistas": []}',
        '{"obtido_em": NaN, "com_chave": false, "conquistas": []}',
        "[" * 100000,
        "[]",
        "",
    ],
    ids=[
        "porcentagem-texto",
        "porcentagem-infinita",
        "porcentagem-gigante",
        "nome-numero",
        "item-nao-objeto",
        "conquistas-nao-lista",
        "obtido-infinito",
        "obtido-nan",
        "fundo-demais",
        "raiz-lista",
        "vazio",
    ],
)
def test_cache_ilegivel_nao_levanta(texto):
    destino = catalogo._arquivo_do_cache("570")
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(texto, encoding="utf-8")
    assert catalogo.em_cache("570") is None


@pytest.mark.parametrize("erro", [RecursionError(), ValueError("json")])
def test_resposta_da_steam_ilegivel_fica_com_o_cache(monkeypatch, schema, erro):
    schema.set_string("conquistas-chave-steam", "abc")
    anterior = Catalogo((INFO,), 1, True)
    catalogo._gravar_cache("570", anterior)
    monkeypatch.setattr(catalogo, "_pedir", _pedidos({"GetSchemaForGame": erro}))
    assert catalogo.renovar("570", "", agora=10**9).catalogo == anterior


def test_porcentagens_ilegiveis_nao_derrubam_a_renovacao(monkeypatch):
    monkeypatch.setattr(catalogo, "_local", lambda _exe: [INFO])
    monkeypatch.setattr(catalogo, "_pedir", _pedidos({"GetGlobal": RecursionError()}))
    assert catalogo.renovar("570", "", agora=10).catalogo.conquistas == (INFO,)


def test_steam_settings_fundo_demais_nao_levanta(tmp_path):
    arquivo = tmp_path / "achievements.json"
    arquivo.write_text("[" * 100000, encoding="utf-8")
    assert catalogo.ler_steam_settings(arquivo) == []
