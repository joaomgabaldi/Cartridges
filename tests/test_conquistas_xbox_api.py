"""A API do Xbox: titleId, catálogo + progresso, cache e erros."""

import json
from pathlib import Path

import pytest
import requests

from cartridges import shared
from cartridges.conquistas import catalogo
from cartridges.conquistas.formatos import Desbloqueio
from cartridges.conquistas.xbox import api, conta
from tests.apoio_xbox import Resposta, rede_falsa

_DADOS = Path(__file__).parent / "dados" / "xbox" / "conquistas.json"
_ACH = "https://achievements.xboxlive.com"
_HUB = "https://titlehub.xboxlive.com"


@pytest.fixture(autouse=True)
def conectado(monkeypatch):
    monkeypatch.setattr(conta, "autorizacao", lambda forcar=False: ("UHS", "XSTS"))
    monkeypatch.setattr(conta, "xuid", lambda: "2535400000000000")
    monkeypatch.setattr(conta, "conectada", lambda: False)
    monkeypatch.setattr(api, "_limite", lambda: _SemLimite())


class _SemLimite:
    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


def _conquista(id_, nome="Nome", conseguida=False, quando="2026-10-01T12:00:00.0000000Z", **extra):
    item = {
        "id": id_,
        "name": nome,
        "description": f"Descrição {id_}",
        "lockedDescription": f"Bloqueada {id_}",
        "isSecret": False,
        "progressState": "Achieved" if conseguida else "NotStarted",
        "progression": {"timeUnlocked": quando if conseguida else "0001-01-01T00:00:00.0000000Z"},
        "mediaAssets": [{"name": "i", "type": "Icon", "url": f"https://images-eds-ssl.xboxlive.com/{id_}.png"}],
        "rarity": {"currentCategory": "Rare", "currentPercentage": 4.5},
    }
    item.update(extra)
    return item


def _pagina(itens, continuar=None):
    return Resposta(200, {"achievements": itens, "pagingInfo": {"continuationToken": continuar, "totalRecords": len(itens)}})


def test_contrato_e_o_que_a_prova_aprovou():
    assert api.CONTRATO == "4"
    assert api.PREFIXO == "XBOX:"
    assert api.chave_do_catalogo("123") == "xbox-123"


def test_resposta_real_da_prova(monkeypatch):
    corpo = json.loads(_DADOS.read_text(encoding="utf-8"))
    rede_falsa(monkeypatch, api, {_ACH: [Resposta(200, corpo)]}, nome="_requisitar")
    leitura = api.ler("123")
    assert leitura is not None and leitura.catalogo.conquistas
    assert all(info.nome.startswith("XBOX:") for info in leitura.catalogo.conquistas)
    assert all(d.nome.startswith("XBOX:") and d.quando > 0 for d in leitura.desbloqueios)
    assert catalogo.em_cache("xbox-123") == leitura.catalogo
    # Ícones reais são https com query; porcentagem vem do contrato 4.
    assert all(info.icone.startswith("https://images-eds-ssl.xboxlive.com/image?url=") for info in leitura.catalogo.conquistas)
    assert any(info.porcentagem is not None for info in leitura.catalogo.conquistas)
    assert not leitura.catalogo.sem_raridade


def test_so_achieved_vira_desbloqueio_na_resposta_real(monkeypatch):
    """A prova: `unlockedOnly=true` também devolve InProgress; ela não entra."""
    corpo = json.loads(_DADOS.read_text(encoding="utf-8"))
    estados = [item["progressState"] for item in corpo["achievements"]]
    assert estados.count("Achieved") == 3 and estados.count("InProgress") == 1
    achieved = {f"XBOX:{item['id']}" for item in corpo["achievements"] if item["progressState"] == "Achieved"}
    em_progresso = {f"XBOX:{item['id']}" for item in corpo["achievements"] if item["progressState"] == "InProgress"}

    # A API devolveria só as desbloqueadas e as em progresso.
    corpo["achievements"] = [i for i in corpo["achievements"] if i["progressState"] in ("Achieved", "InProgress")]
    rede_falsa(monkeypatch, api, {_ACH: [Resposta(200, corpo), Resposta(200, corpo)]}, nome="_requisitar")

    lidas = api.desbloqueadas("123")
    assert {d.nome for d in lidas} == achieved and len(lidas) == 3
    assert not ({d.nome for d in lidas} & em_progresso)
    assert all(d.quando > 0 for d in lidas)

    assert {d.nome for d in api.ler("123").desbloqueios} == achieved


def test_mapeamento(monkeypatch):
    itens = [_conquista("1", "Primeira", True), _conquista("2", "Segredo", isSecret=True, description="")]
    rede_falsa(monkeypatch, api, {_ACH: [_pagina(itens)]}, nome="_requisitar")
    leitura = api.ler("123")
    um, dois = leitura.catalogo.conquistas
    assert (um.nome, um.titulo, um.descricao, um.oculta) == ("XBOX:1", "Primeira", "Descrição 1", False)
    assert um.icone == "https://images-eds-ssl.xboxlive.com/1.png" and um.icone_cinza == ""
    assert (dois.oculta, dois.descricao) == (True, "Bloqueada 2")
    assert leitura.desbloqueios == [Desbloqueio("XBOX:1", 1790856000)]
    if api.CONTRATO == "4":
        assert um.porcentagem == 4.5 and um.rara
    else:
        assert um.porcentagem is None


@pytest.mark.parametrize("rarity", [None, {}, {"currentPercentage": True}, {"currentPercentage": float("nan")},
                                    {"currentPercentage": float("inf")}, {"currentPercentage": -1},
                                    {"currentPercentage": 100.5}, {"currentPercentage": "4"}, "x"])
def test_raridade_estranha_fica_sem_porcentagem(monkeypatch, rarity):
    rede_falsa(monkeypatch, api, {_ACH: [_pagina([_conquista("1", rarity=rarity)])]}, nome="_requisitar")
    leitura = api.ler("1")
    assert leitura.catalogo.conquistas[0].porcentagem is None
    assert leitura.catalogo.sem_raridade


def test_cabecalhos(monkeypatch):
    chamadas = rede_falsa(monkeypatch, api, {_ACH: [_pagina([])]}, nome="_requisitar")
    api.ler("123")
    _url, kwargs = chamadas[0]
    cab = kwargs["headers"]
    assert cab["Authorization"] == "XBL3.0 x=UHS;XSTS"
    assert cab["x-xbl-contract-version"] == api.CONTRATO
    assert cab["Accept-Language"].startswith("pt-BR")
    assert kwargs["params"]["titleId"] == "123"


@pytest.mark.parametrize("quando", ["lixo", "0001-01-01T00:00:00Z", "1969-12-31T23:59:59Z", None, 5])
def test_data_invalida_vira_sem_data(monkeypatch, quando):
    item = _conquista("1", conseguida=True)
    item["progression"]["timeUnlocked"] = quando
    rede_falsa(monkeypatch, api, {_ACH: [_pagina([item])]}, nome="_requisitar")
    assert api.ler("1").desbloqueios == [Desbloqueio("XBOX:1", 0)]


def test_data_real_com_sete_casas_e_z(monkeypatch):
    item = _conquista("1", conseguida=True, quando="2026-08-06T01:15:55.7870000Z")
    rede_falsa(monkeypatch, api, {_ACH: [_pagina([item])]}, nome="_requisitar")
    assert api.ler("1").desbloqueios == [Desbloqueio("XBOX:1", 1785978955)]


@pytest.mark.parametrize("url", ["http://x/i.png", "file:///C:/x.png", "C:\\x.png", 5, ""])
def test_icone_que_nao_e_https_cai(monkeypatch, url):
    item = _conquista("1", mediaAssets=[{"type": "Icon", "url": url}])
    rede_falsa(monkeypatch, api, {_ACH: [_pagina([item])]}, nome="_requisitar")
    assert api.ler("1").catalogo.conquistas[0].icone == ""


def test_conquista_com_campo_errado_cai_sozinha(monkeypatch):
    ruins = [_conquista(5), _conquista("2", name=["x"]), "texto", _conquista("", "Sem id")]
    rede_falsa(monkeypatch, api, {_ACH: [_pagina([_conquista("1"), *ruins])]}, nome="_requisitar")
    assert [i.nome for i in api.ler("1").catalogo.conquistas] == ["XBOX:1"]


def test_paginas(monkeypatch):
    chamadas = rede_falsa(
        monkeypatch, api,
        {_ACH: [_pagina([_conquista("1")], "T2"), _pagina([_conquista("2")])]},
        nome="_requisitar",
    )
    assert [i.nome for i in api.ler("1").catalogo.conquistas] == ["XBOX:1", "XBOX:2"]
    assert chamadas[1][1]["params"]["continuationToken"] == "T2"


def test_paginas_tem_limite(monkeypatch):
    infinitas = [_pagina([_conquista(str(n))], "mais") for n in range(30)]
    chamadas = rede_falsa(monkeypatch, api, {_ACH: infinitas}, nome="_requisitar")
    assert api.ler("1") is not None
    assert len(chamadas) == 10


@pytest.mark.parametrize("corpo", [None, [], {"achievements": "x"}, {"outra": 1}])
def test_resposta_invalida_e_none(monkeypatch, corpo):
    rede_falsa(monkeypatch, api, {_ACH: [Resposta(200, corpo)]}, nome="_requisitar")
    if corpo is None:
        with pytest.raises(api.FalhaDeRede):
            api.ler("1")
    else:
        assert api.ler("1") is None


@pytest.mark.parametrize("status", [429, 500, 503])
def test_status_de_rede(monkeypatch, status):
    rede_falsa(monkeypatch, api, {_ACH: [Resposta(status, {})]}, nome="_requisitar")
    with pytest.raises(api.FalhaDeRede):
        api.ler("1")


def test_outro_4xx_e_none(monkeypatch):
    rede_falsa(monkeypatch, api, {_ACH: [Resposta(403, {})]}, nome="_requisitar")
    assert api.ler("1") is None


def test_rede_fora(monkeypatch):
    rede_falsa(monkeypatch, api, {}, nome="_requisitar")
    with pytest.raises(api.FalhaDeRede):
        api.ler("1")


def test_falha_de_rede_nao_loga_a_mensagem_da_excecao(monkeypatch, caplog):
    erro = requests.ConnectionError("https://achievements.xboxlive.com/segredo?token=ABC")
    rede_falsa(monkeypatch, api, {_ACH: [erro]}, nome="_requisitar")
    with caplog.at_level("DEBUG"):
        with pytest.raises(api.FalhaDeRede):
            api.ler("1")
    assert "segredo" not in caplog.text and "ABC" not in caplog.text and "XSTS" not in caplog.text
    assert "ConnectionError" in caplog.text


def test_401_renova_uma_vez(monkeypatch):
    forcadas = []
    monkeypatch.setattr(conta, "autorizacao", lambda forcar=False: forcadas.append(forcar) or ("U", "X"))
    rede_falsa(monkeypatch, api, {_ACH: [Resposta(401, {}), _pagina([_conquista("1")])]}, nome="_requisitar")
    assert api.ler("1") is not None
    assert forcadas == [False, True]


def test_401_duas_vezes_desconecta(monkeypatch):
    recusas = []
    monkeypatch.setattr(conta, "recusada", lambda: recusas.append(1))
    rede_falsa(monkeypatch, api, {_ACH: [Resposta(401, {}), Resposta(401, {})]}, nome="_requisitar")
    assert api.ler("1") is None
    assert recusas == [1]


def test_401_e_renovacao_sem_conta_e_none(monkeypatch):
    monkeypatch.setattr(conta, "autorizacao", lambda forcar=False: None if forcar else ("U", "X"))
    recusas = []
    monkeypatch.setattr(conta, "recusada", lambda: recusas.append(1))
    rede_falsa(monkeypatch, api, {_ACH: [Resposta(401, {})]}, nome="_requisitar")
    assert api.ler("1") is None and recusas == []


def test_sem_conta_nao_vai_a_rede(monkeypatch):
    monkeypatch.setattr(conta, "autorizacao", lambda forcar=False: None)
    chamadas = rede_falsa(monkeypatch, api, {}, nome="_requisitar")
    assert api.ler("1") is None and api.desbloqueadas("1") is None
    assert api.titulo("Pkg_x", []) is None
    assert chamadas == []


def test_renovacao_que_falhou_com_a_conta_conectada_e_falha_de_rede(monkeypatch):
    """`conta.autorizacao` devolve None quando a renovação cai por rede: a conta segue
    conectada, e quem varre precisa do `FalhaDeRede` para acionar o disjuntor."""
    monkeypatch.setattr(conta, "autorizacao", lambda forcar=False: None)
    monkeypatch.setattr(conta, "conectada", lambda: True)
    chamadas = rede_falsa(monkeypatch, api, {}, nome="_requisitar")
    with pytest.raises(api.FalhaDeRede):
        api.ler("1")
    with pytest.raises(api.FalhaDeRede):
        api.desbloqueadas("1")
    with pytest.raises(api.FalhaDeRede):
        api.titulo("Pkg_x", [])
    assert chamadas == []


def test_renovacao_forcada_apos_401_que_falha_com_a_conta_conectada(monkeypatch):
    monkeypatch.setattr(conta, "autorizacao", lambda forcar=False: None if forcar else ("U", "X"))
    monkeypatch.setattr(conta, "conectada", lambda: True)
    recusas = []
    monkeypatch.setattr(conta, "recusada", lambda: recusas.append(1))
    rede_falsa(monkeypatch, api, {_ACH: [Resposta(401, {})]}, nome="_requisitar")
    with pytest.raises(api.FalhaDeRede):
        api.ler("1")
    assert recusas == []


def test_segundo_401_desconecta_e_e_none_mesmo_conectada(monkeypatch):
    monkeypatch.setattr(conta, "conectada", lambda: True)
    monkeypatch.setattr(conta, "recusada", lambda: None)
    rede_falsa(monkeypatch, api, {_ACH: [Resposta(401, {}), Resposta(401, {})]}, nome="_requisitar")
    assert api.ler("1") is None


def test_sem_xuid_e_none(monkeypatch):
    monkeypatch.setattr(conta, "xuid", lambda: None)
    chamadas = rede_falsa(monkeypatch, api, {}, nome="_requisitar")
    assert api.ler("1") is None and api.desbloqueadas("1") is None
    assert chamadas == []


def test_desbloqueadas_pede_so_as_desbloqueadas_e_nao_mexe_no_cache(monkeypatch):
    chamadas = rede_falsa(monkeypatch, api, {_ACH: [_pagina([_conquista("1", conseguida=True)])]}, nome="_requisitar")
    assert api.desbloqueadas("9") == [Desbloqueio("XBOX:1", 1790856000)]
    assert chamadas[0][1]["params"]["unlockedOnly"] == "true"
    assert catalogo.em_cache("xbox-9") is None


def test_desbloqueadas_ignora_o_que_nao_e_achieved(monkeypatch):
    itens = [_conquista("1", conseguida=True), _conquista("2", progressState="InProgress")]
    rede_falsa(monkeypatch, api, {_ACH: [_pagina(itens)]}, nome="_requisitar")
    assert api.desbloqueadas("9") == [Desbloqueio("XBOX:1", 1790856000)]


def test_cache_que_nao_grava_nao_derruba_a_leitura(monkeypatch):
    def falha(_chave, _cat):
        raise OSError("disco cheio")

    monkeypatch.setattr(catalogo, "guardar", falha)
    rede_falsa(monkeypatch, api, {_ACH: [_pagina([_conquista("1")])]}, nome="_requisitar")
    assert api.ler("1") is not None


def test_surrogate_solto_no_id_derruba_so_a_conquista(monkeypatch):
    itens = [
        _conquista("1", "Boa", True),
        _conquista("\ud800", "Id ruim", True),
        _conquista("3", "Terceira", True),
    ]
    rede_falsa(monkeypatch, api, {_ACH: [_pagina(itens)]}, nome="_requisitar")
    leitura = api.ler("1")
    assert [i.nome for i in leitura.catalogo.conquistas] == ["XBOX:1", "XBOX:3"]
    assert [d.nome for d in leitura.desbloqueios] == ["XBOX:1", "XBOX:3"]
    assert catalogo.em_cache("xbox-1") == leitura.catalogo
    rede_falsa(monkeypatch, api, {_ACH: [_pagina(itens)]}, nome="_requisitar")
    assert [d.nome for d in api.desbloqueadas("1")] == ["XBOX:1", "XBOX:3"]


def test_surrogate_solto_no_texto_e_trocado_e_o_cache_grava(monkeypatch):
    itens = [
        _conquista("1", "Nome\ud800ruim", True, description="Desc\udfffruim"),
        _conquista("2", "\ud800", lockedDescription="\ud800", description=""),
        _conquista("3", mediaAssets=[{"type": "Icon", "url": "https://x/\ud800.png"}]),
    ]
    rede_falsa(monkeypatch, api, {_ACH: [_pagina(itens)]}, nome="_requisitar")
    leitura = api.ler("1")
    um, dois, tres = leitura.catalogo.conquistas
    assert (um.titulo, um.descricao) == ("Nome?ruim", "Desc?ruim")
    assert dois.titulo == "?" and dois.descricao == "?"
    assert tres.icone == ""
    assert leitura.desbloqueios == [Desbloqueio("XBOX:1", 1790856000)]
    assert catalogo.em_cache("xbox-1") == leitura.catalogo


def test_cache_que_nao_grava_por_valueerror_nao_derruba_a_leitura(monkeypatch):
    def falha(_chave, _cat):
        raise UnicodeEncodeError("utf-8", "x", 0, 1, "surrogate")

    monkeypatch.setattr(catalogo, "guardar", falha)
    rede_falsa(monkeypatch, api, {_ACH: [_pagina([_conquista("1")])]}, nome="_requisitar")
    assert api.ler("1") is not None


def _config(pasta: Path, titulo: str) -> None:
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / "MicrosoftGame.config").write_text(
        f'<?xml version="1.0"?><Game configVersion="1"><TitleId>{titulo}</TitleId></Game>',
        encoding="utf-8",
    )


def test_titulo_pelo_config_em_hex(tmp_path):
    _config(tmp_path / "Content", "1A2B3C4D")
    assert api.titulo_local(None, [tmp_path / "Content"]) == str(0x1A2B3C4D)


@pytest.mark.parametrize("conteudo", ["<Game><TitleId>XYZ</TitleId></Game>", "nao e xml", "<Game/>",
                                      "<Game><TitleId>123456789</TitleId></Game>"])
def test_config_ruim_e_ignorado(tmp_path, conteudo):
    (tmp_path / "MicrosoftGame.config").write_text(conteudo, encoding="utf-8")
    assert api.titulo_local(None, [tmp_path]) is None


def test_config_grande_demais_e_ignorado(tmp_path):
    (tmp_path / "MicrosoftGame.config").write_text(
        "<Game><TitleId>1A</TitleId><!--" + "x" * (2 * 1024 * 1024) + "--></Game>", encoding="utf-8"
    )
    assert api.titulo_local(None, [tmp_path]) is None


def test_titulo_pelo_titlehub_e_cache(monkeypatch):
    chamadas = rede_falsa(monkeypatch, api, {_HUB: [Resposta(200, {"titles": [{"titleId": "1234", "pfn": "Pkg_abc"}]})]}, nome="_requisitar")
    assert api.titulo("Pkg_abc", []) == "1234"
    assert chamadas[0][1]["json"] == {"pfns": ["Pkg_abc"], "windowsPhoneProductIds": []}
    assert api.titulo_local("Pkg_abc", []) == "1234"
    assert api.titulo("Pkg_abc", []) == "1234" and len(chamadas) == 1


def test_titlehub_procura_o_pfn_pedido_na_lista(monkeypatch):
    titulos = [
        {"titleId": "111", "pfn": "Outro_x"},
        {"titleId": "222", "pfn": "PKG_Abc"},
        {"titleId": "333"},
    ]
    rede_falsa(monkeypatch, api, {_HUB: [Resposta(200, {"titles": titulos})]}, nome="_requisitar")
    assert api.titulo("pkg_ABC", []) == "222"
    assert api.titulo_local("pkg_ABC", []) == "222"


@pytest.mark.parametrize(
    "titulos",
    [
        [{"titleId": "111", "pfn": "Outro_x"}],
        [{"titleId": "111"}],
        [{"titleId": "111", "pfn": None}, "lixo", 5],
        [{"titleId": "111", "pfn": 7}],
    ],
)
def test_titlehub_sem_o_pfn_pedido_e_sem_xbox_live(monkeypatch, titulos):
    """O primeiro item da lista não vale se não é do pacote pedido."""
    rede_falsa(monkeypatch, api, {_HUB: [Resposta(200, {"titles": titulos})]}, nome="_requisitar")
    assert api.titulo("Pkg_abc", []) == ""
    assert api.titulo_local("Pkg_abc", []) == ""


def test_titulo_sem_pfn_nao_vai_a_rede(monkeypatch):
    chamadas = rede_falsa(monkeypatch, api, {}, nome="_requisitar")
    assert api.titulo(None, []) is None
    assert chamadas == []


def test_titlehub_fora_levanta_e_nao_grava_cache(monkeypatch):
    rede_falsa(monkeypatch, api, {}, nome="_requisitar")
    with pytest.raises(api.FalhaDeRede):
        api.titulo("Pkg_x", [])
    assert api.titulo_local("Pkg_x", []) is None


def test_pacote_sem_xbox_live_fica_7_dias(monkeypatch):
    rede_falsa(monkeypatch, api, {_HUB: [Resposta(200, {"titles": []})]}, nome="_requisitar")
    assert api.titulo("App_x", []) == ""
    assert api.titulo_local("App_x", []) == ""
    dados = json.loads((shared.conquistas_cache_dir / "xbox-titulos.json").read_text(encoding="utf-8"))
    dados["App_x"]["em"] -= 8 * 24 * 3600
    (shared.conquistas_cache_dir / "xbox-titulos.json").write_text(json.dumps(dados), encoding="utf-8")
    assert api.titulo_local("App_x", []) is None


@pytest.mark.parametrize("titulo", ["12a", "", None, 5, "١٢"])
def test_titlehub_com_titulo_estranho(monkeypatch, titulo):
    rede_falsa(monkeypatch, api, {_HUB: [Resposta(200, {"titles": [{"titleId": titulo, "pfn": "P"}]})]}, nome="_requisitar")
    assert api.titulo("P", []) == ""


def test_cache_de_titulos_ilegivel_e_ignorado():
    shared.conquistas_cache_dir.mkdir(parents=True)
    (shared.conquistas_cache_dir / "xbox-titulos.json").write_text("{", encoding="utf-8")
    assert api.titulo_local("P", []) is None


@pytest.mark.parametrize("conteudo", ['[]', '{"P": 5}', '{"P": {"titulo": 7, "em": 1}}',
                                      '{"P": {"titulo": null, "em": "x"}}', '{"P": {"titulo": null, "em": NaN}}'])
def test_cache_de_titulos_com_formato_errado_e_ignorado(conteudo):
    shared.conquistas_cache_dir.mkdir(parents=True)
    (shared.conquistas_cache_dir / "xbox-titulos.json").write_text(conteudo, encoding="utf-8")
    assert api.titulo_local("P", []) is None


def test_gravar_titulo_preserva_os_outros(monkeypatch):
    rede_falsa(monkeypatch, api, {_HUB: [Resposta(200, {"titles": [{"titleId": "1", "pfn": "A"}]}),
                                         Resposta(200, {"titles": [{"titleId": "2", "pfn": "B"}]})]}, nome="_requisitar")
    api.titulo("A", [])
    api.titulo("B", [])
    assert api.titulo_local("A", []) == "1" and api.titulo_local("B", []) == "2"
