"""O vigia: percebe as conquistas que saem durante a partida."""

import json
import os

import pytest

from cartridges.conquistas import catalogo, historico, vigia
from cartridges.conquistas.catalogo import Catalogo, ConquistaInfo
from cartridges.conquistas.formatos import Desbloqueio
from tests.apoio_conquistas import criar, pastas  # noqa: F401

CAT = Catalogo(
    (
        ConquistaInfo("ACH_A", "Primeira", "", "", "", False, 50.0),
        ConquistaInfo("ACH_B", "Rara", "", "", "", False, 4.0),
    ),
    0,
    False,
)


@pytest.fixture(autouse=True)
def sem_timeout(monkeypatch):
    """O tique é chamado à mão; nada de GLib.timeout de verdade nos testes."""
    fontes = []
    monkeypatch.setattr(vigia.GLib, "timeout_add_seconds", lambda _s, f: fontes.append(f) or 7)
    monkeypatch.setattr(vigia.GLib, "source_remove", lambda _id: None)
    return fontes


def _arquivo(pastas, conquistas):  # noqa: F811
    caminho = pastas.appdata / "GSE Saves" / "570" / "achievements.json"
    criar(caminho, json.dumps({n: {"earned": True, "earned_time": t} for n, t in conquistas}))
    # O mtime tem de andar mesmo quando o teste regrava no mesmo instante. O NTFS
    # só distingue múltiplos de 100 ns, então o passo é de 1 s.
    passo = getattr(_arquivo, "passo", 0) + 1
    _arquivo.passo = passo
    os.utime(caminho, ns=(10**18 + passo * 10**9, 10**18 + passo * 10**9))
    return caminho


def _jogo(make_game, **campos):
    return make_game(game_id="g1", name="Jogo", steam_appid="570", executable="", **campos)


def _vigia(make_game, **campos):
    avisos = []
    instancia = vigia.Vigia(_jogo(make_game, **campos), avisos.append)
    return instancia, avisos


def test_inicio_grava_em_silencio(pastas, make_game):
    _arquivo(pastas, [("ACH_A", 100)])
    instancia, avisos = _vigia(make_game)
    instancia.iniciar()
    assert historico.ler("g1") == {"ACH_A": 100}
    assert instancia._olhar() is True
    assert avisos == []


def test_conquista_nova_durante_a_partida(pastas, make_game):
    catalogo._gravar_cache("570", CAT)
    _arquivo(pastas, [("ACH_A", 100)])
    instancia, avisos = _vigia(make_game)
    instancia.iniciar()
    _arquivo(pastas, [("ACH_A", 100), ("ACH_B", 200)])
    instancia._olhar()
    assert historico.ler("g1") == {"ACH_A": 100, "ACH_B": 200}
    assert len(avisos) == 1
    (nova,) = avisos[0]
    assert nova.nome == "ACH_B" and nova.info.titulo == "Rara"
    assert nova.completou is True  # 2 de 2


def test_arquivo_regravado_sem_novidade_nao_avisa(pastas, make_game):
    _arquivo(pastas, [("ACH_A", 100)])
    instancia, avisos = _vigia(make_game)
    instancia.iniciar()
    _arquivo(pastas, [("ACH_A", 100), ("ACH_B", 200)])
    instancia._olhar()
    _arquivo(pastas, [("ACH_A", 100), ("ACH_B", 200)])
    instancia._olhar()
    assert len(avisos) == 1


def test_varias_de_uma_vez_saem_em_ordem_de_hora(pastas, make_game):
    _arquivo(pastas, [])
    instancia, avisos = _vigia(make_game)
    instancia.iniciar()
    _arquivo(pastas, [("ACH_B", 300), ("ACH_A", 200)])
    instancia._olhar()
    assert [d.nome for d in avisos[0]] == ["ACH_A", "ACH_B"]
    assert all(d.info is None for d in avisos[0])  # sem catálogo


def test_arquivo_que_aparece_no_meio_da_partida(pastas, make_game):
    instancia, avisos = _vigia(make_game)
    instancia.iniciar()  # nenhum arquivo ainda: primeira vez grava vazio
    _arquivo(pastas, [("ACH_A", 100)])
    for _tique in range(vigia.REBUSCA):
        instancia._olhar()
    assert [d.nome for d in avisos[0]] == ["ACH_A"]


def test_arquivo_que_some_nao_levanta(pastas, make_game):
    caminho = _arquivo(pastas, [("ACH_A", 100)])
    instancia, avisos = _vigia(make_game)
    instancia.iniciar()
    caminho.unlink()
    assert instancia._olhar() is True
    assert avisos == []


def test_erro_inesperado_nao_derruba_o_tique(pastas, make_game, monkeypatch):
    _arquivo(pastas, [("ACH_A", 100)])
    instancia, _avisos = _vigia(make_game)
    instancia.iniciar()
    _arquivo(pastas, [("ACH_A", 100), ("ACH_B", 1)])
    monkeypatch.setattr(vigia.historico, "registrar", lambda *_a: 1 / 0)
    assert instancia._olhar() is True


def test_primeira_varredura_durante_a_sessao_nao_avisa(pastas, make_game):
    """Jogo que nunca foi varrido: o que já estava no arquivo é base, não novidade."""
    _arquivo(pastas, [("ACH_A", 100), ("ACH_B", 200)])
    instancia, avisos = _vigia(make_game)
    instancia.iniciar()
    instancia._olhar()
    assert avisos == []


def test_leitura_que_falha_e_tentada_de_novo_no_tique_seguinte(pastas, make_game, monkeypatch):
    _arquivo(pastas, [("ACH_A", 100)])
    instancia, avisos = _vigia(make_game)
    instancia.iniciar()
    _arquivo(pastas, [("ACH_A", 100), ("ACH_B", 200)])
    real = vigia.formatos.ler_ou_none
    falhas = []

    def falha_uma_vez(caminho, formato):
        if not falhas:
            falhas.append(caminho)
            return None
        return real(caminho, formato)

    monkeypatch.setattr(vigia.formatos, "ler_ou_none", falha_uma_vez)
    instancia._olhar()
    assert avisos == [] and "ACH_B" not in historico.ler("g1")
    instancia._olhar()  # o arquivo não mudou de novo
    assert [d.nome for d in avisos[0]] == ["ACH_B"]


def test_gravacao_que_falha_e_tentada_de_novo_no_tique_seguinte(pastas, make_game, monkeypatch):
    _arquivo(pastas, [("ACH_A", 100)])
    instancia, avisos = _vigia(make_game)
    instancia.iniciar()
    _arquivo(pastas, [("ACH_A", 100), ("ACH_B", 200)])
    real = vigia.historico.registrar
    chamadas = []

    def falha_uma_vez(game_id, novos):
        if not chamadas:
            chamadas.append(game_id)
            return [], False
        return real(game_id, novos)

    monkeypatch.setattr(vigia.historico, "registrar", falha_uma_vez)
    instancia._olhar()
    assert avisos == [] and "ACH_B" not in historico.ler("g1")
    instancia._olhar()
    assert [d.nome for d in avisos[0]] == ["ACH_B"]
    instancia._olhar()  # e agora está visto: nada se repete
    assert len(avisos) == 1


def test_historico_indisponivel_por_um_tique_avisa_no_seguinte_uma_vez_so(
    pastas, make_game, monkeypatch
):
    """Antivírus com o histórico aberto no instante da releitura: nada se perde nem se duplica."""
    catalogo._gravar_cache("570", CAT)
    _arquivo(pastas, [("ACH_A", 100)])
    instancia, avisos = _vigia(make_game)
    instancia.iniciar()
    _arquivo(pastas, [("ACH_A", 100), ("ACH_B", 200)])
    real = historico.ler_json
    negar = [True]

    def negado(caminho):
        if negar[0]:
            raise PermissionError("em uso por outro processo")
        return real(caminho)

    monkeypatch.setattr(historico, "ler_json", negado)
    instancia._olhar()
    assert avisos == []
    negar[0] = False
    assert historico.ler("g1") == {"ACH_A": 100}  # intacto, sem .corrompido
    assert not historico.caminho("g1").with_name("g1.json.corrompido").exists()
    instancia._olhar()
    assert [d.nome for d in avisos[0]] == ["ACH_B"]
    instancia._olhar()
    assert len(avisos) == 1


def test_base_que_nao_pode_ser_lida_nao_vira_aviso(pastas, make_game, monkeypatch):
    _arquivo(pastas, [("ACH_A", 100)])
    historico.registrar("g1", [Desbloqueio("ANTIGA", 5)])  # o histórico já existe
    real = vigia.formatos.ler_ou_none
    monkeypatch.setattr(vigia.formatos, "ler_ou_none", lambda *_a: None)
    instancia, avisos = _vigia(make_game)
    instancia.iniciar()
    assert historico.ler("g1") == {"ANTIGA": 5}
    instancia._olhar()  # continua ilegível
    assert avisos == []
    monkeypatch.setattr(vigia.formatos, "ler_ou_none", real)
    instancia._olhar()  # agora lê: é a base, em silêncio
    assert avisos == [] and historico.ler("g1") == {"ANTIGA": 5, "ACH_A": 100}
    _arquivo(pastas, [("ACH_A", 100), ("ACH_B", 200)])
    instancia._olhar()  # e daqui em diante é um arquivo como os outros
    assert [d.nome for d in avisos[0]] == ["ACH_B"]


def test_historico_que_sumiu_no_meio_da_partida_nao_avisa(pastas, make_game):
    """Jogo nunca varrido: sem histórico na hora da mudança, é a primeira vez, não novidade."""
    _arquivo(pastas, [("ACH_A", 100)])
    instancia, avisos = _vigia(make_game)
    instancia.iniciar()
    historico.caminho("g1").unlink()
    _arquivo(pastas, [("ACH_A", 100), ("ACH_B", 200)])
    instancia._olhar()
    assert avisos == [] and historico.ler("g1") == {"ACH_A": 100, "ACH_B": 200}


def test_arquivo_apagado_e_recriado_com_conquista_nova(pastas, make_game):
    caminho = _arquivo(pastas, [("ACH_A", 100)])
    instancia, avisos = _vigia(make_game)
    instancia.iniciar()
    caminho.unlink()
    instancia._olhar()
    _arquivo(pastas, [("ACH_A", 100), ("ACH_B", 200)])
    instancia._olhar()
    assert [d.nome for d in avisos[0]] == ["ACH_B"]


def test_hora_grande_demais_avisa_uma_vez_so(pastas, make_game):
    """O histórico recusa hora de 2**63 para cima; ela vira "sem data", e não um aviso por tique."""
    _arquivo(pastas, [("ACH_A", 100)])
    instancia, avisos = _vigia(make_game)
    instancia.iniciar()
    _arquivo(pastas, [("ACH_A", 100), ("ACH_B", 10**20)])
    for _tique in range(5):
        instancia._olhar()
    assert len(avisos) == 1
    assert historico.ler("g1") == {"ACH_A": 100, "ACH_B": 0}


def test_hora_grande_demais_na_base_nao_deixa_o_arquivo_pendente(pastas, make_game):
    _arquivo(pastas, [("ACH_A", 10**20)])
    instancia, _avisos = _vigia(make_game)
    instancia.iniciar()
    assert historico.ler("g1") == {"ACH_A": 0} and not instancia._pendentes


@pytest.mark.parametrize("na_base", [False, True])
def test_arquivo_que_sempre_falha_so_volta_na_rebusca(pastas, make_game, monkeypatch, na_base):
    _arquivo(pastas, [("ACH_A", 100)])
    instancia, avisos = _vigia(make_game)
    chamadas = []

    def sempre_falha(caminho, _formato):
        chamadas.append(caminho)
        return None

    if na_base:
        monkeypatch.setattr(vigia.formatos, "ler_ou_none", sempre_falha)
        instancia.iniciar()
        chamadas.clear()  # a leitura da base não conta
    else:
        instancia.iniciar()
        _arquivo(pastas, [("ACH_A", 100), ("ACH_B", 200)])
        monkeypatch.setattr(vigia.formatos, "ler_ou_none", sempre_falha)
    for _tique in range(3):
        instancia._olhar()
    assert len(chamadas) == vigia.TENTATIVAS == 3
    for _tique in range(vigia.REBUSCA - 4):
        instancia._olhar()
    assert len(chamadas) == 3  # tiques 4 a REBUSCA - 1: nada
    instancia._olhar()  # o tique da rebusca tenta de novo
    assert len(chamadas) == 4 and avisos == []


def test_gravacao_que_nunca_se_completa_tambem_para_de_insistir(pastas, make_game, monkeypatch):
    _arquivo(pastas, [("ACH_A", 100)])
    instancia, _avisos = _vigia(make_game)
    instancia.iniciar()
    _arquivo(pastas, [("ACH_A", 100), ("ACH_B", 200)])
    chamadas = []
    monkeypatch.setattr(
        vigia.historico, "registrar", lambda *_a: chamadas.append(1) or ([], False)
    )
    for _tique in range(vigia.REBUSCA - 1):
        instancia._olhar()
    assert len(chamadas) == 3


CAT3 = Catalogo(
    (
        ConquistaInfo("ACH_A", "Um", "", "", "", False, 50.0),
        ConquistaInfo("ACH_B", "Dois", "", "", "", False, 50.0),
        ConquistaInfo("ACH_C", "Três", "", "", "", False, 50.0),
    ),
    0,
    False,
)


def test_duas_de_uma_vez_sem_fechar_o_jogo_nao_completam(pastas, make_game):
    catalogo._gravar_cache("570", CAT3)
    _arquivo(pastas, [])
    instancia, avisos = _vigia(make_game)
    instancia.iniciar()
    _arquivo(pastas, [("ACH_A", 100), ("ACH_B", 200)])
    instancia._olhar()
    assert [d.completou for d in avisos[0]] == [False, False]


def test_o_cem_por_cento_e_da_ultima_conquista_do_catalogo(pastas, make_game):
    catalogo._gravar_cache("570", CAT)
    _arquivo(pastas, [("ACH_A", 100)])
    instancia, avisos = _vigia(make_game)
    instancia.iniciar()
    # ACH_X é a mais recente, mas o catálogo não a conhece.
    _arquivo(pastas, [("ACH_A", 100), ("ACH_B", 200), ("ACH_X", 300)])
    instancia._olhar()
    assert [(d.nome, d.completou) for d in avisos[0]] == [("ACH_B", True), ("ACH_X", False)]


def test_jogo_ja_completo_que_recebe_nome_desconhecido_nao_completa(pastas, make_game):
    catalogo._gravar_cache("570", CAT)
    _arquivo(pastas, [("ACH_A", 100), ("ACH_B", 200)])
    instancia, avisos = _vigia(make_game)
    instancia.iniciar()
    _arquivo(pastas, [("ACH_A", 100), ("ACH_B", 200), ("ACH_X", 300)])
    instancia._olhar()
    assert [(d.nome, d.completou) for d in avisos[0]] == [("ACH_X", False)]


@pytest.mark.parametrize(
    ("campos", "esperado"),
    [
        ({}, True),
        ({"conquistas": False}, False),
        ({"executable": "steam://rungameid/570"}, False),
        ({"steam_appid": None}, False),
        ({"steam_appid": "..\\x"}, False),
    ],
)
def test_quem_o_vigia_acompanha(make_game, campos, esperado):
    base = {"game_id": "g1", "name": "Jogo", "steam_appid": "570", "executable": ""}
    base.update(campos)
    assert vigia.acompanha(make_game(**base)) is esperado


def test_jogo_que_nao_e_acompanhado_nao_liga_o_timer(make_game, sem_timeout):
    instancia, _avisos = _vigia(make_game, conquistas=False)
    instancia.iniciar()
    assert sem_timeout == [] and not instancia.ativo


def test_parar_desliga(pastas, make_game, sem_timeout):
    instancia, _avisos = _vigia(make_game)
    instancia.iniciar()
    assert instancia.ativo
    instancia.parar()
    assert not instancia.ativo


def test_historico_ja_existente_continua_somando(pastas, make_game):
    historico.registrar("g1", [Desbloqueio("ANTIGA", 5)])
    _arquivo(pastas, [("ACH_A", 100)])
    instancia, avisos = _vigia(make_game)
    instancia.iniciar()
    assert historico.ler("g1") == {"ANTIGA": 5, "ACH_A": 100}
    assert avisos == []  # o que já estava no arquivo no começo da sessão é base
