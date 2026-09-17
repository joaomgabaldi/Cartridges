# test_session_fita.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""As fitas de LED: o que fica em disco, qual cor cada jogo recebe, e quem
chama o ciclo — o arranque do app, a sessão e o fechamento."""

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
    # O carimbo da última varredura é estado de módulo, e sobreviveria ao
    # teste: sem zerá-lo, o teste seguinte pularia a varredura pelo intervalo
    # mínimo e passaria pelo motivo errado.
    monkeypatch.setattr(session_fita, "_ultima_varredura", None)
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


def test_aplicar_sem_cor_manda_so_o_liga_desliga(falsas):
    """Fita apagada às vezes não reporta a cor, e o estado sai com ela vazia.

    Mandar ``24: ""`` faz o módulo recusar o comando inteiro — e aí a fita não
    apaga, que é justamente o que a devolução do fechamento promete.
    """
    modulos = falsas(False)
    fita = session_fita.fitas()[0]

    assert session_fita.aplicar(fita, False, "") is True
    assert modulos[fita.id].recebidos == [{"20": False}]


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


def test_varredura_vira_mapa_de_id_para_ip():
    achados = {
        "192.168.0.150": {"gwId": "eb0", "version": "3.3"},
        "192.168.0.195": {"gwId": "eb1", "version": "3.3"},
        "192.168.0.99": {"sem_id": True},
    }
    assert session_fita.ips_da_varredura(achados) == {
        "eb0": "192.168.0.150",
        "eb1": "192.168.0.195",
    }


def _tinytuya_que_varre(monkeypatch, resposta):
    """Põe no lugar da ``tinytuya`` um módulo cujo ``deviceScan`` é anotado.

    ``resposta`` é o que a varredura devolve, ou a exceção que ela levanta.
    """
    chamadas = []

    def varrer(*args, **kwargs):
        chamadas.append((args, kwargs))
        if isinstance(resposta, Exception):
            raise resposta
        return resposta

    falso = ModuleType("tinytuya")
    falso.deviceScan = varrer
    monkeypatch.setitem(sys.modules, "tinytuya", falso)
    return chamadas


def test_redescobrir_grava_o_ip_que_o_dhcp_trocou(monkeypatch):
    """O casamento é pelo id do módulo: no arquivo, o que envelhece é o IP."""
    antes = [
        session_fita.Fita("Centro", "eb0", "192.168.0.150", "k"),
        session_fita.Fita("Direita", "eb1", "192.168.0.151", "k2", "3.4"),
    ]
    session_fita.gravar_fitas(antes)
    chamadas = _tinytuya_que_varre(monkeypatch, {"192.168.0.77": {"gwId": "eb0"}})

    assert session_fita._redescobrir_ips() is None
    assert session_fita.fitas() == [
        antes[0]._replace(ip="192.168.0.77"),
        antes[1],  # quem não apareceu na varredura fica exatamente como estava
    ]

    # Calada, curta e sem enquete: só os IPs interessam aqui.
    args, opcoes = chamadas[0]
    assert args[:2] == (False, session_fita.ESPERA_VARREDURA)
    assert opcoes.get("poll") is False


def test_varredura_que_falha_deixa_o_arquivo_como_estava(monkeypatch):
    """Rede caída não pode apagar a configuração nem levantar na thread."""
    antes = [session_fita.Fita("Centro", "eb0", "192.168.0.150", "k")]
    session_fita.gravar_fitas(antes)
    _tinytuya_que_varre(monkeypatch, OSError("rede sumiu"))

    assert session_fita._redescobrir_ips() is None
    assert session_fita.fitas() == antes


def test_varredura_respeita_o_intervalo_minimo(monkeypatch):
    """Fita fora da tomada não pode custar doze segundos em toda troca de cor.

    Duas falhas seguidas dentro do intervalo varrem uma vez só; passado o
    intervalo, a varredura volta a valer — é o IP trocado pelo DHCP que ela
    existe para consertar, e esse caso não pode ficar sem conserto.
    """
    session_fita.gravar_fitas([session_fita.Fita("Centro", "eb0", "1.2.3.4", "k")])
    chamadas = _tinytuya_que_varre(monkeypatch, {})
    relogio = [1000.0]
    monkeypatch.setattr(session_fita.time, "monotonic", lambda: relogio[0])

    session_fita._redescobrir_ips()
    session_fita._redescobrir_ips()
    assert len(chamadas) == 1

    relogio[0] += session_fita.INTERVALO_VARREDURA + 1
    session_fita._redescobrir_ips()
    assert len(chamadas) == 2

    # O arranque força: a fita que o assistente acabou de gravar entra sem IP,
    # e ali a varredura é a única maneira de achá-la.
    session_fita._redescobrir_ips(forcar=True)
    assert len(chamadas) == 3


def test_fita_que_falha_dispara_uma_redescoberta_e_uma_segunda_tentativa(
    falsas, monkeypatch
):
    modulos = falsas(True)
    tentativas = []

    def redescobrir():
        tentativas.append("varreu")
        # A varredura "conserta" o módulo: ele passa a responder.
        modulos["eb0"].quebrada = False

    monkeypatch.setattr(session_fita, "_redescobrir_ips", redescobrir)
    session_fita._vestir(session_fita.Cor(284, 620, 180))

    assert tentativas == ["varreu"]
    assert modulos["eb0"].recebidos  # a segunda tentativa chegou


def test_tudo_respondendo_nao_varre_a_rede(falsas, monkeypatch):
    falsas(False)
    monkeypatch.setattr(
        session_fita,
        "_redescobrir_ips",
        lambda: pytest.fail("varreu a rede sem precisar"),
    )
    session_fita._vestir(session_fita.Cor(284, 620, 180))


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


def test_ninguem_respondendo_varre_e_le_o_estado_de_novo(falsas, monkeypatch, schema):
    """A fita que o assistente acabou de gravar entra sem IP, de propósito.

    Nesse primeiro arranque a leitura falha em todas, e sem a releitura o
    estado original de cada fita se perderia justamente na estreia do recurso:
    o ``_vestir`` conserta o endereço logo em seguida e acende tudo, mas aí já
    é tarde para saber como elas estavam.
    """
    schema.set_boolean("session-fita", True)
    modulos = falsas(True, True)
    varreduras = []

    def redescobrir(forcar=False):
        varreduras.append(forcar)
        for modulo in modulos.values():
            modulo.quebrada = False

    monkeypatch.setattr(session_fita, "_redescobrir_ips", redescobrir)
    session_fita._guardar_e_vestir()

    # Forçada: o piso entre varreduras não pode calar a estreia do recurso.
    assert varreduras == [True]
    guardado = json.loads(schema.get_string("fita-estado-anterior"))
    assert set(guardado) == {"eb0", "eb1"}
    assert guardado["eb0"] == {"ligada": False, "cor": "000003e800b4"}


def test_uma_fita_respondendo_ja_dispensa_a_varredura_na_leitura(
    falsas, monkeypatch, schema
):
    """Varrer para ler é só para o caso de NINGUÉM responder.

    Com uma fita muda entre duas, a varredura ainda acontece — mas lá no
    ``_vestir``, com a chave já gravada. Se a leitura tivesse varrido, a
    primeira varredura veria a chave ainda vazia, e é isso que se prende aqui.
    """
    schema.set_boolean("session-fita", True)
    falsas(False, True)
    chave_na_varredura = []
    monkeypatch.setattr(
        session_fita,
        "_redescobrir_ips",
        lambda: chave_na_varredura.append(schema.get_string("fita-estado-anterior")),
    )

    session_fita._guardar_e_vestir()

    assert len(chave_na_varredura) == 1
    assert json.loads(chave_na_varredura[0]) == {
        "eb0": {"ligada": False, "cor": "000003e800b4"}
    }


def test_todas_fora_da_tomada_varrem_uma_vez_so(falsas, monkeypatch, schema):
    """Varredura que não achou ninguém não é repetida no mesmo arranque.

    Sem isto, o arranque com tudo fora da tomada varreria duas vezes: uma para
    ler o estado e outra dentro do ``_vestir``, a poucos segundos da primeira e
    na mesma rede.
    """
    schema.set_boolean("session-fita", True)
    falsas(True, True)
    varreduras = []
    monkeypatch.setattr(
        session_fita,
        "_redescobrir_ips",
        lambda forcar=False: varreduras.append("varreu"),
    )

    assert session_fita._guardar_e_vestir() is None

    assert varreduras == ["varreu"]
    assert json.loads(schema.get_string("fita-estado-anterior")) == {}


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

    roxo = session_fita.hsv_hex(session_fita.roxo())
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


# region As Preferências


def _preferencias(monkeypatch):
    """A tela de Preferências de verdade, como em ``test_session_monitors``."""
    import cartridges.preferences as preferences_module  # noqa: PLC0415
    from cartridges.metadata_refresh import MetadataRefresh  # noqa: PLC0415

    monkeypatch.setattr(preferences_module, "get_metadata_refresh", MetadataRefresh)
    return preferences_module.CartridgesPreferences()


def test_preferencias_bloqueiam_a_fita_sem_configuracao(monkeypatch, schema):
    """Sem fita configurada não há o que ligar, e a tela diz isso."""
    schema.set_boolean("session-fita", True)

    preferencias = _preferencias(monkeypatch)

    assert preferencias.session_fita_switch.get_sensitive() is False
    assert preferencias.session_fita_switch.get_subtitle() == "Nenhuma fita configurada"
    assert schema.get_boolean("session-fita") is False


def test_preferencias_liberam_a_fita_e_contam_as_configuradas(monkeypatch, schema):
    """Com fita gravada o interruptor responde, e o subtítulo diz quantas são."""
    session_fita.gravar_fitas(
        [
            session_fita.Fita("Centro", "eb0", "192.168.0.150", "chave"),
            session_fita.Fita("Direita", "eb1", "192.168.0.151", "chave"),
        ]
    )

    preferencias = _preferencias(monkeypatch)

    assert preferencias.session_fita_switch.get_sensitive() is True
    assert preferencias.session_fita_switch.get_subtitle() == "2 fitas configuradas"


def test_ligar_o_interruptor_arranca_o_ciclo(monkeypatch, schema):
    """Ligar com o app aberto tem de guardar o estado de antes na hora.

    Sem isto, o ciclo só arrancaria no arranque seguinte: a chave
    ``fita-estado-anterior`` ficaria vazia, a sessão seguinte vestiria a cor do
    jogo e o fechamento não teria o que devolver.
    """
    session_fita.gravar_fitas([session_fita.Fita("Centro", "eb0", "1.2.3.4", "k")])
    chamadas = []
    monkeypatch.setattr(session_fita, "abrir", lambda: chamadas.append("abrir"))

    preferencias = _preferencias(monkeypatch)
    assert chamadas == []

    preferencias.session_fita_switch.set_active(True)
    assert chamadas == ["abrir"]

    # Desligar não desfaz nada aqui: quem devolve as fitas é o fechamento.
    preferencias.session_fita_switch.set_active(False)
    assert chamadas == ["abrir"]


def test_abrir_a_tela_com_o_recurso_ligado_nao_arranca(monkeypatch, schema):
    """Abrir as Preferências não é ligar o recurso: construir a tela não acende.

    O ``bind`` do dublê de schema não faz nada, e é justamente ele que acende o
    interruptor no meio do ``__init__``. Imitado aqui para que a construção
    passe pelo mesmo ``notify::active`` do app de verdade — é o que torna este
    teste capaz de pegar um handler ligado cedo demais.
    """
    session_fita.gravar_fitas([session_fita.Fita("Centro", "eb0", "1.2.3.4", "k")])
    schema.set_boolean("session-fita", True)
    monkeypatch.setattr(
        schema,
        "bind",
        lambda chave, widget, prop, _flags: widget.set_property(
            prop, schema.get_boolean(chave)
        ),
    )
    chamadas = []
    monkeypatch.setattr(session_fita, "abrir", lambda: chamadas.append("abrir"))

    preferencias = _preferencias(monkeypatch)

    assert preferencias.session_fita_switch.get_active() is True
    assert chamadas == []


def test_ligar_grava_a_chave_antes_de_arrancar(monkeypatch, schema):
    """A chave tem de estar gravada quando o ``abrir`` roda, e não depois.

    ``abrir`` decide pela chave, via ``ligada()``, e não pelo widget. Deixar
    isso por conta do ``bind`` do GSettings amarraria o recurso à ordem em que
    os handlers foram conectados: invertida, o ciclo não armaria, em silêncio.
    O dublê lê a chave no momento da chamada, que é o instante que importa.
    """
    session_fita.gravar_fitas([session_fita.Fita("Centro", "eb0", "1.2.3.4", "k")])
    vista = []
    monkeypatch.setattr(
        session_fita, "abrir", lambda: vista.append(schema.get_boolean("session-fita"))
    )

    preferencias = _preferencias(monkeypatch)
    preferencias.session_fita_switch.set_active(True)

    assert vista == [True]


def test_o_teste_nao_escreve_em_tela_ja_fechada(monkeypatch, schema):
    """O resultado do "Testar" volta pelo ``idle_add``, e a tela pode ter ido.

    Com o diálogo fechado no meio da conversa com as fitas, o que volta não tem
    onde escrever — e o subtítulo fica no "Testando…" que o clique deixou.

    A thread e o ``idle_add`` são capturados em vez de rodados, como no
    ``test_abrir_nao_faz_rede_na_thread_de_ui``: o que se prova aqui é o que a
    volta faz, e rodar o laço principal de verdade não acrescentaria nada.
    """
    import cartridges.preferences as preferences_module  # noqa: PLC0415

    session_fita.gravar_fitas([session_fita.Fita("Centro", "eb0", "1.2.3.4", "k")])
    monkeypatch.setattr(session_fita, "aplicar", lambda *_args: True)
    monkeypatch.setattr(
        preferences_module,
        "threading",
        SimpleNamespace(Thread=lambda target, daemon: SimpleNamespace(start=target)),
    )
    agendadas = []
    monkeypatch.setattr(
        preferences_module.GLib,
        "idle_add",
        lambda funcao, *args: agendadas.append((funcao, args)),
    )
    preferencias = _preferencias(monkeypatch)

    preferencias.testar_fitas()
    assert preferencias.fita_testar_row.get_subtitle() == "Testando…"
    volta, argumentos = agendadas.pop()
    volta(*argumentos)
    assert preferencias.fita_testar_row.get_subtitle() == "Todas responderam"

    preferencias.testar_fitas()
    monkeypatch.setattr(preferences_module.CartridgesPreferences, "is_open", False)
    volta, argumentos = agendadas.pop()

    assert volta(*argumentos) is False
    assert preferencias.fita_testar_row.get_subtitle() == "Testando…"


def test_fechar_o_assistente_com_fita_nova_arranca_o_ciclo(monkeypatch, schema):
    """Configurar a primeira fita com o recurso já ligado também arranca."""
    schema.set_boolean("session-fita", True)
    chamadas = []
    monkeypatch.setattr(session_fita, "abrir", lambda: chamadas.append("abrir"))

    preferencias = _preferencias(monkeypatch)
    # Sem fita, `atualizar_fitas` desligou a chave: não há o que arrancar.
    preferencias.fitas_configuradas()
    assert chamadas == []

    session_fita.gravar_fitas([session_fita.Fita("Centro", "eb0", "1.2.3.4", "k")])
    schema.set_boolean("session-fita", True)
    preferencias.fitas_configuradas()

    assert chamadas == ["abrir"]
    assert preferencias.session_fita_switch.get_sensitive() is True


# endregion
# region A fiação: quem chama o ciclo


def test_a_janela_e_o_app_falam_com_o_mesmo_modulo_de_fita():
    """A fiação só vale se for ESTE módulo que os dois lados chamam.

    Sem isto, um `import` para o lugar errado passaria despercebido: os testes
    abaixo trocariam funções de um módulo que a janela não usa, e continuariam
    verdes enquanto o app não acendia fita nenhuma.
    """
    import cartridges.main as main_module  # noqa: PLC0415
    import cartridges.window as window_module  # noqa: PLC0415

    assert window_module.session_fita is session_fita
    assert main_module.session_fita is session_fita


def test_a_sessao_veste_e_despe_as_fitas(real_window, make_game, monkeypatch):
    """O bloqueador da sessão é quem manda vestir a cor do jogo, e quem despe.

    Pela janela de verdade, e não por um dublê: o que se prova aqui é que as
    duas chamadas estão mesmo nos dois métodos, e que o jogo que chega ao
    `comecar` é o da sessão que acabou de abrir.
    """
    import cartridges.window as window_module  # noqa: PLC0415

    chamadas = []
    monkeypatch.setattr(window_module.session_fita, "comecar", chamadas.append)
    monkeypatch.setattr(
        window_module.session_fita, "voltar", lambda: chamadas.append("voltar")
    )

    jogo = make_game(name="Hollow Knight")
    real_window.show_session_blocker(jogo)
    assert chamadas == [jogo]

    real_window.hide_session_blocker()
    assert chamadas == [jogo, "voltar"]


def test_o_fechamento_do_app_devolve_as_fitas(monkeypatch):
    """`do_shutdown` é a última janela em que ainda há processo para desfazer.

    Sem janela, `save_window_geometry` volta na primeira linha e o resto do
    método é todo `is not None` — sobra exatamente o caminho que interessa.
    """
    import cartridges.main as main_module  # noqa: PLC0415

    chamadas = []
    monkeypatch.setattr(
        main_module.session_fita, "fechar", lambda: chamadas.append("fechar")
    )
    monkeypatch.setattr(shared, "win", None)
    # `CartridgesApplication.__init__` troca `shared.store` por um novo. O
    # monkeypatch de agora não muda nada agora; ele é o que devolve o antigo no
    # fim do teste, para a loja nova não vazar para o teste seguinte.
    monkeypatch.setattr(shared, "store", shared.store)

    assert main_module.CartridgesApplication().do_shutdown() is None
    assert chamadas == ["fechar"]


# endregion

# region A cor na tela do jogo


def test_cor_vai_e_volta_entre_o_seletor_e_o_modulo():
    from gi.repository import Gdk  # noqa: PLC0415

    original = session_fita.Cor(340, 1000, 150)
    rgba = session_fita.cor_para_rgba(original)
    assert isinstance(rgba, Gdk.RGBA)

    volta = session_fita.rgba_para_cor(rgba, 150)
    # Matiz e saturação sobrevivem à ida e à volta, com folga de arredondamento.
    assert abs(volta.matiz - original.matiz) <= 2
    assert abs(volta.saturacao - original.saturacao) <= 10
    assert volta.brilho == 150


@pytest.fixture
def tela(write_record, win):
    """A tela de detalhes de um jogo que ainda não tem cor escolhida.

    Com uma fita gravada: sem nenhuma, as duas linhas ficam insensíveis e a
    tela não mostra cor nenhuma para escolher — ver
    ``test_sem_fita_a_linha_fica_insensivel_e_nao_calcula_cor``.
    """
    from cartridges.details_dialog import DetailsDialog  # noqa: PLC0415
    from cartridges.game import Game  # noqa: PLC0415

    session_fita.gravar_fitas([session_fita.Fita("Centro", "eb0", "1.2.3.4", "k")])
    write_record("jogo-fita", name="Jogo")
    jogo = Game(
        {
            "game_id": "jogo-fita",
            "name": "Jogo",
            "source": "shortcuts",
            "executable": r'start "" "C:\g\jogo.exe"',
        }
    )
    return DetailsDialog(jogo), jogo


def test_sem_fita_a_linha_fica_insensivel_e_nao_calcula_cor(
    write_record, app_dirs, win, monkeypatch
):
    """Sem fita configurada não há cor para escolher — nem para calcular.

    Como a linha do papel de parede sem um segundo monitor. E de quebra: tirar
    a dominante da capa custa milissegundos na thread de UI em toda abertura da
    tela, e aqui seriam gastos por uma fita que não existe — por isso o espião
    na cor da capa, e não só a checagem das duas linhas.
    """
    from cartridges.details_dialog import DetailsDialog  # noqa: PLC0415
    from cartridges.game import Game  # noqa: PLC0415

    write_record("jogo-sem-fita", name="Jogo")
    # Com capa de verdade: sem ela, `cor_do_jogo` nem chegaria à dominante e o
    # espião abaixo não provaria nada.
    Image.new("RGB", (60, 90), (220, 20, 20)).save(
        app_dirs.covers / "jogo-sem-fita.webp"
    )
    monkeypatch.setattr(
        session_fita,
        "dominante",
        lambda *_a, **_k: pytest.fail("calculou a cor da capa sem fita configurada"),
    )

    jogo = Game(
        {
            "game_id": "jogo-sem-fita",
            "name": "Jogo",
            "source": "shortcuts",
            "executable": r'start "" "C:\g\jogo.exe"',
        }
    )
    dialog = DetailsDialog(jogo)

    assert dialog.fita_row.get_sensitive() is False
    assert dialog.fita_brilho_row.get_sensitive() is False
    assert dialog.fita_row.get_subtitle() == "Nenhuma fita configurada"
    assert dialog.fita_brilho_row.get_subtitle() == "Nenhuma fita configurada"
    assert not dialog.fita_button_reset.get_visible()

    # E o Aplicar não marca escolha nenhuma: não houve cor mostrada.
    dialog.aplicar_fita(jogo)
    assert session_fita.escolhida(jogo.game_id) is False


def test_aplicar_sem_mexer_na_cor_nao_marca_escolha(tela):
    """Quem abriu a tela para renomear o jogo não pediu cor nenhuma.

    Gravar aqui tiraria o jogo da cor automática para sempre, e sem que
    ninguém tivesse escolhido cor alguma.
    """
    dialog, jogo = tela

    dialog.aplicar_fita(jogo)

    assert session_fita.escolhida(jogo.game_id) is False


def test_cor_trocada_na_tela_vira_escolha(tela):
    dialog, jogo = tela

    dialog.fita_color_button.set_rgba(
        session_fita.cor_para_rgba(session_fita.Cor(120, 900, 0))
    )
    dialog.aplicar_fita(jogo)

    assert session_fita.escolhida(jogo.game_id)
    assert abs(session_fita.cor_do_jogo(jogo).matiz - 120) <= 2


def _com_escolha(dialog, jogo, cor=session_fita.Cor(340, 1000, 150)):
    """Deixa o jogo com cor escolhida e a tela mostrando essa escolha."""
    session_fita.salvar_cor(jogo.game_id, jogo.name, cor)
    dialog.atualizar_fita()
    return cor


def test_a_linha_mostra_a_escolha_e_o_botao_de_voltar(tela):
    """De quebra, o único teste que constrói a linha inteira do .blp."""
    dialog, jogo = tela
    assert not dialog.fita_button_reset.get_visible()

    _com_escolha(dialog, jogo)

    assert dialog.fita_button_reset.get_visible()
    assert dialog.fita_row.get_subtitle() == "Escolhida por você"


def test_redefinir_sem_aplicar_nao_apaga_a_escolha(tela):
    """Como o resto da tela: a intenção fica em memória até o Aplicar.

    Quem clica em "voltar ao automático" e fecha a tela no X não pediu para
    perder a cor que tinha escolhido.
    """
    dialog, jogo = tela
    _com_escolha(dialog, jogo)

    dialog.redefinir_fita()

    assert session_fita.escolhida(jogo.game_id)
    # A tela já mostra o automático, e o botão saiu junto com a escolha.
    assert not dialog.fita_button_reset.get_visible()
    assert dialog.fita_row.get_subtitle() == "Tirada da capa"


def test_redefinir_e_aplicar_apaga_a_escolha(tela):
    dialog, jogo = tela
    _com_escolha(dialog, jogo)

    dialog.redefinir_fita()
    dialog.aplicar_fita(jogo)

    assert not session_fita.escolhida(jogo.game_id)


def test_cor_nova_depois_de_redefinir_vence_a_redefinicao(tela):
    """O que vale é o que está na tela na hora do Aplicar."""
    dialog, jogo = tela
    _com_escolha(dialog, jogo)

    dialog.redefinir_fita()
    dialog.fita_color_button.set_rgba(
        session_fita.cor_para_rgba(session_fita.Cor(120, 900, 0))
    )
    dialog.aplicar_fita(jogo)

    assert session_fita.escolhida(jogo.game_id)
    assert abs(session_fita.cor_do_jogo(jogo).matiz - 120) <= 2


def test_sem_fita_o_aplicar_nao_apaga_a_escolha_que_o_jogo_tinha(write_record, win):
    """Tirar as fitas da configuração não pode custar a cor já escolhida.

    Sem fita a linha fica insensível e nunca é preenchida, então o que está no
    seletor é o padrão do .blp. Quem abre a tela só para renomear o jogo e
    clica em Aplicar veria a escolha de disco trocada por esse lixo, em
    silêncio.
    """
    from cartridges.details_dialog import DetailsDialog  # noqa: PLC0415
    from cartridges.game import Game  # noqa: PLC0415

    write_record("jogo-guardado", name="Jogo")
    jogo = Game(
        {
            "game_id": "jogo-guardado",
            "name": "Jogo",
            "source": "shortcuts",
            "executable": r'start "" "C:\g\jogo.exe"',
        }
    )
    guardada = session_fita.Cor(340, 1000, 150)
    session_fita.salvar_cor(jogo.game_id, jogo.name, guardada)

    # Nenhuma fita configurada: `gravar_fitas` nunca foi chamado nesta pasta.
    dialog = DetailsDialog(jogo)
    dialog.aplicar_fita(jogo)

    assert session_fita.escolhida(jogo.game_id) is True
    assert session_fita.cor_do_jogo(jogo) == guardada


# endregion
