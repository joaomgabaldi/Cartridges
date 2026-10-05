"""O histórico de conquistas: só soma."""

import json
from pathlib import Path

import pytest

from cartridges import shared
from cartridges.conquistas import historico
from cartridges.conquistas.formatos import Desbloqueio as D


def test_fundir_so_soma():
    atual = {"ACH_A": 100}
    resultado, entraram = historico.fundir(atual, [D("ach_b", 200)])
    assert resultado == {"ACH_A": 100, "ACH_B": 200}
    assert entraram == ["ACH_B"]
    assert atual == {"ACH_A": 100}  # não mexe no que recebeu


def test_fundir_fica_a_data_mais_antiga():
    assert historico.fundir({"A": 300}, [D("a", 200)]) == ({"A": 200}, [])
    assert historico.fundir({"A": 200}, [D("A", 300)]) == ({"A": 200}, [])


def test_data_zero_nao_apaga_uma_data():
    assert historico.fundir({"A": 200}, [D("A", 0)]) == ({"A": 200}, [])
    assert historico.fundir({"A": 0}, [D("A", 150)]) == ({"A": 150}, [])


def test_repetida_na_mesma_leitura_entra_uma_vez():
    assert historico.fundir({}, [D("A", 5), D("a", 3)]) == ({"A": 3}, ["A"])


def test_primeira_vez_grava_mesmo_vazio():
    assert historico.ler("g1") is None
    assert historico.registrar("g1", []) == ([], True)
    assert historico.ler("g1") == {}


def test_registrar_nunca_tira():
    historico.registrar("g1", [D("A", 1)])
    assert historico.registrar("g1", []) == ([], False)
    assert historico.ler("g1") == {"A": 1}


def test_arquivo_ilegivel_conta_como_nunca_varrido():
    historico.caminho("g1").parent.mkdir(parents=True)
    historico.caminho("g1").write_text("{", encoding="utf-8")
    assert historico.ler("g1") is None


def test_registrar_guarda_o_arquivo_ilegivel_antes_de_gravar():
    historico.caminho("g1").parent.mkdir(parents=True)
    historico.caminho("g1").write_text("{", encoding="utf-8")
    assert historico.registrar("g1", [D("A", 1)]) == (["A"], True)
    assert historico.ler("g1") == {"A": 1}
    guardado = historico.caminho("g1").with_name("g1.json.corrompido")
    assert guardado.read_text(encoding="utf-8") == "{"


def test_formato_inesperado_tambem_e_guardado():
    historico.caminho("g1").parent.mkdir(parents=True)
    historico.caminho("g1").write_text('{"desbloqueadas": [1]}', encoding="utf-8")
    assert historico.ler("g1") is None
    assert historico.registrar("g1", [D("A", 1)]) == (["A"], True)
    assert historico.caminho("g1").with_name("g1.json.corrompido").is_file()


def test_arquivo_ilegivel_travado_nao_e_sobrescrito(monkeypatch):
    historico.caminho("g1").parent.mkdir(parents=True)
    historico.caminho("g1").write_text("{", encoding="utf-8")

    def travado(self, destino):
        raise PermissionError("travado")

    monkeypatch.setattr(Path, "replace", travado)
    assert historico.registrar("g1", [D("A", 1)]) == ([], False)
    assert historico.caminho("g1").read_text(encoding="utf-8") == "{"


def test_transferir_guarda_o_destino_ilegivel():
    historico.registrar("de", [D("A", 5)])
    historico.caminho("para").write_text("{", encoding="utf-8")
    historico.transferir("de", "para")
    assert historico.ler("para") == {"A": 5}
    assert historico.caminho("para").with_name("para.json.corrompido").read_text(
        encoding="utf-8"
    ) == "{"


def test_transferir_destino_travado_nao_grava(monkeypatch):
    historico.registrar("de", [D("A", 5)])
    historico.caminho("para").write_text("{", encoding="utf-8")

    def travado(self, destino):
        raise PermissionError("travado")

    monkeypatch.setattr(Path, "replace", travado)
    historico.transferir("de", "para")
    assert historico.caminho("para").read_text(encoding="utf-8") == "{"


def _indisponivel(monkeypatch, *quais):
    """O arquivo existe, mas ``ler_json`` levanta ``PermissionError`` mesmo depois das tentativas."""
    real = historico.ler_json

    def negado(caminho):
        if not quais or caminho.stem in quais:
            raise PermissionError("em uso por outro processo")
        return real(caminho)

    monkeypatch.setattr(historico, "ler_json", negado)
    return real


def test_arquivo_indisponivel_nao_vai_para_o_corrompido(monkeypatch):
    """Antivírus ou indexador com o arquivo aberto: não é conteúdo ruim, é o momento errado."""
    historico.registrar("g1", [D("A", 1)])
    antes = historico.caminho("g1").read_text(encoding="utf-8")
    real = _indisponivel(monkeypatch)
    assert historico.ler("g1") is None
    assert historico.registrar("g1", [D("B", 2)]) == ([], False)
    assert historico.caminho("g1").read_text(encoding="utf-8") == antes
    assert not historico.caminho("g1").with_name("g1.json.corrompido").exists()
    monkeypatch.setattr(historico, "ler_json", real)
    assert historico.registrar("g1", [D("B", 2)]) == (["B"], False)
    assert historico.ler("g1") == {"A": 1, "B": 2}


def test_arquivo_indisponivel_nunca_e_a_primeira_vez(monkeypatch):
    historico.registrar("g1", [D("A", 1)])
    _indisponivel(monkeypatch)
    assert historico.registrar("g1", []) == ([], False)
    assert historico.registrar("g1", [D("A", 1)]) == ([], False)


def test_json_invalido_continua_indo_para_o_corrompido():
    historico.caminho("g1").parent.mkdir(parents=True)
    historico.caminho("g1").write_text("{", encoding="utf-8")
    assert historico.registrar("g1", [D("A", 1)]) == (["A"], True)
    assert historico.caminho("g1").with_name("g1.json.corrompido").is_file()


def test_transferir_destino_indisponivel_nao_o_renomeia(monkeypatch):
    historico.registrar("de", [D("A", 5)])
    historico.registrar("para", [D("B", 7)])
    antes = historico.caminho("para").read_text(encoding="utf-8")
    _indisponivel(monkeypatch, "para")
    assert historico.transferir("de", "para") is False
    assert historico.caminho("para").read_text(encoding="utf-8") == antes
    assert not historico.caminho("para").with_name("para.json.corrompido").exists()
    # A origem fica à parte, onde o Excluir que vem em seguida não alcança.
    assert not historico.caminho("de").exists()
    pendente = historico.caminho("de").with_name("de.json.pendente")
    assert json.loads(pendente.read_text(encoding="utf-8")) == {"desbloqueadas": {"A": 5}}


def test_transferir_origem_indisponivel_nao_vai_para_o_corrompido(monkeypatch):
    historico.registrar("de", [D("A", 5)])
    historico.registrar("para", [D("B", 7)])
    _indisponivel(monkeypatch, "de")
    assert historico.transferir("de", "para") is False
    assert not historico.caminho("de").with_name("de.json.corrompido").exists()
    assert historico.ler("para") == {"B": 7}
    # O arquivo à parte (.pendente) segura o conteúdo contra o Excluir.
    assert historico.caminho("de").with_name("de.json.pendente").is_file()
    assert not historico.caminho("de").exists()


def test_transferir_origem_ilegivel_nao_mexe_no_destino():
    historico.registrar("para", [D("B", 7)])
    historico.caminho("de").write_text("{", encoding="utf-8")
    historico.transferir("de", "para")
    assert historico.ler("para") == {"B": 7}


def test_transferir_guarda_a_origem_ilegivel():
    """Quem chama exclui a origem em seguida (apagando `<id>.json`): o que não
    deu para ler precisa já estar à parte, no `.corrompido`."""
    historico.registrar("para", [D("B", 7)])
    historico.caminho("de").write_text("{", encoding="utf-8")
    historico.transferir("de", "para")
    assert not historico.caminho("de").exists()
    assert historico.caminho("de").with_name("de.json.corrompido").read_text(
        encoding="utf-8"
    ) == "{"


def test_transferir_devolve_true_quando_fundiu_ou_nao_havia_nada():
    historico.registrar("de", [D("A", 5)])
    assert historico.transferir("de", "para") is True
    assert historico.transferir("sem_arquivo", "para") is True


def test_transferir_que_nao_grava_poe_a_origem_de_lado(monkeypatch, caplog):
    """Quem chama exclui a origem logo depois: se o destino não recebeu, a
    origem não pode ser o único exemplar a ir embora com o Excluir."""
    historico.registrar("de", [D("A", 5)])
    historico.registrar("para", [D("B", 7)])

    def falha(*_args):
        raise OSError("disco cheio")

    monkeypatch.setattr(historico, "_gravar", falha)
    with caplog.at_level("WARNING"):
        assert historico.transferir("de", "para") is False
    assert not historico.caminho("de").exists()
    pendente = historico.caminho("de").with_name("de.json.pendente")
    assert json.loads(pendente.read_text(encoding="utf-8")) == {"desbloqueadas": {"A": 5}}
    assert historico.ler("para") == {"B": 7}
    assert "não transferidas" in caplog.text
    # O Excluir que vem em seguida não leva o arquivo à parte.
    historico.apagar("de")
    assert pendente.is_file()


def test_registrar_que_nao_grava_nao_anuncia_o_que_nao_guardou(monkeypatch):
    def falha(*_args):
        raise OSError("disco cheio")

    monkeypatch.setattr(historico, "_gravar", falha)
    assert historico.registrar("g1", [D("A", 1)]) == ([], True)
    historico.registrar("g2", [])  # também sem arquivo, e também sem levantar
    assert historico.ler("g1") is None


def test_registrar_que_nao_grava_um_historico_existente_devolve_vazio(monkeypatch):
    historico.registrar("g1", [D("A", 1)])

    def falha(*_args):
        raise OSError("disco cheio")

    monkeypatch.setattr(historico, "_gravar", falha)
    assert historico.registrar("g1", [D("B", 2)]) == ([], False)
    assert historico.ler("g1") == {"A": 1}


def test_mover_leva_o_historico_e_nao_levanta(monkeypatch, caplog):
    historico.registrar("velho", [D("A", 1)])
    historico.mover("velho", "novo")
    assert historico.ler("novo") == {"A": 1}
    assert historico.ler("velho") is None

    historico.mover("sem_arquivo", "outro")  # sem origem: nada a fazer
    assert historico.ler("outro") is None

    def travado(self, destino):
        raise PermissionError("travado")

    monkeypatch.setattr(Path, "replace", travado)
    with caplog.at_level("WARNING"):
        historico.mover("novo", "terceiro")  # não levanta
    assert "não movidas" in caplog.text
    assert historico.ler("novo") == {"A": 1}


def test_valores_invalidos_sao_pulados_um_a_um():
    historico.caminho("g1").parent.mkdir(parents=True)
    historico.caminho("g1").write_text(
        '{"desbloqueadas": {"A": NaN, "B": Infinity, "C": 5, "D": true}}',
        encoding="utf-8",
    )
    assert historico.ler("g1") == {"C": 5}


def test_inteiro_gigante_nao_levanta():
    historico.caminho("g1").parent.mkdir(parents=True)
    historico.caminho("g1").write_text(
        '{"desbloqueadas": {"A": 1' + "0" * 400 + ', "B": 5}}', encoding="utf-8"
    )
    # "A" não cabe como data (passa de 2**63): é pulada, sem levantar; "B" fica.
    assert historico.ler("g1") == {"B": 5}


def test_grava_na_pasta_do_app():
    historico.registrar("g1", [D("A", 1)])
    assert historico.caminho("g1") == shared.conquistas_dir / "g1.json"
    assert historico.caminho("g1").is_file()


def test_transferir_funde_no_destino():
    historico.registrar("de", [D("A", 5), D("B", 9)])
    historico.registrar("para", [D("B", 7)])
    historico.transferir("de", "para")
    assert historico.ler("para") == {"A": 5, "B": 7}


def test_transferir_sem_origem_nao_cria_o_destino():
    historico.transferir("de", "para")
    assert historico.ler("para") is None


def test_apagar():
    historico.registrar("g1", [D("A", 1)])
    historico.apagar("g1")
    assert historico.ler("g1") is None
    historico.apagar("g1")  # de novo, sem arquivo: não levanta


def test_fonte_gravada_junto_das_desbloqueadas():
    historico.registrar("g", [D("A", 1)], fonte="steam:570")
    assert historico.fonte("g") == "steam:570"
    assert historico.ler("g") == {"A": 1}


def test_registrar_sem_fonte_mantem_a_gravada():
    historico.registrar("g", [], fonte="xbox:9")
    historico.registrar("g", [D("XBOX:1", 5)])
    assert historico.fonte("g") == "xbox:9"


def test_trocar_so_a_fonte_grava():
    historico.registrar("g", [D("A", 1)], fonte="steam:570")
    entraram, primeira = historico.registrar("g", [], fonte="xbox:9")
    assert (entraram, primeira) == ([], False)
    assert historico.fonte("g") == "xbox:9"
    assert historico.ler("g") == {"A": 1}


def test_esquecer_fonte_nao_cria_arquivo():
    historico.esquecer_fonte("nunca")
    assert not historico.caminho("nunca").exists()
    historico.registrar("g", [D("A", 1)], fonte="steam:570")
    historico.esquecer_fonte("g")
    assert historico.fonte("g") is None
    assert historico.ler("g") == {"A": 1}


@pytest.mark.parametrize("valor", [5, None, ["x"], {"a": 1}, ""])
def test_fonte_estranha_vira_none(valor):
    historico.caminho("g").parent.mkdir(parents=True, exist_ok=True)
    historico.caminho("g").write_text(
        json.dumps({"desbloqueadas": {"A": 1}, "fonte": valor}), encoding="utf-8"
    )
    assert historico.fonte("g") is None
    assert historico.ler("g") == {"A": 1}


def test_transferir_leva_a_fonte_so_se_o_destino_nao_tem():
    historico.registrar("de", [D("A", 1)], fonte="xbox:9")
    historico.registrar("para", [D("B", 2)])
    assert historico.transferir("de", "para")
    assert historico.fonte("para") == "xbox:9"
    historico.registrar("de2", [D("C", 3)], fonte="steam:1")
    assert historico.transferir("de2", "para")
    assert historico.fonte("para") == "xbox:9"


def test_mover_leva_a_fonte():
    historico.registrar("de", [D("A", 1)], fonte="steam:570")
    historico.mover("de", "para")
    assert historico.fonte("para") == "steam:570"


def test_fonte_sem_arquivo_ou_ilegivel_e_none():
    assert historico.fonte("nunca") is None
    historico.caminho("g").parent.mkdir(parents=True, exist_ok=True)
    historico.caminho("g").write_text("{não é json", encoding="utf-8")
    assert historico.fonte("g") is None


def test_esquecer_fonte_nao_mexe_em_arquivo_ilegivel_nem_indisponivel(monkeypatch):
    historico.caminho("g").parent.mkdir(parents=True, exist_ok=True)
    historico.caminho("g").write_text("{não é json", encoding="utf-8")
    historico.esquecer_fonte("g")
    assert historico.caminho("g").read_text(encoding="utf-8") == "{não é json"
    assert not historico.caminho("g").with_name("g.json.corrompido").exists()

    historico.registrar("h", [D("A", 1)], fonte="xbox:9")
    antes = historico.caminho("h").read_text(encoding="utf-8")

    def travado(_caminho):
        raise PermissionError("em uso")

    with monkeypatch.context() as quebrado:
        quebrado.setattr(historico, "ler_json", travado)
        historico.esquecer_fonte("h")
    assert historico.caminho("h").read_text(encoding="utf-8") == antes


def test_esquecer_fonte_que_nao_grava_nao_levanta(monkeypatch):
    historico.registrar("g", [D("A", 1)], fonte="xbox:9")

    def falha(*_args):
        raise OSError("disco cheio")

    with monkeypatch.context() as quebrado:
        quebrado.setattr(historico, "_gravar", falha)
        historico.esquecer_fonte("g")
    assert historico.fonte("g") == "xbox:9"


# -- a conta da fonte do Xbox -----------------------------------------------------


def test_conta_gravada_junto_da_fonte_do_xbox():
    historico.registrar("g", [D("XBOX:1", 5)], fonte="xbox:9", conta="111")
    assert historico.conta("g") == "111"
    assert historico.fonte("g") == "xbox:9"
    assert json.loads(historico.caminho("g").read_text(encoding="utf-8"))["conta"] == "111"


def test_conta_sem_arquivo_ou_sem_conta_gravada_e_none():
    assert historico.conta("nunca") is None
    historico.registrar("g", [D("A", 1)], fonte="steam:570")
    assert historico.conta("g") is None


def test_fonte_da_steam_nao_guarda_conta():
    historico.registrar("g", [], fonte="steam:570", conta="111")
    assert historico.conta("g") is None
    assert "conta" not in json.loads(historico.caminho("g").read_text(encoding="utf-8"))


def test_registrar_sem_fonte_mantem_a_conta():
    historico.registrar("g", [], fonte="xbox:9", conta="111")
    historico.registrar("g", [D("XBOX:1", 5)])
    assert historico.conta("g") == "111"


def test_trocar_so_a_conta_grava():
    historico.registrar("g", [D("XBOX:1", 5)], fonte="xbox:9", conta="111")
    assert historico.registrar("g", [], fonte="xbox:9", conta="222") == ([], False)
    assert historico.conta("g") == "222"
    assert historico.ler("g") == {"XBOX:1": 5}


def test_trocar_a_fonte_para_a_steam_tira_a_conta():
    historico.registrar("g", [], fonte="xbox:9", conta="111")
    historico.registrar("g", [], fonte="steam:570")
    assert historico.conta("g") is None


def test_esquecer_fonte_esquece_a_conta():
    historico.registrar("g", [D("XBOX:1", 5)], fonte="xbox:9", conta="111")
    historico.esquecer_fonte("g")
    assert historico.fonte("g") is None
    assert historico.conta("g") is None
    assert historico.ler("g") == {"XBOX:1": 5}


@pytest.mark.parametrize("valor", [5, None, ["x"], {"a": 1}, ""])
def test_conta_estranha_vira_none(valor):
    historico.caminho("g").parent.mkdir(parents=True, exist_ok=True)
    historico.caminho("g").write_text(
        json.dumps({"desbloqueadas": {"A": 1}, "fonte": "xbox:9", "conta": valor}),
        encoding="utf-8",
    )
    assert historico.conta("g") is None
    assert historico.fonte("g") == "xbox:9"


def test_transferir_leva_a_conta_junto_da_fonte():
    historico.registrar("de", [D("A", 1)], fonte="xbox:9", conta="111")
    historico.registrar("para", [D("B", 2)])
    assert historico.transferir("de", "para")
    assert (historico.fonte("para"), historico.conta("para")) == ("xbox:9", "111")
    historico.registrar("de2", [D("C", 3)], fonte="xbox:5", conta="222")
    assert historico.transferir("de2", "para")
    assert (historico.fonte("para"), historico.conta("para")) == ("xbox:9", "111")


def test_mover_leva_a_conta():
    historico.registrar("de", [D("A", 1)], fonte="xbox:9", conta="111")
    historico.mover("de", "para")
    assert historico.conta("para") == "111"


def test_conta_gravada_junto_da_fonte_da_epic():
    historico.registrar("g", [D("EPIC:A", 5)], fonte="epic:fn", conta="c1")
    assert historico.conta("g") == "c1"
