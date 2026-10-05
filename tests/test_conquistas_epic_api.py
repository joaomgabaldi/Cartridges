"""A API da Epic: consultas registradas na loja, biblioteca, com rede falsa."""

import json
import time
from pathlib import Path

import pytest
import requests

from cartridges import shared
from cartridges.conquistas import catalogo
from cartridges.conquistas.epic import api, conta
from tests.apoio_xbox import Resposta

_DADOS = Path(__file__).parent / "dados" / "epic"


def _dado(nome):
    return json.loads((_DADOS / nome).read_text(encoding="utf-8"))


def _catalogo(*itens, produto="p1"):
    return {"data": {"Achievement": {"productAchievementsRecordBySandbox": {
        "productId": produto, "achievements": [{"achievement": item} for item in itens]}}}}


def _progresso(*itens, relacao="SELF", tipo="PlayerProductAchievementsResponseSuccess"):
    resultado = {"__typename": tipo}
    if tipo == "PlayerProductAchievementsResponseSuccess":
        resultado["data"] = {"playerAchievements": [{"playerAchievement": item} for item in itens]}
    return {"data": {"PlayerProfile": {"playerProfile": {"relationship": relacao, "productAchievements": resultado}}}}


def _conquista(nome="ACH_1", **campos):
    base = {
        "name": nome, "hidden": False,
        "unlockedDisplayName": "Primeira", "lockedDisplayName": "???",
        "unlockedDescription": "Fez algo", "lockedDescription": "Faça algo",
        "unlockedIconLink": "https://cdn.epic/a.png", "lockedIconLink": "https://cdn.epic/a-cinza.png",
        "rarity": {"percent": 42.5},
    }
    return {**base, **campos}


class _SemLimite:
    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


@pytest.fixture
def rede(monkeypatch):
    """Cada pedido devolve o próximo item de `respostas` (uma exceção é levantada)."""
    estado = {"respostas": [], "pedidos": []}
    monkeypatch.setattr(conta, "conectada", lambda: True)
    monkeypatch.setattr(conta, "account_id", lambda: "c" * 32)
    monkeypatch.setattr(conta, "autorizacao", lambda forcar=False: "A2" if forcar else "A1")
    monkeypatch.setattr(api, "_limite", lambda: _SemLimite())

    def requisitar(metodo, url, **kwargs):
        estado["pedidos"].append((metodo, url, kwargs))
        resposta = estado["respostas"].pop(0)
        if isinstance(resposta, BaseException):
            raise resposta
        return resposta

    monkeypatch.setattr(api, "_requisitar", requisitar)
    return estado


def test_ler_mapeia_e_guarda_o_catalogo(rede):
    rede["respostas"] = [
        Resposta(200, _catalogo(_conquista("ACH_1"), _conquista("ACH_2", hidden=True, rarity={"percent": 3}))),
        Resposta(200, _progresso({"achievementName": "ACH_1", "unlocked": True, "unlockDate": "2024-05-01T10:00:00.000Z"},
                                 {"achievementName": "ACH_2", "unlocked": False, "unlockDate": None})),
    ]
    leitura = api.ler("ns1")
    um, dois = leitura.catalogo.conquistas
    assert (um.nome, um.titulo, um.descricao, um.icone, um.icone_cinza, um.oculta, um.porcentagem) == (
        "EPIC:ACH_1", "Primeira", "Fez algo", "https://cdn.epic/a.png", "https://cdn.epic/a-cinza.png", False, 42.5
    )
    assert dois.oculta and dois.rara
    assert [(d.nome, d.quando) for d in leitura.desbloqueios] == [("EPIC:ACH_1", 1714557600)]
    assert catalogo.em_cache("epic-ns1").conquistas == leitura.catalogo.conquistas


def test_consultas_registradas_e_cookie_so_no_progresso(rede):
    rede["respostas"] = [Resposta(200, _catalogo(_conquista())), Resposta(200, _progresso())]
    api.ler("ns1")
    (m1, url1, kw1), (m2, url2, kw2) = rede["pedidos"]
    assert (m1, m2) == ("GET", "GET") and url1 == url2 == "https://store.epicgames.com/graphql"
    assert kw1["params"]["operationName"] == "Achievement"
    assert json.loads(kw1["params"]["variables"]) == {"sandboxId": "ns1", "locale": "pt-BR"}
    assert "9284d2fe" in kw1["params"]["extensions"]
    assert "Cookie" not in kw1["headers"] and kw1["headers"]["User-Agent"].startswith("Mozilla/5.0")
    assert kw2["params"]["operationName"] == "playerProfileAchievementsByProductId"
    assert json.loads(kw2["params"]["variables"]) == {"epicAccountId": "c" * 32, "productId": "p1"}
    assert kw2["headers"]["Cookie"] == "EPIC_EG1=A1"
    assert "Authorization" not in kw2["headers"]


def test_textos_bloqueados_sao_reserva(rede):
    rede["respostas"] = [
        Resposta(200, _catalogo(_conquista(unlockedDisplayName="", unlockedDescription=""))),
        Resposta(200, _progresso()),
    ]
    (info,) = api.ler("ns1").catalogo.conquistas
    assert (info.titulo, info.descricao) == ("???", "Faça algo")


def test_conquista_com_campo_errado_cai_sozinha(rede):
    rede["respostas"] = [
        Resposta(200, _catalogo(
            _conquista("BOA"),
            _conquista(123),
            _conquista("ICONE", unlockedIconLink="http://x/a.png", lockedIconLink="file:///c:/a.png"),
            _conquista("RARA", rarity={"percent": 300}),
            "não é dicionário",
        )),
        Resposta(200, _progresso({"achievementName": "BOA", "unlocked": True, "unlockDate": "data ruim"},
                                 {"achievementName": 5, "unlocked": True})),
    ]
    leitura = api.ler("ns1")
    assert [i.nome for i in leitura.catalogo.conquistas] == ["EPIC:BOA", "EPIC:ICONE", "EPIC:RARA"]
    icone = leitura.catalogo.conquistas[1]
    assert (icone.icone, icone.icone_cinza) == ("", "")
    assert leitura.catalogo.conquistas[2].porcentagem is None
    assert [(d.nome, d.quando) for d in leitura.desbloqueios] == [("EPIC:BOA", 0)]


def test_raridade_enorme_so_perde_a_porcentagem(rede):
    rede["respostas"] = [
        Resposta(200, _catalogo(_conquista("ENORME", rarity={"percent": 10**400}), _conquista("BOA"))),
        Resposta(200, _progresso()),
    ]
    enorme, boa = api.ler("ns1").catalogo.conquistas
    assert (enorme.nome, enorme.porcentagem) == ("EPIC:ENORME", None)
    assert (boa.nome, boa.porcentagem) == ("EPIC:BOA", 42.5)


def test_errors_e_none(rede):
    rede["respostas"] = [Resposta(200, {"errors": [{"message": "PersistedQueryNotFound"}], "data": None})]
    assert api.ler("ns1") is None


def test_jogo_sem_conquistas_e_catalogo_vazio_sem_pedir_progresso(rede):
    rede["respostas"] = [Resposta(200, {"data": {"Achievement": {"productAchievementsRecordBySandbox": {
        "productId": None, "achievements": None}}}})]
    leitura = api.ler("fn")
    assert leitura.catalogo.conquistas == () and leitura.desbloqueios == []
    assert len(rede["pedidos"]) == 1


def test_nunca_jogado_e_lista_vazia(rede):
    rede["respostas"] = [Resposta(200, _catalogo(_conquista())), Resposta(200, _dado("progresso-nunca-jogado.json"))]
    assert api.ler("ns1").desbloqueios == []


def test_conta_nao_reconhecida_renova_uma_vez(rede):
    rede["respostas"] = [
        Resposta(200, _catalogo(_conquista())),
        Resposta(200, _dado("progresso-sem-reconhecer.json")),
        Resposta(200, _progresso({"achievementName": "ACH_1", "unlocked": True, "unlockDate": None})),
    ]
    assert [d.nome for d in api.ler("ns1").desbloqueios] == ["EPIC:ACH_1"]
    assert rede["pedidos"][2][2]["headers"]["Cookie"] == "EPIC_EG1=A2"


def test_conta_nao_reconhecida_duas_vezes_e_none_sem_desconectar(rede, monkeypatch):
    recusas = []
    monkeypatch.setattr(conta, "recusada", lambda: recusas.append(1))
    sem = _dado("progresso-sem-reconhecer.json")
    rede["respostas"] = [Resposta(200, _catalogo(_conquista())), Resposta(200, sem), Resposta(200, sem)]
    assert api.ler("ns1") is None
    assert recusas == []


@pytest.mark.parametrize("resposta", [Resposta(429), Resposta(503), requests.ConnectionError("x")])
def test_falhas_de_rede(rede, resposta):
    rede["respostas"] = [resposta]
    with pytest.raises(api.FalhaDeRede):
        api.ler("ns1")


def test_resposta_que_nao_e_json_e_falha_de_rede(rede):
    rede["respostas"] = [Resposta(200)]
    with pytest.raises(api.FalhaDeRede):
        api.ler("ns1")


def test_outro_4xx_e_none(rede):
    rede["respostas"] = [Resposta(404)]
    assert api.ler("ns1") is None


def test_sem_conta_e_none(rede, monkeypatch):
    monkeypatch.setattr(conta, "autorizacao", lambda forcar=False: None)
    monkeypatch.setattr(conta, "conectada", lambda: False)
    rede["respostas"] = [Resposta(200, _catalogo(_conquista()))]
    assert api.ler("ns1") is None


def test_renovacao_que_falha_com_a_conta_conectada_e_falha_de_rede(rede, monkeypatch):
    monkeypatch.setattr(conta, "autorizacao", lambda forcar=False: None)
    rede["respostas"] = [Resposta(200, _catalogo(_conquista()))]
    with pytest.raises(api.FalhaDeRede):
        api.ler("ns1")


@pytest.mark.parametrize("ns", ["", "a b", "a" * 65, "../x", "ns:1"])
def test_namespace_invalido_nao_vai_a_rede(rede, ns):
    assert api.ler(ns) is None and api.desbloqueadas(ns) is None
    assert rede["pedidos"] == []


def test_desbloqueadas_usa_o_produto_guardado(rede):
    rede["respostas"] = [
        Resposta(200, _catalogo(_conquista(), produto="p9")),
        Resposta(200, _progresso()),
        Resposta(200, _progresso({"achievementName": "ACH_1", "unlocked": True, "unlockDate": None})),
    ]
    api.ler("ns1")
    assert [d.nome for d in api.desbloqueadas("ns1")] == ["EPIC:ACH_1"]
    assert len(rede["pedidos"]) == 3
    assert json.loads(rede["pedidos"][2][2]["params"]["variables"])["productId"] == "p9"


def test_desbloqueadas_sem_produto_busca_o_catalogo(rede):
    rede["respostas"] = [Resposta(200, _catalogo(_conquista(), produto="p9")), Resposta(200, _progresso())]
    assert api.desbloqueadas("ns2") == []
    assert [json.loads(p[2]["params"]["variables"]) for p in rede["pedidos"]][1]["productId"] == "p9"


def test_respostas_reais_da_prova(rede):
    rede["respostas"] = [Resposta(200, _dado("catalogo.json")), Resposta(200, _dado("progresso.json"))]
    leitura = api.ler("50118b7f954e450f8823df1614b24e80")
    nomes = {i.nome for i in leitura.catalogo.conquistas}
    assert len(nomes) == 6 and all(n.startswith("EPIC:") for n in nomes)
    assert "Valentão" in {i.titulo for i in leitura.catalogo.conquistas}
    assert any(i.rara for i in leitura.catalogo.conquistas)
    assert len(leitura.desbloqueios) == 3
    assert all(d.nome in nomes and d.quando > 1_700_000_000 for d in leitura.desbloqueios)


def test_nada_secreto_no_log(rede, caplog):
    caplog.set_level("DEBUG")
    rede["respostas"] = [Resposta(200, _catalogo(_conquista())), Resposta(503)]
    with pytest.raises(api.FalhaDeRede):
        api.ler("ns1")
    assert "A1" not in caplog.text and "c" * 32 not in caplog.text


# -- biblioteca ---------------------------------------------------------------


def _biblioteca(*pares, cursor=None):
    return {
        "responseMetadata": {"nextCursor": cursor},
        "records": [{"appName": app, "namespace": ns, "catalogItemId": "i"} for app, ns in pares],
    }


def test_biblioteca_acha_e_guarda(rede):
    rede["respostas"] = [
        Resposta(200, _biblioteca(("Fortnite", "fn"), cursor="c2")),
        Resposta(200, _biblioteca(("Sugar", "abc123"))),
    ]
    assert api.namespace_do_app("sugar") == "abc123"
    assert api.namespace_local_do_app("FORTNITE") == "fn"
    assert rede["pedidos"][0][2]["headers"]["Authorization"] == "bearer A1"
    assert rede["pedidos"][1][2]["params"]["cursor"] == "c2"


def test_biblioteca_401_renova_uma_vez(rede):
    rede["respostas"] = [Resposta(401), Resposta(200, _biblioteca(("Sugar", "abc123")))]
    assert api.namespace_do_app("Sugar") == "abc123"
    assert rede["pedidos"][1][2]["headers"]["Authorization"] == "bearer A2"


def test_biblioteca_recente_nao_busca_de_novo(rede):
    rede["respostas"] = [Resposta(200, _biblioteca(("Sugar", "abc123")))]
    assert api.namespace_do_app("Outro") == ""
    assert api.namespace_do_app("Outro") == ""
    assert len(rede["pedidos"]) == 1


def test_biblioteca_velha_busca_de_novo(rede):
    destino = shared.conquistas_cache_dir / "epic-biblioteca.json"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps({"apps": {"sugar": "abc123"}, "em": time.time() - 2 * 86400}), encoding="utf-8")
    rede["respostas"] = [Resposta(200, _biblioteca(("Sugar", "abc123"), ("Novo", "n1")))]
    assert api.namespace_do_app("Sugar") == "abc123"
    assert rede["pedidos"] == []
    assert api.namespace_do_app("Novo") == "n1"


def test_biblioteca_com_data_enorme_e_velha(rede):
    destino = shared.conquistas_cache_dir / "epic-biblioteca.json"
    destino.parent.mkdir(parents=True, exist_ok=True)
    # O texto direto: um inteiro de 400 dígitos continua inteiro e não cabe num float.
    destino.write_text('{"apps": {"sugar": "abc123"}, "em": ' + "9" * 400 + "}", encoding="utf-8")
    rede["respostas"] = [Resposta(200, _biblioteca(("Outro", "o1")))]
    assert api.namespace_local_do_app("Sugar") == "abc123"
    assert api.namespace_do_app("Outro") == "o1"
    assert len(rede["pedidos"]) == 1


def test_biblioteca_ilegivel_e_vazia(rede):
    destino = shared.conquistas_cache_dir / "epic-biblioteca.json"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text("{ruim", encoding="utf-8")
    assert api.namespace_local_do_app("Sugar") is None


def test_biblioteca_fora_do_formato_nao_grava(rede):
    rede["respostas"] = [Resposta(200, {"inesperado": True})]
    assert api.namespace_do_app("Sugar") is None
    assert not (shared.conquistas_cache_dir / "epic-biblioteca.json").exists()


def test_biblioteca_real_da_prova(rede):
    corpo = _dado("biblioteca.json")
    rede["respostas"] = [Resposta(200, corpo)]
    primeiro = corpo["records"][0]
    assert api.namespace_do_app(primeiro["appName"]) == primeiro["namespace"]
