"""O histórico de conquistas: só soma."""

from pathlib import Path

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


def test_transferir_origem_ilegivel_nao_mexe_no_destino():
    historico.registrar("para", [D("B", 7)])
    historico.caminho("de").write_text("{", encoding="utf-8")
    historico.transferir("de", "para")
    assert historico.ler("para") == {"B": 7}
    assert historico.caminho("de").read_text(encoding="utf-8") == "{"


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
