"""O catálogo de conquistas: Steam, arquivo do jogo, raridade e cache."""

import json
import logging
import threading
import time
from pathlib import Path

import pytest
from requests.exceptions import ConnectionError as ErroDeConexao

from cartridges import shared
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


# --- rede fora, cache negativo, entradas estranhas ------------------------------


def _sem_pedidos(monkeypatch):
    chamadas = []

    def pedir(url):
        chamadas.append(url)
        raise AssertionError(f"pedido inesperado: {url}")

    monkeypatch.setattr(catalogo, "_pedir", pedir)
    return chamadas


def test_falha_de_rede_no_schema_marca_rede_falhou(monkeypatch, schema):
    schema.set_string("conquistas-chave-steam", "abc")
    monkeypatch.setattr(catalogo, "_local", lambda _exe: [INFO])
    monkeypatch.setattr(
        catalogo,
        "_pedir",
        _pedidos({"GetSchemaForGame": ErroDeConexao(), "GetGlobal": ErroDeConexao()}),
    )
    assert catalogo.renovar("570", "", agora=10).rede_falhou


def test_falha_de_rede_nas_porcentagens_marca_rede_falhou(monkeypatch):
    monkeypatch.setattr(catalogo, "_local", lambda _exe: [INFO])
    monkeypatch.setattr(catalogo, "_pedir", _pedidos({"GetGlobal": ErroDeConexao()}))
    renovacao = catalogo.renovar("570", "", agora=10)
    assert renovacao.rede_falhou
    assert renovacao.catalogo.conquistas == (INFO,)  # o arquivo do jogo vale


def test_sucesso_nao_marca_rede_falhou(monkeypatch):
    monkeypatch.setattr(catalogo, "_local", lambda _exe: [INFO])
    monkeypatch.setattr(catalogo, "_pedir", _pedidos({"GetGlobal": PORCENTAGENS}))
    assert not catalogo.renovar("570", "", agora=10).rede_falhou


def test_resposta_ilegivel_nao_conta_como_rede_fora(monkeypatch, schema):
    schema.set_string("conquistas-chave-steam", "abc")
    monkeypatch.setattr(catalogo, "_local", lambda _exe: [INFO])
    monkeypatch.setattr(
        catalogo, "_pedir", _pedidos({"GetSchemaForGame": ValueError(), "GetGlobal": {}})
    )
    assert not catalogo.renovar("570", "", agora=10).rede_falhou


def test_sem_rede_usa_o_cache_vencido_sem_pedir(monkeypatch, schema):
    schema.set_string("conquistas-chave-steam", "abc")
    anterior = Catalogo((INFO,), 1, True, catalogo._impressao("abc"))
    catalogo._gravar_cache("570", anterior)
    pedidos = _sem_pedidos(monkeypatch)
    renovacao = catalogo.obter("570", "", agora=10**9, rede=False)
    assert renovacao.catalogo == anterior
    assert not renovacao.rede_falhou
    assert pedidos == []


def test_sem_rede_e_sem_cache_usa_o_arquivo_do_jogo(monkeypatch, schema):
    schema.set_string("conquistas-chave-steam", "abc")
    monkeypatch.setattr(catalogo, "_local", lambda _exe: [INFO])
    pedidos = _sem_pedidos(monkeypatch)
    cat = catalogo.obter("570", "", agora=10, rede=False).catalogo
    assert [i.nome for i in cat.conquistas] == ["ACH_L"]
    assert pedidos == []
    # Nada foi perguntado à Steam: na próxima abertura a chave é tentada.
    assert catalogo.vencido(cat, 11, catalogo._impressao("abc"))


def test_sem_rede_e_sem_nada_devolve_vazio(monkeypatch, schema):
    schema.set_string("conquistas-chave-steam", "abc")
    monkeypatch.setattr(catalogo, "_local", lambda _exe: [])
    pedidos = _sem_pedidos(monkeypatch)
    assert catalogo.obter("570", "", agora=10, rede=False).catalogo is None
    assert catalogo.em_cache("570") is None
    assert pedidos == []


def test_steam_sem_conquistas_vira_cache_negativo(monkeypatch, schema):
    schema.set_string("conquistas-chave-steam", "abc")
    monkeypatch.setattr(catalogo, "_local", lambda _exe: [])
    monkeypatch.setattr(catalogo, "_pedir", _pedidos({"GetSchemaForGame": {"game": {}}}))
    primeira = catalogo.obter("570", "", agora=10)
    assert primeira.catalogo is not None and primeira.catalogo.conquistas == ()
    assert catalogo.em_cache("570") == Catalogo((), 10, True, catalogo._impressao("abc"))
    # Dentro dos 7 dias, nenhum pedido: o jogo sem conquistas não vai à rede a cada abertura.
    pedidos = _sem_pedidos(monkeypatch)
    segunda = catalogo.obter("570", "", agora=10 + catalogo.VALIDADE - 1)
    assert segunda.catalogo.conquistas == ()
    assert pedidos == []
    # Depois dos 7 dias, pergunta de novo.
    monkeypatch.setattr(catalogo, "_pedir", _pedidos({"GetSchemaForGame": SCHEMA, "GetGlobal": {}}))
    assert catalogo.obter("570", "", agora=10 + catalogo.VALIDADE).catalogo.conquistas


def test_cache_negativo_nao_vale_para_outra_chave(monkeypatch, schema):
    schema.set_string("conquistas-chave-steam", "abc")
    monkeypatch.setattr(catalogo, "_local", lambda _exe: [])
    monkeypatch.setattr(catalogo, "_pedir", _pedidos({"GetSchemaForGame": {"game": {}}}))
    catalogo.obter("570", "", agora=10)
    schema.set_string("conquistas-chave-steam", "outra")
    monkeypatch.setattr(catalogo, "_pedir", _pedidos({"GetSchemaForGame": SCHEMA, "GetGlobal": {}}))
    assert catalogo.obter("570", "", agora=20).catalogo.conquistas


def test_falha_de_rede_nao_vira_cache_negativo(monkeypatch, schema):
    schema.set_string("conquistas-chave-steam", "abc")
    monkeypatch.setattr(catalogo, "_local", lambda _exe: [])
    monkeypatch.setattr(catalogo, "_pedir", _pedidos({"GetSchemaForGame": ErroDeConexao()}))
    renovacao = catalogo.obter("570", "", agora=10)
    assert renovacao.catalogo is None and renovacao.rede_falhou
    assert catalogo.em_cache("570") is None


def test_cache_negativo_nao_apaga_um_catalogo_anterior(monkeypatch, schema):
    schema.set_string("conquistas-chave-steam", "abc")
    anterior = Catalogo((INFO,), 1, True, catalogo._impressao("abc"))
    catalogo._gravar_cache("570", anterior)
    monkeypatch.setattr(catalogo, "_local", lambda _exe: [])
    monkeypatch.setattr(catalogo, "_pedir", _pedidos({"GetSchemaForGame": {"game": {}}}))
    assert catalogo.renovar("570", "", agora=10**9).catalogo == anterior
    assert catalogo.em_cache("570") == anterior


def test_sem_chave_e_sem_arquivo_nao_cria_cache_negativo(monkeypatch):
    monkeypatch.setattr(catalogo, "_local", lambda _exe: [])
    pedidos = _sem_pedidos(monkeypatch)
    assert catalogo.obter("570", "", agora=10).catalogo is None
    assert catalogo.em_cache("570") is None
    assert pedidos == []


def test_cache_do_futuro_esta_vencido():
    cat = Catalogo((), 10_000_000, False)
    um_dia = 24 * 3600
    assert not catalogo.vencido(cat, 10_000_000 - um_dia, "")
    assert catalogo.vencido(cat, 10_000_000 - um_dia - 1, "")


@pytest.mark.parametrize("appid", ["", "..\\x", "../x", "57 0", "abc", "-5", "5.7", "²", "٣"])
def test_appid_que_nao_e_numero_nao_toca_disco_nem_rede(monkeypatch, schema, appid):
    schema.set_string("conquistas-chave-steam", "abc")
    pedidos = _sem_pedidos(monkeypatch)
    assert catalogo.obter(appid, "", agora=10) == catalogo.Renovacao(None)
    assert catalogo.renovar(appid, "", agora=10) == catalogo.Renovacao(None)
    assert pedidos == []
    assert not (shared.conquistas_cache_dir).exists() or not list(
        shared.conquistas_cache_dir.glob("**/*")
    )


def test_gravar_cache_nao_deixa_temporario_para_tras(monkeypatch):
    def travado(self, destino):
        raise PermissionError("travado")

    monkeypatch.setattr(Path, "replace", travado)
    with pytest.raises(OSError):
        catalogo._gravar_cache("570", Catalogo((INFO,), 1, False))
    assert list(shared.conquistas_cache_dir.glob("*")) == []


def test_gravar_cache_tem_um_temporario_por_gravacao(monkeypatch):
    nomes = []
    original = Path.write_text

    def espiar(self, *args, **kwargs):
        nomes.append(self.name)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", espiar)
    catalogo._gravar_cache("570", Catalogo((INFO,), 1, False))
    catalogo._gravar_cache("570", Catalogo((INFO,), 2, False))
    assert len(set(nomes)) == 2 and all(n.endswith(".tmp") for n in nomes)


def test_steam_settings_fundo_demais_nao_levanta(tmp_path):
    arquivo = tmp_path / "achievements.json"
    arquivo.write_text("[" * 100000, encoding="utf-8")
    assert catalogo.ler_steam_settings(arquivo) == []
