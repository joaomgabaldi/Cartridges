# test_fita_wizard.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O que o assistente faz com a resposta da nuvem da Tuya."""

import ast
import json
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from cartridges import shared
from cartridges.fita_wizard import REGIOES, fitas_da_nuvem
from cartridges.utils import session_fita, tuya_conta
from cartridges.utils.session_fita import Fita


def test_dispositivo_com_chave_vira_fita():
    resposta = [
        {
            "name": "Fita Centro",
            "id": "eb1",
            "key": "abc",
            "ip": "192.168.0.150",
            "version": "3.3",
        }
    ]
    assert fitas_da_nuvem(resposta) == [
        Fita("Fita Centro", "eb1", "192.168.0.150", "abc", "3.3")
    ]


def test_dispositivo_sem_chave_fica_de_fora():
    assert fitas_da_nuvem([{"name": "X", "id": "eb2", "ip": "1.2.3.4"}]) == []


def test_sem_ip_a_fita_entra_com_ip_vazio_para_a_busca_achar():
    (fita,) = fitas_da_nuvem([{"name": "X", "id": "eb3", "key": "k"}])
    assert fita.ip == ""


def test_versao_ausente_assume_a_do_modulo_mais_comum():
    (fita,) = fitas_da_nuvem([{"name": "X", "id": "eb4", "key": "k", "ip": "1.2.3.4"}])
    assert fita.versao == "3.3"


# A `getdevices` da tinytuya não levanta quando a credencial está errada: ela
# devolve um dicionário de erro no lugar da lista. Sem estas três, um
# `AttributeError` dentro da thread deixaria o assistente parado para sempre na
# página "Buscando…".


def test_dicionario_de_erro_da_nuvem_nao_vira_fita():
    assert fitas_da_nuvem({"Error": "Invalid Key", "Err": "901"}) == []


def test_resposta_que_e_texto_nao_vira_fita():
    assert fitas_da_nuvem("Unable to get device list") == []


def test_item_que_nao_e_dicionario_e_pulado():
    resposta = ["lixo", None, {"name": "X", "id": "eb5", "key": "k"}]
    assert [fita.id for fita in fitas_da_nuvem(resposta)] == ["eb5"]


def test_a_tinytuya_fica_calada_no_arquivo_de_log():
    """A API Secret da conta não pode acabar no `cartridges.log`.

    Em DEBUG a tinytuya loga o dicionário de cabeçalhos de cada chamada à
    nuvem, e enquanto ela não tem token esse dicionário traz a Secret em claro.
    O `file_handler` do app grava tudo que chega em DEBUG, então o silenciamento
    da biblioteca é o que separa o segredo do arquivo que vai anexado a
    relatório de bug — e não pode sumir numa refatoração.
    """
    # shortcut: lê o dicionário do código-fonte, porque `logging/setup.py` ainda importa o GLib; volta ao import
    # direto quando o log migrar para o Qt.
    fonte = (Path(__file__).resolve().parent.parent / "cartridges" / "logging" / "setup.py").read_text(encoding="utf-8")
    lib_loggers = next(
        ast.literal_eval(no.value)
        for no in ast.parse(fonte).body
        if isinstance(no, ast.Assign) and no.targets[0].id == "LIB_LOGGERS"
    )
    nivel = logging.getLevelNamesMapping()[lib_loggers["tinytuya"]["level"]]
    assert nivel >= logging.WARNING


# region A tela do assistente


@pytest.fixture
def pastas(tmp_path, monkeypatch):
    """A configuração das fitas e a conta da Tuya vão para uma pasta descartável."""
    monkeypatch.setattr(shared, "fitas_dir", tmp_path / "fitas")
    monkeypatch.setattr(shared, "fitas_arquivo", tmp_path / "fitas.json")
    monkeypatch.setattr(shared, "tuya_conta_arquivo", tmp_path / "tuya_conta.json")
    return tmp_path


def _assistente(monkeypatch):
    """O assistente de verdade, com a thread da rede rodando na hora.

    Mesmo dublê de ``threading`` do teste do "Testar" nas Preferências: o que
    interessa aqui é o que a tarefa faz, e não que ela tenha uma thread.
    """
    import cartridges.fita_wizard as wizard_module  # noqa: PLC0415

    monkeypatch.setattr(
        wizard_module,
        "threading",
        SimpleNamespace(
            Thread=lambda target, args=(), daemon=False: SimpleNamespace(
                start=lambda: target(*args)
            )
        ),
    )
    return wizard_module.FitaWizard()


def test_busca_vazia_fica_nas_credenciais_e_nao_apaga_a_configuracao(
    pastas, monkeypatch
):
    """A página dos dispositivos só tem "Aplicar", e aplicar vazio apaga tudo.

    Sem esta volta, quem reabre o assistente e erra a Secret perde as fitas
    configuradas num clique, sem caminho de volta para corrigir a credencial.
    """
    configuradas = [Fita("Centro", "eb0", "1.2.3.4", "k")]
    session_fita.gravar_fitas(configuradas)
    assistente = _assistente(monkeypatch)

    assistente._mostrar([])

    assert assistente.pagina == "credenciais"
    assert assistente.semResultado
    assert session_fita.fitas() == configuradas


def test_busca_com_resultado_vai_para_a_lista_e_tira_o_aviso(pastas, monkeypatch):
    assistente = _assistente(monkeypatch)
    assistente._mostrar([])
    assistente._mostrar([Fita("Centro", "eb0", "1.2.3.4", "k")])

    assert assistente.pagina == "dispositivos"
    assert not assistente.semResultado


def test_fita_desmarcada_volta_ao_estado_guardado_e_sai_da_chave(
    pastas, monkeypatch, schema
):
    """Tirar uma fita da configuração não pode deixá-la acesa para sempre.

    Depois da gravação o app não conhece mais essa fita: o fechamento não a
    devolve, ainda limpa a chave, e ela fica na cor do Cartridges até alguém
    abrir o app Smart Life.
    """
    ficou = Fita("Centro", "eb0", "1.2.3.4", "k")
    saiu = Fita("Direita", "eb1", "1.2.3.5", "k")
    session_fita.gravar_fitas([ficou, saiu])
    guardado = {
        "eb0": {"ligada": True, "cor": "00b403e80064"},
        "eb1": {"ligada": False, "cor": ""},
    }
    schema.set_string("fita-estado-anterior", json.dumps(guardado))

    enviados = []
    monkeypatch.setattr(
        session_fita,
        "aplicar",
        lambda fita, ligada, cor: bool(enviados.append((fita.id, ligada, cor))) or True,
    )

    assistente = _assistente(monkeypatch)
    assistente._mostrar([ficou, saiu])
    assistente.marcar("eb1", False)
    fechou = []
    assistente.fechado.connect(lambda: fechou.append(True))
    assistente.salvar()

    assert session_fita.fitas() == [ficou]
    assert enviados == [("eb1", False, "")]
    assert fechou == [True]
    # A que ficou continua na chave: quem a devolve é o fechamento do app.
    assert json.loads(schema.get_string("fita-estado-anterior")) == {
        "eb0": guardado["eb0"]
    }


def test_assistente_abre_pre_preenchido_com_a_conta_salva(pastas, monkeypatch):
    tuya_conta.salvar(tuya_conta.Conta("chave-salva", "segredo-salvo", "cn"))

    assistente = _assistente(monkeypatch)

    assert assistente.chave == "chave-salva"
    assert assistente.segredo == "segredo-salvo"
    assert assistente.regiao == REGIOES.index("cn")


def _nuvem_falsa(monkeypatch, resposta, token="token-valido", error=None):
    """Põe no lugar da fábrica da nuvem uma que devolve ``resposta``.

    ``token`` e ``error`` reproduzem os atributos que a `tinytuya.Cloud` de
    verdade grava no `__init__` (antes mesmo de `getdevices` rodar). Devolve as
    chamadas feitas: ``(regiao, chave, segredo)``.
    """
    import cartridges.fita_wizard as wizard_module  # noqa: PLC0415

    chamadas = []
    monkeypatch.setattr(
        wizard_module,
        "_nuvem",
        lambda regiao, chave, segredo: chamadas.append((regiao, chave, segredo))
        or SimpleNamespace(getdevices=lambda: resposta, token=token, error=error),
    )
    return chamadas


def _sem_enderecos(monkeypatch):
    monkeypatch.setattr(session_fita, "enderecos_na_rede", lambda: ({}, {}))


def test_busca_com_sucesso_salva_a_conta_para_a_proxima_vez(
    pastas, monkeypatch, flush_idle
):
    """Credencial provada válida fica salva; é o que evita voltar ao painel."""
    chamadas = _nuvem_falsa(
        monkeypatch,
        [{"name": "Centro", "id": "eb0", "key": "k", "ip": "1.2.3.4", "version": "3.3"}],
    )
    _sem_enderecos(monkeypatch)
    assistente = _assistente(monkeypatch)
    assistente.chave = "minha-chave"
    assistente.segredo = "meu-segredo"
    assistente.regiao = REGIOES.index("eu")

    assistente.buscar()
    flush_idle()

    assert chamadas == [("eu", "minha-chave", "meu-segredo")]
    assert tuya_conta.carregar() == tuya_conta.Conta("minha-chave", "meu-segredo", "eu")
    assert assistente.pagina == "dispositivos"


def test_busca_sem_sucesso_nao_salva_a_conta(pastas, monkeypatch, flush_idle):
    """Erro de credencial (dicionário, não lista) não é uma conta para guardar."""
    erro = {"Error": "Invalid Key", "Err": "901"}
    _nuvem_falsa(monkeypatch, erro, token=None, error=erro)
    _sem_enderecos(monkeypatch)
    assistente = _assistente(monkeypatch)
    assistente.chave = "chave-errada"
    assistente.segredo = "segredo-errado"

    assistente.buscar()
    flush_idle()

    assert tuya_conta.carregar() is None
    assert assistente.pagina == "credenciais"
    assert assistente.semResultado


# endregion


def test_o_assistente_grava_o_endereco_que_a_rede_deu(monkeypatch, tmp_path):
    """A nuvem não sabe o IP local; a varredura, feita uma vez aqui, sabe."""
    from cartridges import shared
    from cartridges.fita_wizard import com_enderecos

    monkeypatch.setattr(shared, "fitas_arquivo", tmp_path / "fitas.json")
    da_nuvem = [Fita("Centro", "eb1", "", "k", "3.3")]

    (fita,) = com_enderecos(da_nuvem, {"eb1": "192.168.0.150"})

    assert fita.ip == "192.168.0.150"


def test_fita_que_a_rede_nao_achou_mantem_o_endereco_que_ja_tinha(monkeypatch, tmp_path):
    """Rodar o assistente com uma fita desligada não pode apagar o IP dela."""
    from cartridges import shared
    from cartridges.fita_wizard import com_enderecos
    from cartridges.utils.session_fita import gravar_fitas

    monkeypatch.setattr(shared, "fitas_arquivo", tmp_path / "fitas.json")
    gravar_fitas([Fita("Centro", "eb1", "192.168.0.150", "k", "3.3")])

    (fita,) = com_enderecos([Fita("Centro", "eb1", "", "k", "3.3")], {})

    assert fita.ip == "192.168.0.150"


def test_rodar_o_assistente_de_novo_mantem_o_brilho_por_dispositivo(monkeypatch, tmp_path):
    from cartridges import shared
    from cartridges.fita_wizard import com_enderecos
    from cartridges.utils.session_fita import gravar_fitas

    monkeypatch.setattr(shared, "fitas_arquivo", tmp_path / "fitas.json")
    gravar_fitas([Fita("Centro", "eb1", "192.168.0.150", "k", "3.3", 40)])

    antiga, nova = com_enderecos(
        [Fita("Centro", "eb1", "", "k"), Fita("Nova", "eb2", "", "k")], {}
    )

    assert (antiga.brilho, nova.brilho) == (40, 100)


def test_fita_nunca_vista_na_rede_fica_sem_endereco(monkeypatch, tmp_path):
    from cartridges import shared
    from cartridges.fita_wizard import com_enderecos

    monkeypatch.setattr(shared, "fitas_arquivo", tmp_path / "fitas.json")

    (fita,) = com_enderecos([Fita("Centro", "eb1", "", "k", "3.3")], {})

    assert fita.ip == ""


def test_so_fitas_e_lampadas_entram_na_lista():
    """A conta Tuya traz interruptores, tomadas, sensores e controles IR; só
    fita (dd) e lâmpada (dj) falam cor."""
    resposta = [
        {"name": "Fita Monitor Centro", "id": "a", "key": "k", "category": "dd"},
        {"name": "Abajur", "id": "b", "key": "k", "category": "dj"},
        {"name": "Sala", "id": "c", "key": "k", "category": "tdq"},
        {"name": "PC", "id": "d", "key": "k", "category": "cz"},
        {"name": "LED", "id": "e", "key": "k", "category": "infrared_light"},
        {"name": "Bateria #1", "id": "f", "key": "k", "category": "wsdcg"},
    ]
    assert [fita.nome for fita in fitas_da_nuvem(resposta)] == [
        "Fita Monitor Centro",
        "Abajur",
    ]


def test_rodar_o_assistente_de_novo_mantem_a_calibracao(monkeypatch, tmp_path):
    from cartridges import shared
    from cartridges.fita_wizard import com_enderecos
    from cartridges.utils.session_fita import gravar_fitas

    calibracao = {"cores": [[-8, 1.0]] + [[0, 1.0]] * 5, "branco": [30, 150]}
    monkeypatch.setattr(shared, "fitas_arquivo", tmp_path / "fitas.json")
    gravar_fitas([Fita("Centro", "eb1", "192.168.0.150", "k", "3.3", 40, calibracao)])

    antiga, nova = com_enderecos(
        [Fita("Centro", "eb1", "", "k"), Fita("Nova", "eb2", "", "k")], {}
    )

    assert (antiga.calibracao, nova.calibracao) == (calibracao, None)
