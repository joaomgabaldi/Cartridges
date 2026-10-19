"""A API da EA: Juno, API antiga e caches, com rede falsa."""

import json
import time
from pathlib import Path

import pytest
import requests

from cartridges import shared
from cartridges.conquistas import catalogo
from cartridges.conquistas.ea import api, conta
from tests.apoio_xbox import Resposta

_DADOS = Path(__file__).parent / "dados" / "ea"
_CONJUNTO = "75158_193864_50844"
_TOKEN = "TOKEN-SECRETO-A1"
_PERSONA = "1234567890123"
_PSD = "PSD-SECRETO-777"


def _dado(nome):
    return json.loads((_DADOS / nome).read_text(encoding="utf-8"))


def _antiga(**achievements):
    return {"platform": "PC Origin", "name": "Jogo", "achievements": achievements}


def _item(**campos):
    base = {
        "complete": True, "hidden": False, "u": 1602194697, "achievedPercentage": "3.23",
        "name": "Titulo", "desc": "Descricao", "icons": {"208": "https://x.ea.com/a.png"},
    }
    return {**base, **campos}


def _juno_psd():
    return Resposta(200, {"data": {"me": {"player": {"psd": _PSD}}}})


class _SemLimite:
    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


@pytest.fixture
def rede(monkeypatch):
    """Cada pedido devolve o próximo item de `respostas` (uma exceção é levantada)."""
    estado = {"respostas": [], "pedidos": [], "forcou": 0, "recusados": []}
    monkeypatch.setattr(conta, "conectada", lambda: True)
    monkeypatch.setattr(conta, "persona", lambda: _PERSONA)

    def autorizacao(forcar=False, recusado=None):
        if forcar:
            estado["forcou"] += 1
            estado["recusados"].append(recusado)
            return "A2"
        return _TOKEN

    monkeypatch.setattr(conta, "autorizacao", autorizacao)
    monkeypatch.setattr(api, "_limite", lambda: _SemLimite())
    monkeypatch.setattr(api, "_psd", None)
    monkeypatch.setattr(api, "_acesso_ja_renovado", None)

    def requisitar(metodo, url, **kwargs):
        estado["pedidos"].append((metodo, url, kwargs))
        resposta = estado["respostas"].pop(0)
        if isinstance(resposta, BaseException):
            raise resposta
        return resposta

    monkeypatch.setattr(api, "_requisitar", requisitar)
    return estado


def _biblioteca_em_cache(titulos, em=None):
    destino = shared.conquistas_cache_dir / "ea-biblioteca.json"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps({"titulos": titulos, "em": time.time() if em is None else em}), encoding="utf-8")


# --- API antiga -------------------------------------------------------------


def test_ler_mapeia_o_conjunto(rede):
    rede["respostas"] = [Resposta(200, _dado("conjunto-swbf2.json"))]
    leitura = api.ler(_CONJUNTO)
    por_nome = {i.nome: i for i in leitura.catalogo.conquistas}
    assert set(por_nome) == {"EA:31", "EA:36", "EA:22", "EA:23", "EA:10"}
    info = por_nome["EA:31"]
    assert info.titulo == "Ignore seus instintos por seu próprio risco"
    assert info.descricao.startswith("Destrua 25 objetivos")
    assert info.icone == "https://achievements.gameservices.ea.com/achievements/icons/75158_193864_50844-31-208.png"
    assert info.icone_cinza == "" and info.oculta is False and info.porcentagem == 3.23
    assert isinstance(info.porcentagem, float)
    feitas = {(d.nome, d.quando) for d in leitura.desbloqueios}
    assert feitas == {("EA:31", 1602194697), ("EA:36", 1590515623)}


def test_bloqueada_ignora_u(rede):
    rede["respostas"] = [Resposta(200, _antiga(**{"1": _item(complete=False, u=1792106796)}))]
    leitura = api.ler("conj")
    assert [i.nome for i in leitura.catalogo.conquistas] == ["EA:1"]
    assert leitura.desbloqueios == []


def test_oculta_bloqueada(rede):
    rede["respostas"] = [Resposta(200, _dado("conjunto-swbf2.json"))]
    oculta = next(i for i in api.ler(_CONJUNTO).catalogo.conquistas if i.nome == "EA:10")
    assert oculta.oculta is True
    assert (oculta.titulo, oculta.descricao) == ("Conquista Escondida", "")


def test_oculta_bloqueada_esconde_o_texto_da_resposta(rede):
    rede["respostas"] = [Resposta(200, _antiga(**{"1": _item(complete=False, hidden=True, name="Segredo", desc="Spoiler")}))]
    (info,) = api.ler("conj").catalogo.conquistas
    assert (info.oculta, info.titulo, info.descricao) == (True, "Conquista Escondida", "")


def test_porcentagem_invalida_vira_none(rede):
    rede["respostas"] = [Resposta(200, _dado("conjunto-swbf2.json"))]
    por_nome = {i.nome: i for i in api.ler(_CONJUNTO).catalogo.conquistas}
    assert por_nome["EA:23"].porcentagem is None
    assert por_nome["EA:22"].porcentagem == 6.31


def test_tudo_zerado_e_sem_raridade(rede):
    itens = {str(n): _item(achievedPercentage="0.00") for n in (1, 2, 3)}
    rede["respostas"] = [Resposta(200, _antiga(**itens))]
    cat = api.ler("conj").catalogo
    assert all(i.porcentagem is None for i in cat.conquistas)
    assert cat.sem_raridade is True


def test_um_zero_entre_valores_reais_continua_zero(rede):
    rede["respostas"] = [Resposta(200, _antiga(**{
        "1": _item(achievedPercentage="0.00"), "2": _item(achievedPercentage="5.00"),
    }))]
    cat = api.ler("conj").catalogo
    assert [i.porcentagem for i in cat.conquistas] == [0.0, 5.0]
    assert cat.sem_raridade is False


@pytest.mark.parametrize("valor", ["150", "-1", "nan", "inf", 5, None])
def test_porcentagem_fora_da_faixa_vira_none(rede, valor):
    rede["respostas"] = [Resposta(200, _antiga(**{"1": _item(achievedPercentage=valor)}))]
    assert api.ler("conj").catalogo.conquistas[0].porcentagem is None


@pytest.mark.parametrize("icone", ["http://x/a.png", "file:///c:/a.png", 7, ""])
def test_icone_que_nao_e_https(rede, icone):
    rede["respostas"] = [Resposta(200, _antiga(**{"1": _item(icons={"208": icone})}))]
    assert api.ler("conj").catalogo.conquistas[0].icone == ""


def test_item_de_tipo_errado_descarta_so_ele(rede):
    rede["respostas"] = [Resposta(200, _antiga(**{
        "1": _item(), "2": "texto", "3": _item(name=5), "4": _item(desc=None), "5": _item(complete="sim"),
        "\ud800": _item(),
    }))]
    leitura = api.ler("conj")
    assert [i.nome for i in leitura.catalogo.conquistas] == ["EA:1"]


def test_u_fora_da_faixa_vira_zero(rede):
    rede["respostas"] = [Resposta(200, _antiga(**{
        "1": _item(u=2**70), "2": _item(u=100), "3": _item(u="x"), "4": _item(u=1602194697),
    }))]
    quando = {d.nome: d.quando for d in api.ler("conj").desbloqueios}
    assert quando == {"EA:1": 0, "EA:2": 0, "EA:3": 0, "EA:4": 1602194697}


def test_corpo_fora_do_formato_e_none(rede):
    rede["respostas"] = [Resposta(200, ["lista"])]
    assert api.ler("conj") is None


def test_conjunto_invalido_nao_vai_a_rede(rede):
    assert api.ler("a/b") is None and api.desbloqueadas("../x") is None
    assert rede["pedidos"] == []


def test_ler_grava_catalogo_ea(rede):
    rede["respostas"] = [Resposta(200, _dado("conjunto-swbf2.json"))]
    leitura = api.ler(_CONJUNTO)
    em_cache = catalogo.em_cache("ea-75158_193864_50844")
    assert em_cache is not None and em_cache.conquistas == leitura.catalogo.conquistas


def test_desbloqueadas_so_o_progresso(rede):
    rede["respostas"] = [Resposta(200, _dado("conjunto-swbf2.json"))]
    assert {d.nome for d in api.desbloqueadas(_CONJUNTO)} == {"EA:31", "EA:36"}


def test_pedido_da_antiga(rede):
    rede["respostas"] = [Resposta(200, _antiga())]
    api.ler(_CONJUNTO)
    ((metodo, url, kw),) = rede["pedidos"]
    assert metodo == "GET"
    assert url == f"https://achievements.gameservices.ea.com/achievements/personas/{_PERSONA}/{_CONJUNTO}/all"
    assert kw["params"] == {"lang": "pt_BR", "metadata": "true", "fullset": "true"}
    assert kw["headers"] == {
        "AuthToken": _TOKEN, "X-Api-Version": "2", "X-Application-Key": "Origin", "User-Agent": conta.UA,
    }


def test_sem_persona_e_none(rede, monkeypatch):
    monkeypatch.setattr(conta, "persona", lambda: None)
    assert api.ler("conj") is None and rede["pedidos"] == []


def test_401_renova_uma_vez(rede):
    rede["respostas"] = [Resposta(401), Resposta(200, _dado("conjunto-swbf2.json"))]
    assert api.ler(_CONJUNTO) is not None
    assert rede["forcou"] == 1
    assert rede["pedidos"][1][2]["headers"]["AuthToken"] == "A2"


def test_segundo_401_so_loga(rede, caplog):
    caplog.set_level("DEBUG")
    rede["respostas"] = [Resposta(401), Resposta(403)]
    assert api.ler(_CONJUNTO) is None
    assert rede["forcou"] == 1 and conta.conectada()
    # o segundo pedido foi com o token renovado, e a recusa dele só foi para o log
    assert [p[2]["headers"]["AuthToken"] for p in rede["pedidos"]] == [_TOKEN, "A2"]
    assert "EA: acesso recusado duas vezes" in caplog.text
    assert not any(r.levelname in ("WARNING", "ERROR") for r in caplog.records)


def test_renovacao_forcada_informa_o_token_recusado(rede):
    rede["respostas"] = [Resposta(401), Resposta(200, _dado("conjunto-swbf2.json"))]
    api.ler(_CONJUNTO)
    assert rede["recusados"] == [_TOKEN]


def test_recusa_persistente_forca_so_uma_renovacao(rede, monkeypatch):
    atual = {"token": _TOKEN}

    def autorizacao(forcar=False, recusado=None):
        if forcar:
            rede["forcou"] += 1
            atual["token"] = f"F{rede['forcou']}"
        return atual["token"]

    monkeypatch.setattr(conta, "autorizacao", autorizacao)
    rede["respostas"] = [Resposta(403), Resposta(403), Resposta(403)]
    assert api.ler(_CONJUNTO) is None
    assert api.ler(_CONJUNTO) is None
    assert rede["forcou"] == 1
    assert len(rede["pedidos"]) == 3


def test_sem_token_com_conta_e_falha_de_rede(rede, monkeypatch):
    monkeypatch.setattr(conta, "autorizacao", lambda forcar=False, recusado=None: None)
    with pytest.raises(api.FalhaDeRede):
        api.ler("conj")


def test_sem_token_sem_conta_e_none(rede, monkeypatch):
    monkeypatch.setattr(conta, "autorizacao", lambda forcar=False, recusado=None: None)
    monkeypatch.setattr(conta, "conectada", lambda: False)
    assert api.ler("conj") is None


@pytest.mark.parametrize("status", [429, 500, 503])
def test_429_e_5xx_sao_falha_de_rede(rede, status):
    rede["respostas"] = [Resposta(status)]
    with pytest.raises(api.FalhaDeRede):
        api.ler("conj")


def test_erro_do_requests_e_falha_de_rede(rede):
    rede["respostas"] = [requests.ConnectionError("https://x/?token=segredo")]
    with pytest.raises(api.FalhaDeRede):
        api.desbloqueadas("conj")


def test_nao_json_e_falha_de_rede(rede):
    rede["respostas"] = [Resposta(200)]
    with pytest.raises(api.FalhaDeRede):
        api.ler("conj")


def test_outro_4xx_e_none(rede):
    rede["respostas"] = [Resposta(404)]
    assert api.ler("conj") is None


# --- Juno -------------------------------------------------------------------


def test_juno_com_errors_devolve_none(rede, caplog):
    caplog.set_level("DEBUG")
    rede["respostas"] = [Resposta(200, {"errors": [{"message": f"ruim {_PSD}"}], "data": None})]
    assert api.conjunto_da_oferta("Origin.OFR.50.0002148") is None
    assert _PSD not in caplog.text


def test_conjunto_da_oferta(rede):
    rede["respostas"] = [_juno_psd(), Resposta(200, _dado("juno-conjunto.json"))]
    assert api.conjunto_da_oferta("Origin.OFR.50.0002148") == _CONJUNTO
    (m1, u1, k1), (m2, u2, k2) = rede["pedidos"]
    assert (m1, m2) == ("POST", "POST") and u1 == u2 == api.JUNO
    assert k1["headers"]["Authorization"] == f"Bearer {_TOKEN}"
    assert "psd" in k1["json"]["query"] and "variables" not in k1["json"]
    consulta = k2["json"]
    assert consulta["variables"] == {"o": "Origin.OFR.50.0002148", "p": _PSD}
    assert "Origin.OFR" not in consulta["query"] and _PSD not in consulta["query"]
    assert "$o: String!" in consulta["query"] and "$p: String!" in consulta["query"]
    assert 'locale: "pt-BR"' in consulta["query"] and "showHidden: true" in consulta["query"]


def test_conjunto_da_oferta_sem_conquistas(rede):
    rede["respostas"] = [_juno_psd(), Resposta(200, {"data": {"achievements": []}})]
    assert api.conjunto_da_oferta("Origin.OFR.50.0001108") == ""


def test_conjunto_da_oferta_pula_id_invalido(rede):
    rede["respostas"] = [_juno_psd(), Resposta(200, {"data": {"achievements": [{"id": ""}, {"id": "a/b"}, {"id": "ok_1"}]}})]
    assert api.conjunto_da_oferta("O") == "ok_1"


def test_psd_fica_na_memoria_enquanto_o_token_nao_muda(rede):
    rede["respostas"] = [_juno_psd(), Resposta(200, {"data": {"achievements": []}}), Resposta(200, {"data": {"achievements": []}})]
    api.conjunto_da_oferta("A")
    api.conjunto_da_oferta("B")
    assert len(rede["pedidos"]) == 3  # um psd e duas ofertas


def test_juno_401_renova_uma_vez(rede):
    rede["respostas"] = [_juno_psd(), Resposta(401), Resposta(200, {"data": {"achievements": []}})]
    assert api.conjunto_da_oferta("A") == ""
    assert rede["forcou"] == 1
    assert rede["pedidos"][2][2]["headers"]["Authorization"] == "Bearer A2"


def test_psd_de_outro_token_e_esquecido(rede, monkeypatch):
    monkeypatch.setattr(api, "_psd", ("token-velho", "PSD-VELHO"))
    rede["respostas"] = [_juno_psd(), Resposta(200, {"data": {"achievements": []}})]
    api.conjunto_da_oferta("A")
    assert rede["pedidos"][1][2]["json"]["variables"]["p"] == _PSD


def test_juno_sem_psd_e_none(rede):
    rede["respostas"] = [Resposta(200, {"data": {"me": {"player": None}}})]
    assert api.conjunto_da_oferta("A") is None


# --- biblioteca -------------------------------------------------------------


def test_ofertas_busca_e_guarda_a_biblioteca(rede):
    rede["respostas"] = [Resposta(200, _dado("biblioteca.json"))]
    assert api.ofertas("starwarsbattlefrontii") == ["Origin.OFR.50.0002148"]
    consulta = rede["pedidos"][0][2]["json"]["query"]
    assert "ownedGameProducts" in consulta and "paging: {limit: 9999}" in consulta
    guardado = json.loads((shared.conquistas_cache_dir / "ea-biblioteca.json").read_text(encoding="utf-8"))
    assert set(guardado) == {"titulos", "em"}
    assert guardado["titulos"]["starwarsbattlefrontii"] == ["Origin.OFR.50.0002148"]
    assert len(guardado["titulos"]["battlefield4"]) == 2  # duas ofertas, ordem preservada
    assert guardado["titulos"]["battlefield4"] == ["OFB-EAST:109552316", "OFB-EAST:109552155"]
    assert len(guardado["titulos"]) == 4  # o item com `product: null` fica de fora


def test_ofertas_do_cache_novo_sem_rede(rede):
    _biblioteca_em_cache({"jogo": ["O1", "O2"]})
    assert api.ofertas("jogo") == ["O1", "O2"]
    assert rede["pedidos"] == []


def test_ofertas_falta_com_cache_novo_e_lista_vazia_sem_rede(rede):
    _biblioteca_em_cache({"jogo": ["O1"]})
    assert api.ofertas("outro") == []
    assert rede["pedidos"] == []


def test_ofertas_falta_com_cache_velho_rebusca(rede):
    _biblioteca_em_cache({"jogo": ["O1"]}, em=time.time() - 2 * 86400)
    rede["respostas"] = [Resposta(200, _dado("biblioteca.json"))]
    assert api.ofertas("dragonageinquisition") == ["Origin.OFR.50.0001108"]
    assert len(rede["pedidos"]) == 1


def test_ofertas_rebusca_e_ainda_faltando_e_lista_vazia(rede):
    rede["respostas"] = [Resposta(200, _dado("biblioteca.json"))]
    assert api.ofertas("naoexiste") == []
    assert api.ofertas("naoexiste") == []  # o cache regravado é novo: sem segunda busca
    assert len(rede["pedidos"]) == 1


def test_ofertas_sem_conta_none(rede, monkeypatch):
    monkeypatch.setattr(conta, "autorizacao", lambda forcar=False, recusado=None: None)
    monkeypatch.setattr(conta, "conectada", lambda: False)
    assert api.ofertas("jogo") is None


def test_ofertas_cache_ilegivel_rebusca(rede):
    destino = shared.conquistas_cache_dir / "ea-biblioteca.json"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text("{não é json", encoding="utf-8")
    rede["respostas"] = [Resposta(200, _dado("biblioteca.json"))]
    assert api.ofertas("starwarsbattlefrontii") == ["Origin.OFR.50.0002148"]


def test_ofertas_biblioteca_fora_do_formato_e_none(rede):
    rede["respostas"] = [Resposta(200, {"data": {"me": None}})]
    assert api.ofertas("jogo") is None


def test_ofertas_com_errors_e_none(rede):
    rede["respostas"] = [Resposta(200, {"errors": [{"message": "x"}]})]
    assert api.ofertas("jogo") is None


# --- ea-jogos.json ----------------------------------------------------------


def test_conjunto_guardado_e_guardar():
    assert api.conjunto_guardado("c:\\jogos\\bf6\\") is None
    api.guardar_conjunto("c:\\jogos\\bf6\\", _CONJUNTO)
    assert api.conjunto_guardado("c:\\jogos\\bf6\\") == _CONJUNTO
    assert api.conjunto_guardado("c:\\outro\\") is None


def test_conjunto_guardado_vazio_vence_em_1_dia(monkeypatch):
    api.guardar_conjunto("pasta", "")
    assert api.conjunto_guardado("pasta") == ""
    agora = time.time()
    monkeypatch.setattr(api.time, "time", lambda: agora + 2 * 86400)
    assert api.conjunto_guardado("pasta") is None


def test_conjunto_guardado_valido_vale_sempre(monkeypatch):
    api.guardar_conjunto("pasta", "abc_1")
    agora = time.time()
    monkeypatch.setattr(api.time, "time", lambda: agora + 400 * 86400)
    assert api.conjunto_guardado("pasta") == "abc_1"


def test_guardar_conjunto_preserva_os_outros_e_ignora_invalido():
    api.guardar_conjunto("a", "x1")
    api.guardar_conjunto("b", "y2")
    api.guardar_conjunto("c", "tem/barra")
    assert (api.conjunto_guardado("a"), api.conjunto_guardado("b"), api.conjunto_guardado("c")) == ("x1", "y2", None)


def test_conjunto_guardado_arquivo_ruim_e_none():
    destino = shared.conquistas_cache_dir / "ea-jogos.json"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text('{"pasta": 5, "p2": {"conjunto": 3, "em": 1}}', encoding="utf-8")
    assert api.conjunto_guardado("pasta") is None and api.conjunto_guardado("p2") is None


# --- helpers e log ----------------------------------------------------------


def test_conjunto_valido_e_chave():
    assert api.conjunto_valido("75158_193864_50844") and api.conjunto_valido("a-B_9")
    assert not any(api.conjunto_valido(v) for v in ("", "a/b", "x" * 65, None, 5, "a b"))
    assert api.chave_do_catalogo("abc") == "ea-abc" and api.PREFIXO == "EA:"


def test_limitador():
    assert (api.EaLimiter.refill_period_seconds, api.EaLimiter.refill_period_tokens, api.EaLimiter.burst_tokens) == (60, 30, 10)


def test_nada_sensivel_no_log(rede, caplog):
    caplog.set_level("DEBUG")
    rede["respostas"] = [
        Resposta(200, _dado("biblioteca.json")),
        requests.ConnectionError(f"https://x/{_PERSONA}?t={_TOKEN}"),
        Resposta(401), Resposta(401),
        _juno_psd(), Resposta(200, {"errors": [{"message": _PSD}]}),
    ]
    api.ofertas("starwarsbattlefrontii")
    with pytest.raises(api.FalhaDeRede):
        api.ler("conj")
    api.ler("conj")
    api.conjunto_da_oferta("O")
    for segredo in (_TOKEN, "A2", _PERSONA, _PSD, "Battlefront", "Dragon Age", "Battlefield"):
        assert segredo not in caplog.text
