# test_session_fita.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""As fitas de LED: o que fica em disco e qual cor cada jogo recebe."""

import json
import sys
import threading
import time
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from PIL import Image

from cartridges import shared
from cartridges.utils import session_fita


@pytest.fixture(autouse=True)
def pastas(tmp_path, monkeypatch):
    """Tudo o que o módulo grava vai para uma pasta descartável."""
    monkeypatch.setattr(shared, "fitas_dir", tmp_path / "fitas")
    monkeypatch.setattr(shared, "fitas_arquivo", tmp_path / "fitas.json")
    return tmp_path


def _jogo(tmp_path, game_id="jogo-1", cor=(220, 20, 20)):
    capa = tmp_path / f"{game_id}.png"
    Image.new("RGB", (60, 90), cor).save(capa)
    return SimpleNamespace(game_id=game_id, name="Jogo", get_cover_path=lambda: capa)


def test_sem_configuracao_nao_ha_fitas():
    assert session_fita.fitas() == []


def test_fitas_gravadas_voltam_iguais():
    uma = session_fita.Fita("Centro", "eb00", "192.168.0.150", "chave", "3.3")
    session_fita.gravar_fitas([uma])
    assert session_fita.fitas() == [uma]


def test_arquivo_corrompido_nao_levanta():
    shared.fitas_arquivo.write_text("{lixo", encoding="utf-8")
    assert session_fita.fitas() == []


def test_cor_do_jogo_sai_da_capa(tmp_path, schema):
    cor = session_fita.cor_do_jogo(_jogo(tmp_path))
    assert cor.matiz < 10 or cor.matiz > 350
    assert cor.brilho == schema.get_int("fita-brilho-padrao")


def test_escolha_manual_vence_a_capa(tmp_path, schema):
    jogo = _jogo(tmp_path)
    session_fita.salvar_cor(jogo.game_id, jogo.name, session_fita.Cor(340, 1000, 150))
    cor = session_fita.cor_do_jogo(jogo)
    assert cor == session_fita.Cor(340, 1000, 150)
    assert session_fita.escolhida(jogo.game_id)


def test_redefinir_devolve_o_automatico(tmp_path, schema):
    jogo = _jogo(tmp_path)
    session_fita.salvar_cor(jogo.game_id, jogo.name, session_fita.Cor(340, 1000, 150))
    session_fita.redefinir(jogo.game_id)
    assert not session_fita.escolhida(jogo.game_id)
    assert session_fita.cor_do_jogo(jogo).matiz != 340


def test_jogo_sem_capa_usa_o_roxo_do_app(tmp_path, schema):
    jogo = SimpleNamespace(game_id="sem-capa", name="X", get_cover_path=lambda: None)
    cor = session_fita.cor_do_jogo(jogo)
    assert (cor.matiz, cor.saturacao) == session_fita.ROXO_DO_APP


def test_salvar_cor_nao_levanta_sem_permissao(tmp_path, monkeypatch, schema):
    """Quem chama está na thread de UI: disco negado é aviso, nunca exceção."""
    jogo = _jogo(tmp_path)

    def negar(*_args, **_kwargs):
        raise PermissionError("pasta negada")

    monkeypatch.setattr(Path, "mkdir", negar)
    cor = session_fita.Cor(340, 1000, 150)
    assert session_fita.salvar_cor(jogo.game_id, jogo.name, cor) is None
    assert not session_fita.escolhida(jogo.game_id)


def test_redefinir_nao_levanta_quando_o_unlink_falha(tmp_path, monkeypatch, schema):
    jogo = _jogo(tmp_path)
    session_fita.salvar_cor(jogo.game_id, jogo.name, session_fita.Cor(340, 1000, 150))

    def negar(*_args, **_kwargs):
        raise OSError("arquivo em uso")

    monkeypatch.setattr(Path, "unlink", negar)
    assert session_fita.redefinir(jogo.game_id) is None


def test_sidecar_corrompido_volta_para_a_capa(tmp_path, schema):
    jogo = _jogo(tmp_path)
    shared.fitas_dir.mkdir(parents=True, exist_ok=True)
    (shared.fitas_dir / f"{jogo.game_id}.json").write_text("{lixo", encoding="utf-8")
    assert not session_fita.escolhida(jogo.game_id)
    cor = session_fita.cor_do_jogo(jogo)
    assert cor.matiz < 10 or cor.matiz > 350


class FitaFalsa:
    """Um módulo Tuya de mentira, que anota o que mandaram nele."""

    def __init__(self, dps=None, quebrada=False):
        self.dps = dps or {"20": False, "21": "colour", "24": "000003e800b4"}
        self.quebrada = quebrada
        self.recebidos = []

    def status(self):
        if self.quebrada:
            return {"Error": "Network Error: Device Unreachable", "Err": "905"}
        return {"dps": dict(self.dps)}

    def set_multiple_values(self, valores, nowait=False):
        if self.quebrada:
            return {"Error": "Network Error: Device Unreachable", "Err": "905"}
        self.recebidos.append(dict(valores))
        self.dps.update({str(k): v for k, v in valores.items()})
        return {"dps": dict(self.dps)}


@pytest.fixture
def falsas(monkeypatch):
    """Troca as fitas de verdade por módulos de mentira, por id."""
    modulos = {}

    def montar(*fitas_falsas):
        lista = []
        for indice, quebrada in enumerate(fitas_falsas):
            fita = session_fita.Fita(f"Fita {indice}", f"eb{indice}", "1.2.3.4", "k")
            modulos[fita.id] = FitaFalsa(quebrada=quebrada)
            lista.append(fita)
        session_fita.gravar_fitas(lista)
        monkeypatch.setattr(session_fita, "_dispositivo", lambda f: modulos[f.id])
        return modulos

    return montar


def test_cor_vira_hexadecimal_do_jeito_do_modulo():
    assert session_fita.hsv_hex(session_fita.Cor(340, 1000, 150)) == "015403e80096"


def test_hexadecimal_volta_a_ser_cor():
    assert session_fita.cor_de_hex("015403e80096") == session_fita.Cor(340, 1000, 150)


def test_hexadecimal_estranho_vira_nada():
    assert session_fita.cor_de_hex("nao-e-hex") is None


def test_ler_estado_traz_ligada_e_cor(falsas):
    modulos = falsas(False)
    fita = session_fita.fitas()[0]
    assert session_fita.ler_estado(fita) == {"ligada": False, "cor": "000003e800b4"}
    assert modulos


def test_ler_estado_de_fita_fora_do_ar_e_nada(falsas):
    falsas(True)
    assert session_fita.ler_estado(session_fita.fitas()[0]) is None


def test_aplicar_liga_poe_modo_cor_e_manda_a_cor(falsas):
    modulos = falsas(False)
    fita = session_fita.fitas()[0]
    assert session_fita.aplicar(fita, True, "015403e80096") is True
    assert modulos[fita.id].recebidos == [
        {"20": True, "21": "colour", "24": "015403e80096"}
    ]


def test_aplicar_em_fita_fora_do_ar_devolve_falso(falsas):
    falsas(True)
    assert session_fita.aplicar(session_fita.fitas()[0], True, "015403e80096") is False


def test_dispositivo_nao_insiste_com_fita_muda(monkeypatch):
    """O único teste que passa pelo ``_dispositivo`` de verdade.

    Prende o que a fita fora da tomada custa: sem cortar as retentativas, o
    fechamento do app — que é síncrono — esperaria dezenas de segundos por um
    módulo que não vai responder.
    """
    recebidos = {}

    class BulbFalso:
        def __init__(self, *args, **kwargs):
            recebidos["args"] = args
            recebidos["kwargs"] = kwargs

        def set_socketTimeout(self, segundos):
            recebidos["espera"] = segundos

    falso = ModuleType("tinytuya")
    falso.BulbDevice = BulbFalso
    monkeypatch.setitem(sys.modules, "tinytuya", falso)

    fita = session_fita.Fita("Centro", "eb00", "192.168.0.150", "chave", "3.3")
    assert isinstance(session_fita._dispositivo(fita), BulbFalso)

    assert recebidos["args"] == (fita.id, fita.ip, fita.key)
    assert recebidos["kwargs"] == {
        "version": 3.3,
        "persist": False,
        "connection_retry_limit": 1,
        "connection_retry_delay": 0,
    }
    assert recebidos["espera"] == session_fita.ESPERA


def test_abrir_guarda_o_estado_e_veste_o_roxo(falsas, schema):
    schema.set_boolean("session-fita", True)
    modulos = falsas(False, False)
    session_fita._guardar_e_vestir()

    guardado = json.loads(schema.get_string("fita-estado-anterior"))
    assert set(guardado) == {"eb0", "eb1"}
    assert guardado["eb0"] == {"ligada": False, "cor": "000003e800b4"}

    for modulo in modulos.values():
        ultimo = modulo.recebidos[-1]
        assert ultimo["20"] is True
        assert session_fita.cor_de_hex(ultimo["24"])[:2] == session_fita.ROXO_DO_APP


def test_devolver_repoe_o_estado_e_limpa_a_chave(falsas, schema):
    schema.set_boolean("session-fita", True)
    modulos = falsas(False)
    session_fita._guardar_e_vestir()
    session_fita._devolver()

    assert schema.get_string("fita-estado-anterior") == ""
    ultimo = modulos["eb0"].recebidos[-1]
    assert ultimo["20"] is False
    assert ultimo["24"] == "000003e800b4"


def test_fita_fora_do_ar_nao_derruba_as_outras(falsas, schema):
    schema.set_boolean("session-fita", True)
    modulos = falsas(False, True)
    session_fita._guardar_e_vestir()

    assert list(json.loads(schema.get_string("fita-estado-anterior"))) == ["eb0"]
    assert modulos["eb0"].recebidos


def test_orfaos_desfazem_a_sessao_que_ficou(falsas, schema):
    schema.set_boolean("session-fita", True)
    modulos = falsas(False)
    schema.set_string(
        "fita-estado-anterior",
        json.dumps({"eb0": {"ligada": True, "cor": "00b403e80064"}}),
    )
    session_fita.restaurar_orfaos()

    assert schema.get_string("fita-estado-anterior") == ""
    assert modulos["eb0"].recebidos[-1]["24"] == "00b403e80064"


def test_sem_fita_configurada_o_recurso_nao_age(schema):
    schema.set_boolean("session-fita", True)
    assert session_fita.ligada() is False
    session_fita._guardar_e_vestir()
    assert schema.get_string("fita-estado-anterior") == ""


def test_desligado_nas_preferencias_nao_age(falsas, schema):
    schema.set_boolean("session-fita", False)
    falsas(False)
    assert session_fita.ligada() is False


def test_abrir_nao_faz_rede_na_thread_de_ui(falsas, monkeypatch, schema):
    """``abrir`` só agenda: os dois passos do arranque são rede pura.

    Com a thread capturada em vez de iniciada, ``abrir`` volta sem ter mandado
    comando nenhum e sem ter tocado na chave.
    """
    schema.set_boolean("session-fita", True)
    modulos = falsas(False)

    tarefas = []
    monkeypatch.setattr(session_fita, "_em_thread", tarefas.append)

    session_fita.abrir()
    assert modulos["eb0"].recebidos == []
    assert schema.get_string("fita-estado-anterior") == ""

    tarefas[0]()
    assert modulos["eb0"].recebidos
    assert json.loads(schema.get_string("fita-estado-anterior"))


def test_arrancar_desfaz_o_orfao_antes_de_guardar_o_novo(falsas, schema):
    """A ordem importa: desfazer primeiro, guardar depois.

    Invertida, o roxo que o próprio app pintou viraria "o estado de antes" do
    usuário, e o fechamento devolveria as fitas ao roxo para sempre.
    """
    schema.set_boolean("session-fita", True)
    modulos = falsas(False)
    orfao = {"eb0": {"ligada": True, "cor": "00b403e80064"}}
    schema.set_string("fita-estado-anterior", json.dumps(orfao))

    session_fita._arrancar()

    roxo = session_fita.hsv_hex(session_fita._roxo())
    assert [r["24"] for r in modulos["eb0"].recebidos] == ["00b403e80064", roxo]

    guardado = json.loads(schema.get_string("fita-estado-anterior"))
    assert guardado == orfao
    assert guardado["eb0"]["cor"] != roxo


def test_trava_ignora_o_arranque_que_chegou_junto(falsas, schema):
    """Dois ``do_activate`` próximos não podem ler a chave ao mesmo tempo."""
    schema.set_boolean("session-fita", True)
    modulos = falsas(False)

    assert session_fita._TRAVA_ARRANQUE.acquire(blocking=False)
    try:
        assert session_fita._arrancar() is None
    finally:
        session_fita._TRAVA_ARRANQUE.release()

    assert modulos["eb0"].recebidos == []
    assert schema.get_string("fita-estado-anterior") == ""


def test_desligado_nas_preferencias_ainda_desfaz_o_orfao(falsas, monkeypatch, schema):
    """Quem desligou a opção no meio do caminho não fica com as fitas vestidas."""
    schema.set_boolean("session-fita", False)
    modulos = falsas(False)
    schema.set_string(
        "fita-estado-anterior",
        json.dumps({"eb0": {"ligada": True, "cor": "00b403e80064"}}),
    )

    tarefas = []
    monkeypatch.setattr(session_fita, "_em_thread", tarefas.append)
    session_fita.abrir()
    tarefas[0]()

    assert schema.get_string("fita-estado-anterior") == ""
    assert [r["24"] for r in modulos["eb0"].recebidos] == ["00b403e80064"]


def test_desligado_e_sem_orfao_o_arranque_nem_agenda(falsas, monkeypatch, schema):
    schema.set_boolean("session-fita", False)
    falsas(False)

    tarefas = []
    monkeypatch.setattr(session_fita, "_em_thread", tarefas.append)
    assert session_fita.abrir() is None
    assert tarefas == []


def test_estado_adulterado_nao_levanta(falsas, schema):
    """Chave mexida à mão não pode virar ``AttributeError`` cru."""
    modulos = falsas(False, False)
    schema.set_string(
        "fita-estado-anterior",
        json.dumps({"eb0": "roxo", "eb1": {"ligada": True, "cor": "00b403e80064"}}),
    )

    assert session_fita._devolver() is None
    assert modulos["eb0"].recebidos == []
    assert modulos["eb1"].recebidos[-1]["24"] == "00b403e80064"
    assert schema.get_string("fita-estado-anterior") == ""


def test_segunda_chamada_nao_repinta_o_estado_guardado(falsas, schema):
    """O ``do_activate`` dispara de novo quando uma segunda instância é
    encaminhada para a viva. A chave não pode ser regravada aí: o estado a
    devolver é o primeiro, e não o roxo que o próprio app pintou por cima.
    """
    schema.set_boolean("session-fita", True)
    modulos = falsas(False)
    modulos["eb0"].dps = {"20": True, "21": "colour", "24": "00b403e80064"}

    session_fita._guardar_e_vestir()
    primeiro = schema.get_string("fita-estado-anterior")
    assert json.loads(primeiro) == {"eb0": {"ligada": True, "cor": "00b403e80064"}}

    # O próprio `_vestir` já deixou o módulo roxo: é exatamente esse estado
    # errado que a segunda chamada gravaria se não houvesse a guarda.
    assert modulos["eb0"].dps["24"] != "00b403e80064"

    session_fita._guardar_e_vestir()
    assert schema.get_string("fita-estado-anterior") == primeiro

    session_fita._devolver()
    ultimo = modulos["eb0"].recebidos[-1]
    assert ultimo["20"] is True
    assert ultimo["24"] == "00b403e80064"


def test_comecar_tira_a_cor_do_jogo_dentro_da_thread(
    falsas, tmp_path, monkeypatch, schema
):
    """A cor do jogo é calculada na thread, e não antes dela.

    Observável com a thread capturada em vez de iniciada: ``comecar`` volta sem
    ter chamado ``cor_do_jogo`` nenhuma vez. Tirar a cor abre e quantiza a capa
    em disco — I/O mais CPU, e isso não pode correr na thread de UI enquanto o
    jogo abre. A cor sai certa quando a tarefa capturada roda.
    """
    schema.set_boolean("session-fita", True)
    modulos = falsas(False)
    jogo = _jogo(tmp_path)
    escolha = session_fita.Cor(340, 1000, 150)
    session_fita.salvar_cor(jogo.game_id, jogo.name, escolha)

    tarefas = []
    monkeypatch.setattr(session_fita, "_em_thread", tarefas.append)
    chamadas = []
    de_verdade = session_fita.cor_do_jogo
    monkeypatch.setattr(
        session_fita,
        "cor_do_jogo",
        lambda game: (chamadas.append(game), de_verdade(game))[1],
    )

    session_fita.comecar(jogo)
    assert chamadas == []

    tarefas[0]()
    assert chamadas == [jogo]
    assert modulos["eb0"].recebidos[-1]["24"] == session_fita.hsv_hex(escolha)


def test_fechar_nao_espera_alem_do_prazo(falsas, monkeypatch, schema):
    """Fita muda não segura o fechamento do app.

    A chave fica gravada de propósito quando o prazo estoura: é o
    ``restaurar_orfaos`` do próximo arranque que termina o serviço.
    """
    schema.set_boolean("session-fita", True)
    falsas(False)
    session_fita._guardar_e_vestir()

    monkeypatch.setattr(session_fita, "PRAZO_FECHAMENTO", 0.2)
    preso = threading.Event()
    monkeypatch.setattr(session_fita, "_devolver", preso.wait)

    comeco = time.monotonic()
    try:
        assert session_fita.fechar() is None
        gasto = time.monotonic() - comeco
    finally:
        preso.set()

    assert gasto < 2
    assert schema.get_string("fita-estado-anterior")
