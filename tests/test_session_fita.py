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
from typing import NamedTuple, Optional

import pytest
from PIL import Image

from cartridges import shared
from cartridges.utils import session_fita


@pytest.fixture(autouse=True)
def pastas(tmp_path, monkeypatch):
    """Tudo o que o módulo grava vai para uma pasta descartável."""
    monkeypatch.setattr(shared, "fitas_dir", tmp_path / "fitas")
    monkeypatch.setattr(shared, "fitas_arquivo", tmp_path / "fitas.json")
    # As conexões abertas, a contagem de falhas e as suspensões também são
    # estado de módulo: um teste que suspendeu uma fita não pode deixá-la
    # suspensa para o seguinte.
    _esquecer_conexoes()
    yield tmp_path
    _esquecer_conexoes()


def _esquecer_conexoes():
    session_fita.fechar_conexoes()
    session_fita._falhas.clear()
    session_fita._suspensas.clear()
    session_fita._mostrada.clear()


@pytest.fixture(autouse=True)
def sem_fade(monkeypatch):
    """Fade de 1,5 s em todo teste deixaria a suíte lenta e mudaria o que os
    testes antigos contam. Os testes do fade ligam de volta."""
    monkeypatch.setattr(session_fita, "DURACAO_FADE", 0)


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


class Msg(NamedTuple):
    """Uma mensagem da fita: o código do protocolo e o que veio dentro."""

    cmd: int
    payload: Optional[dict] = None


RECEBI, AVISO, BATIMENTO, CONSULTA = 7, 8, 9, 10


class SoqueteFalso:
    """O que chegou da fita e ainda não foi lido, em ordem de chegada.

    ``a_caminho`` são respostas que a fita ainda vai mandar: a fita aplica
    mais devagar do que recebe, e só quem espera por elas as vê chegar.
    """

    def __init__(self):
        self.fila = []
        self.a_caminho = []
        self.espera = session_fita.ESPERA

    def chegar(self):
        self.fila += self.a_caminho
        self.a_caminho = []

    def gettimeout(self):
        return self.espera

    def settimeout(self, segundos):
        self.espera = segundos

    def recv(self, _tamanho):
        if not self.fila:
            raise BlockingIOError("nada por ler")
        self.fila.pop(0)
        return b"mensagem"


class FitaFalsa:
    """Um módulo Tuya de mentira, que anota o que mandaram nele.

    Como o de verdade, cada comando volta um "recebi" e depois um aviso com os
    valores aplicados — menos o modo (21), que a fita nunca avisa.
    """

    def __init__(self, dps=None, quebrada=False, demora=0.0):
        self.dps = dps or {"20": False, "21": "colour", "24": "000003e800b4"}
        self.quebrada = quebrada
        # Quanto cada comando custa. Serve para provar que as fitas falam ao
        # mesmo tempo: em fila, três fitas de 0,1s levariam 0,3s.
        self.demora = demora
        self.recebidos = []
        # Quantas conversas correram ao mesmo tempo NESTA fita. O módulo Tuya
        # aceita uma sessão por vez, então este número não pode passar de um.
        self.simultaneos = 0
        self.pico = 0
        self.socket = SoqueteFalso()
        # A fita sobrecarregada às vezes não avisa: medido a 40 degraus/s.
        self.sem_aviso = False
        # Quantos dos próximos comandos a fita joga fora: chegam, ganham o
        # "recebi" e não são aplicados nem avisados.
        self.perder = 0

    def status(self, nowait=False):
        if self.quebrada:
            return {"Error": "Network Error: Device Unreachable", "Err": "905"}
        if nowait:
            self.socket.a_caminho.append(Msg(CONSULTA, {"dps": dict(self.dps)}))
            return None
        return {"dps": dict(self.dps)}

    def close(self):
        self.fechada = True

    def _receive(self):
        self.socket.chegar()
        if not self.socket.fila:
            raise TimeoutError("a fita não respondeu")
        return self.socket.fila.pop(0)

    def _decode_payload(self, payload):
        return payload

    def set_multiple_values(self, valores, nowait=False):
        self.simultaneos += 1
        self.pico = max(self.pico, self.simultaneos)
        try:
            if self.demora:
                time.sleep(self.demora)
            if self.quebrada:
                return {"Error": "Network Error: Device Unreachable", "Err": "905"}
            if self.perder:
                self.perder -= 1
                self.socket.a_caminho.append(Msg(RECEBI))
                return None
            self.recebidos.append(dict(valores))
            self.dps.update({str(k): v for k, v in valores.items()})
            self.socket.a_caminho.append(Msg(RECEBI))
            if not self.sem_aviso:
                aviso = {chave: valor for chave, valor in valores.items() if chave != "21"}
                self.socket.a_caminho.append(Msg(AVISO, {"dps": aviso}))
            return None
        finally:
            self.simultaneos -= 1


def cor_mandada(modulo):
    """A última cor que chegou nesta fita, em qualquer um dos comandos.

    Acender vai em dois passos, a cor antes do liga, para a fita não piscar na
    cor de ontem — então o último comando recebido é o do liga, e quem quer
    conferir a cor tem de procurá-la.
    """
    comandos = [comando for comando in modulo.recebidos if "24" in comando]
    return comandos[-1]["24"] if comandos else None


def estado_mandado(modulo):
    """O último liga/desliga que chegou nesta fita."""
    comandos = [comando for comando in modulo.recebidos if "20" in comando]
    return comandos[-1]["20"] if comandos else None


@pytest.fixture
def falsas(monkeypatch):
    """Troca as fitas de verdade por módulos de mentira, por id."""
    modulos = {}

    def montar(*fitas_falsas, demora=0.0):
        lista = []
        for indice, quebrada in enumerate(fitas_falsas):
            fita = session_fita.Fita(f"Fita {indice}", f"eb{indice}", "1.2.3.4", "k")
            modulos[fita.id] = FitaFalsa(quebrada=quebrada, demora=demora)
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
    # A ordem é o que importa aqui: a cor tem de chegar ANTES do liga, senão a
    # fita acende na cor de ontem, no brilho de ontem, e só depois obedece.
    assert modulos[fita.id].recebidos == [
        {"21": "colour", "24": "015403e80096"},
        {"20": True},
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
        "persist": True,
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


def test_abrir_guarda_o_estado_e_veste_o_roxo(falsas, schema):
    schema.set_boolean("session-fita", True)
    modulos = falsas(False, False)
    session_fita._guardar_e_vestir()

    guardado = json.loads(schema.get_string("fita-estado-anterior"))
    assert set(guardado) == {"eb0", "eb1"}
    assert guardado["eb0"] == {"ligada": False, "cor": "000003e800b4"}

    for modulo in modulos.values():
        assert estado_mandado(modulo) is True
        assert session_fita.cor_de_hex(cor_mandada(modulo))[:2] == session_fita.ROXO_DO_APP


def test_devolver_repoe_o_estado_e_limpa_a_chave(falsas, schema):
    schema.set_boolean("session-fita", True)
    modulos = falsas(False)
    session_fita._guardar_e_vestir()
    session_fita._devolver()

    assert schema.get_string("fita-estado-anterior") == ""
    assert estado_mandado(modulos["eb0"]) is False
    # Apagada não recebe a cor de antes: ela acenderia nela por um instante.
    assert modulos["eb0"].recebidos[-1] == {"20": False}


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
    assert cor_mandada(modulos["eb0"]) == "00b403e80064"


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

    roxo = session_fita.hsv_hex(session_fita.cor_do_app())
    # Só as cores, na ordem: a do órfão primeiro, a do app depois. Os comandos
    # de liga/desliga entram no meio, porque acender manda a cor antes do liga.
    cores = [c["24"] for c in modulos["eb0"].recebidos if "24" in c]
    assert cores == ["00b403e80064", roxo]

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
    assert [c["24"] for c in modulos["eb0"].recebidos if "24" in c] == [
        "00b403e80064"
    ]


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
    assert cor_mandada(modulos["eb1"]) == "00b403e80064"
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
    assert estado_mandado(modulos["eb0"]) is True
    assert cor_mandada(modulos["eb0"]) == "00b403e80064"


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
    assert cor_mandada(modulos["eb0"]) == session_fita.hsv_hex(escolha)


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
        # `Event` de verdade: é o sinal de parada do teste, e trocá-lo por um
        # dublê esconderia justamente o botão que vira "parar".
        SimpleNamespace(
            Thread=lambda target, daemon: SimpleNamespace(start=target),
            Event=threading.Event,
        ),
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

    dialog.fita_color_button.set_property(
        "rgba",
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
    dialog.fita_color_button.set_property(
        "rgba",
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


def test_as_fitas_mudam_de_cor_ao_mesmo_tempo(falsas, schema):
    """Em fila, dá para ver a troca correndo de um monitor para o outro.

    Três fitas de 0,15s levariam 0,45s uma depois da outra; juntas, pouco mais
    que 0,15s. A margem é folgada de propósito, para a máquina ocupada não
    derrubar o teste — o que ele prende é a ordem de grandeza, não o relógio.
    """
    schema.set_boolean("session-fita", True)
    falsas(False, False, False, demora=0.15)

    comeco = time.monotonic()
    session_fita._vestir(session_fita.Cor(284, 620, 180))
    gasto = time.monotonic() - comeco

    # Acender manda dois comandos por fita (cor e depois liga), então o piso é
    # 0,30s. Em fila seriam 0,90s.
    assert gasto < 0.6


def test_nunca_ha_duas_conversas_com_a_mesma_fita(falsas, schema):
    """O módulo Tuya aceita uma sessão por vez; duas dão erro de soquete."""
    schema.set_boolean("session-fita", True)
    modulos = falsas(False, False, demora=0.05)

    linhas = [
        threading.Thread(target=session_fita._vestir, args=(session_fita.cor_do_app(),))
        for _ in range(4)
    ]
    for linha in linhas:
        linha.start()
    for linha in linhas:
        linha.join()

    for modulo in modulos.values():
        assert modulo.pico == 1


def test_o_brilho_vai_e_volta_entre_a_tela_e_o_modulo():
    """A tela conta de 0 a 100; o módulo, de 0 a 1000."""
    assert session_fita.por_cento(1000) == 100
    assert session_fita.por_cento(180) == 18
    assert session_fita.de_por_cento(18) == 180
    assert session_fita.de_por_cento(100) == 1000


def test_o_brilho_da_tela_nunca_apaga_a_fita():
    """Zero por cento não pode virar fita apagada por acidente.

    Apagar é o liga/desliga, não o brilho: uma cor com brilho zero é uma fita
    que parece queimada, e não uma fita desligada.
    """
    assert session_fita.de_por_cento(0) == session_fita.BRILHO_MINIMO
    assert session_fita.de_por_cento(-5) == session_fita.BRILHO_MINIMO
    assert session_fita.de_por_cento(200) == session_fita.BRILHO_CHEIO


def test_a_previa_engole_os_passos_do_meio(falsas, schema):
    """Arrastar o controle gera dezenas de valores; a fita só precisa do último.

    Sem isso, cada passo do controle viraria uma conversa de rede com as três
    fitas e a fila só cresceria enquanto o dedo estivesse no controle.
    """
    schema.set_boolean("session-fita", True)
    modulos = falsas(False, demora=0.05)

    for por_cento in range(1, 40):
        session_fita.previa(session_fita.Cor(284, 620, por_cento * 25))

    # Espera a thread da prévia terminar o que pegou.
    time.sleep(0.4)

    cores = [comando for comando in modulos["eb0"].recebidos if "24" in comando]
    assert 0 < len(cores) < 39
    # A última cor pedida é a que fica valendo na fita.
    assert cores[-1]["24"] == session_fita.hsv_hex(session_fita.Cor(284, 620, 975))


def test_a_previa_nao_mexe_no_liga_desliga(falsas, schema):
    """Prévia é cor, não interruptor: fita apagada continua apagada."""
    schema.set_boolean("session-fita", True)
    modulos = falsas(False)

    session_fita.previa(session_fita.Cor(284, 620, 180))
    time.sleep(0.2)

    assert all("20" not in comando for comando in modulos["eb0"].recebidos)


def test_sem_fita_configurada_a_previa_nao_faz_nada(schema):
    schema.set_boolean("session-fita", True)
    session_fita.previa(session_fita.Cor(284, 620, 180))


def test_a_conexao_aberta_e_reaproveitada(falsas, monkeypatch, schema):
    """Abrir conexão custa ~225 ms; mandar pela aberta, ~11 ms."""
    schema.set_boolean("session-fita", True)
    modulos = falsas(False)
    abertas = []
    monkeypatch.setattr(
        session_fita, "_dispositivo", lambda fita: abertas.append(fita.id) or modulos[fita.id]
    )

    session_fita._vestir(session_fita.cor_do_app())
    session_fita._vestir(session_fita.Cor(120, 1000, 180))

    assert abertas == ["eb0"]


def test_conexao_que_morreu_em_silencio_e_refeita_na_hora(falsas, monkeypatch, schema):
    """Roteador reiniciou ou o PC voltou da suspensão: o soquete guardado morreu.

    O comando não pode se perder por isso — abre outra conexão e segue.
    """
    schema.set_boolean("session-fita", True)
    modulos = falsas(False)
    fita = session_fita.fitas()[0]
    session_fita.aplicar(fita, False, "")

    modulos["eb0"].quebrada = True
    novo = FitaFalsa()
    monkeypatch.setattr(session_fita, "_dispositivo", lambda _fita: novo)

    assert session_fita.aplicar(fita, True, "015403e80096") is True
    assert cor_mandada(novo) == "015403e80096"
    assert modulos["eb0"].fechada


def test_tres_falhas_seguidas_suspendem_a_fita(falsas, schema):
    """Fita fora da tomada para de custar o tempo de espera a cada troca."""
    schema.set_boolean("session-fita", True)
    modulos = falsas(True)
    fita = session_fita.fitas()[0]

    for _ in range(session_fita.FALHAS_PARA_SUSPENDER):
        assert session_fita.aplicar(fita, False, "") is False
    assert fita.id in session_fita._suspensas

    modulos["eb0"].quebrada = False
    assert session_fita.aplicar(fita, False, "") is False
    assert modulos["eb0"].recebidos == []


def test_retomar_devolve_a_fita_suspensa(falsas, schema):
    schema.set_boolean("session-fita", True)
    modulos = falsas(True)
    fita = session_fita.fitas()[0]
    for _ in range(session_fita.FALHAS_PARA_SUSPENDER):
        session_fita.aplicar(fita, False, "")

    modulos["eb0"].quebrada = False
    session_fita.retomar()

    assert session_fita.aplicar(fita, False, "") is True


def test_uma_falha_solta_nao_suspende(falsas, schema):
    """Um engasgo da rede no meio de respostas boas não conta como fita morta."""
    schema.set_boolean("session-fita", True)
    modulos = falsas(False)
    fita = session_fita.fitas()[0]

    for _ in range(session_fita.FALHAS_PARA_SUSPENDER):
        modulos["eb0"].quebrada = True
        session_fita.aplicar(fita, False, "")
        modulos["eb0"].quebrada = False
        session_fita.aplicar(fita, False, "")

    assert fita.id not in session_fita._suspensas


def test_fechar_conexoes_fecha_todas(falsas, schema):
    schema.set_boolean("session-fita", True)
    modulos = falsas(False, False)
    session_fita._vestir(session_fita.cor_do_app())

    session_fita.fechar_conexoes()

    assert all(getattr(modulo, "fechada", False) for modulo in modulos.values())
    assert session_fita._conexoes == {}


class FitaComFila(FitaFalsa):
    """Uma fita cuja consulta e batimento respondem como os de verdade numa
    conexão que fica aberta: a tinytuya não confere se a resposta é do pedido
    que ela fez, lê a mais antiga e, se vier vazia, lê mais uma."""

    def __init__(self):
        super().__init__()
        self.sinais_de_vida = 0

    def _responder(self, *mensagens):
        # O que já estava a caminho chega antes da resposta deste pedido.
        self.socket.chegar()
        self.socket.fila += mensagens
        mensagem = self.socket.fila.pop(0)
        if mensagem.payload is None and self.socket.fila:
            mensagem = self.socket.fila.pop(0)
        return mensagem.payload

    def heartbeat(self, nowait=True):
        self.sinais_de_vida += 1
        self.socket.fila.append(Msg(BATIMENTO))

    def status(self, nowait=False):
        self.sinais_de_vida += 1
        if nowait:
            return super().status(nowait=True)
        return self._responder(Msg(CONSULTA, {"dps": dict(self.dps)}))

    def close(self):
        # Fechar com resposta por ler faz o Windows mandar RST, e a fita joga
        # fora o último comando — medido: até 4 em 6 perdidos.
        self.por_ler_ao_fechar = self.socket.fila + self.socket.a_caminho
        super().close()


@pytest.fixture
def com_fila(monkeypatch, schema):
    schema.set_boolean("session-fita", True)
    fita = session_fita.Fita("Centro", "eb0", "1.2.3.4", "k")
    session_fita.gravar_fitas([fita])
    modulo = FitaComFila()
    monkeypatch.setattr(session_fita, "_dispositivo", lambda _fita: modulo)
    return fita, modulo


def test_mensagem_que_ninguem_pediu_nao_vira_resposta(com_fila):
    """Foi o "Testar" dizendo que as três fitas estavam fora do ar.

    Uma mensagem antiga no soquete (a resposta de um batimento, ou a fita
    avisando de uma troca feita pelo Smart Life) virava a resposta do comando
    seguinte: a tinytuya lia ela e o "recebi" vazio, e devolvia nada.
    """
    fita, modulo = com_fila
    session_fita.aplicar(fita, True, "015403e80096")
    modulo.socket.fila.append(Msg(BATIMENTO))

    assert session_fita.aplicar(fita, True, "011b026101f4") is True


def test_batimento_nao_deixa_resposta_por_ler(com_fila, monkeypatch):
    fita, modulo = com_fila
    monkeypatch.setattr(session_fita, "BATIMENTO", 0.01)
    session_fita.aplicar(fita, True, "015403e80096")

    time.sleep(0.1)
    assert modulo.sinais_de_vida > 1
    assert fita.id in session_fita._conexoes
    session_fita.fechar_conexoes()

    assert modulo.por_ler_ao_fechar == []


def test_fechamento_nao_deixa_resposta_por_ler(com_fila, schema):
    """Resposta por ler no fechamento perdia a devolução de uma ou duas fitas."""
    fita, modulo = com_fila
    schema.set_string(
        session_fita.CHAVE_ESTADO,
        json.dumps({fita.id: {"ligada": True, "cor": "011b026101f4"}}),
    )
    session_fita.aplicar(fita, True, "015403e80096")
    modulo.socket.fila.append(Msg(BATIMENTO))

    session_fita.fechar()

    assert cor_mandada(modulo) == "011b026101f4"
    assert modulo.por_ler_ao_fechar == []


def _cores_mandadas(modulo):
    return [comando["24"] for comando in modulo.recebidos if "24" in comando]


@pytest.fixture
def com_fade(monkeypatch):
    """Um fade curto: 10 degraus em 0,2 s."""
    monkeypatch.setattr(session_fita, "DURACAO_FADE", 0.2)
    monkeypatch.setattr(session_fita, "RITMO_FADE", 50)


def test_degraus_vao_pelo_caminho_mais_curto():
    """De 350° a 10° passa pelo vermelho (0°), e não dá a volta pelo verde."""
    degraus = session_fita._degraus(
        session_fita.Cor(350, 1000, 100), session_fita.Cor(10, 1000, 300), 4
    )
    cores = [session_fita.cor_de_hex(degrau) for degrau in degraus]
    assert [cor.matiz for cor in cores] == [355, 0, 5, 10]
    assert [cor.brilho for cor in cores] == [150, 200, 250, 300]


def test_troca_de_cor_passa_pelas_cores_do_meio(com_fila, com_fade):
    fita, modulo = com_fila
    session_fita.aplicar(fita, True, "000003e80064")

    session_fita._vestir(session_fita.Cor(120, 1000, 100))

    cores = _cores_mandadas(modulo)
    assert "003c03e80064" in cores  # 60°, o meio do caminho do vermelho ao verde
    assert cores[-1] == "007803e80064"


def test_estado_lido_serve_de_partida_para_o_fade(com_fila, com_fade):
    """É o caso da abertura do app: lê a cor de antes e desliza dela."""
    fita, modulo = com_fila
    modulo.dps.update({"20": True, "24": "000003e80064"})
    session_fita.ler_estado(fita)

    session_fita._vestir(session_fita.Cor(120, 1000, 100))

    assert "003c03e80064" in _cores_mandadas(modulo)


def test_sem_saber_de_onde_a_fita_parte_nao_ha_fade(com_fila, com_fade):
    """Sem ter lido nem mandado nada, o fade partiria de uma cor inventada."""
    fita, modulo = com_fila

    session_fita._vestir(session_fita.Cor(120, 1000, 100))

    assert modulo.recebidos == [{"21": "colour", "24": "007803e80064"}, {"20": True}]


def test_fita_apagada_acende_direto_sem_fade(com_fila, com_fade):
    """Acender do escuro com fade deixava fita apagada no teste com as fitas
    de verdade; o usuário preferiu acender direto, a cor antes do liga."""
    fita, modulo = com_fila
    session_fita.aplicar(fita, False, "000003e80064")
    modulo.recebidos.clear()

    session_fita._vestir(session_fita.Cor(120, 1000, 500))

    assert modulo.recebidos == [{"21": "colour", "24": "007803e801f4"}, {"20": True}]


def test_apagar_desce_o_brilho_antes_de_desligar(com_fila, com_fade):
    """O fechamento que devolve a fita apagada: ela escurece, e só então desliga."""
    fita, modulo = com_fila
    session_fita.aplicar(fita, True, "000003e801f4")
    modulo.recebidos.clear()

    session_fita._repor(fita, {"ligada": False, "cor": "011b026101f4"})

    *degraus, final = modulo.recebidos
    # Só o desliga: a cor de antes junto fazia a fita piscar nela ao apagar.
    assert final == {"20": False}
    brilhos = [session_fita.cor_de_hex(degrau["24"]).brilho for degrau in degraus]
    assert brilhos == sorted(brilhos, reverse=True)
    assert brilhos[-1] == session_fita.BRILHO_MINIMO


def test_troca_nova_interrompe_o_fade_em_curso(com_fila, monkeypatch):
    """Play no meio do fade da abertura: a cor nova parte de onde a fita está."""
    monkeypatch.setattr(session_fita, "DURACAO_FADE", 1)
    monkeypatch.setattr(session_fita, "RITMO_FADE", 50)
    fita, modulo = com_fila
    session_fita.aplicar(fita, True, "000003e80064")

    primeira = threading.Thread(
        target=session_fita._vestir, args=(session_fita.Cor(120, 1000, 100),)
    )
    primeira.start()
    time.sleep(0.2)
    session_fita._vestir(session_fita.Cor(240, 1000, 100))
    primeira.join()

    assert _cores_mandadas(modulo)[-1] == "00f003e80064"
    # A primeira nunca chegou ao fim: nem o último degrau, nem o comando final.
    assert "007803e80064" not in _cores_mandadas(modulo)


def test_fade_so_termina_quando_a_fita_para_de_responder(com_fila):
    """Os degraus vão sem esperar resposta, e as respostas chegam depois.

    Se o comando final saísse com elas ainda a caminho, leria uma delas como a
    sua, e a dele sobraria no soquete: é o bug do fechamento que perdia a
    devolução.
    """
    fita, modulo = com_fila
    session_fita.aplicar(fita, True, "000003e80064")
    session_fita._geracoes[fita.id] = 1

    session_fita._rajada(fita, ["003c03e80064", "007803e80064"], 1)

    assert modulo.socket.fila == []
    assert modulo.socket.a_caminho == []


def test_fade_sem_aviso_do_fim_segue_na_mesma_conexao(com_fila):
    """A fita às vezes joga fora o fim da rajada. Quem garante a cor final é o
    comando final, que é reenviado; trocar de conexão ali só punha uma
    reconexão no pior momento."""
    fita, modulo = com_fila
    session_fita.aplicar(fita, True, "000003e80064")
    session_fita._geracoes[fita.id] = 1
    modulo.sem_aviso = True

    session_fita._rajada(fita, ["003c03e80064"], 1)

    assert not getattr(modulo, "fechada", False)
    assert fita.id in session_fita._conexoes


def test_comando_perdido_e_reenviado_na_mesma_conexao(com_fila):
    """Medido: de vez em quando a fita joga fora um comando, sem aviso. O
    mesmo comando reenviado pega."""
    fita, modulo = com_fila
    session_fita.aplicar(fita, True, "000003e80064")
    modulo.recebidos.clear()
    modulo.perder = 1

    assert session_fita.aplicar(fita, False, "") is True
    assert modulo.recebidos == [{"20": False}]
    assert not getattr(modulo, "fechada", False)


def test_aviso_repetido_de_outro_comando_nao_confirma_este(com_fila):
    """Visto logo depois de um fade: a fita repetiu o aviso do último degrau
    depois do comando seguinte. Lido como resposta, o aviso de verdade sobrava
    no soquete — e fechar com ele por ler faz a fita jogar fora o comando."""
    fita, modulo = com_fila
    session_fita.aplicar(fita, True, "000003e80064")
    modulo.socket.a_caminho.append(Msg(AVISO, {"dps": {"24": "000003e80064"}}))

    assert session_fita.aplicar(fita, False, "") is True
    assert modulo.socket.fila == []
    assert modulo.socket.a_caminho == []


def test_ler_estado_nao_confunde_aviso_com_estado(com_fila):
    """No arranque com órfãos, a leitura vem logo depois da devolução, com a
    segunda cópia do último aviso ainda a caminho. Lida como estado, a fita
    acesa viraria "apagada" — e o fechamento a desligaria."""
    fita, modulo = com_fila
    modulo.dps.update({"20": True, "24": "000003e80064"})
    session_fita.aplicar(fita, True, "000003e80064")
    modulo.socket.a_caminho.append(Msg(AVISO, {"dps": {"24": "000003e80064"}}))

    assert session_fita.ler_estado(fita) == {"ligada": True, "cor": "000003e80064"}


def test_degraus_repetidos_viram_um_so():
    """Fade de 50% a 50,2%: sem isso, o último degrau apareceria três vezes, e
    o aviso do primeiro deles pareceria o do fim."""
    degraus = session_fita._degraus(
        session_fita.Cor(0, 1000, 500), session_fita.Cor(0, 1000, 502), 10
    )
    assert degraus == ["000003e801f5", "000003e801f6"]


def test_previa_nao_faz_fade(com_fila, com_fade):
    """O controle de brilho tem de acompanhar o dedo, e não correr atrás dele."""
    fita, modulo = com_fila
    session_fita.aplicar(fita, True, "000003e80064")
    modulo.recebidos.clear()

    session_fita._pintar(session_fita.Cor(120, 1000, 100))

    assert modulo.recebidos == [{"21": "colour", "24": "007803e80064"}]


def test_duas_varreduras_ao_mesmo_tempo_viram_uma(monkeypatch):
    """Duas varreduras juntas brigam pelo mesmo soquete de broadcast.

    No Windows isso volta como "apenas uma utilização de cada endereço de
    soquete" — foi o erro visto no primeiro teste com as fitas de verdade.
    """
    dentro = []
    pico = []

    def varredura_lenta(*_args, **_kwargs):
        dentro.append(1)
        pico.append(len(dentro))
        time.sleep(0.1)
        dentro.pop()
        return {}

    falso = ModuleType("tinytuya")
    falso.deviceScan = varredura_lenta
    monkeypatch.setitem(sys.modules, "tinytuya", falso)

    linhas = [threading.Thread(target=session_fita.enderecos_na_rede) for _ in range(3)]
    for linha in linhas:
        linha.start()
    for linha in linhas:
        linha.join()

    assert max(pico) == 1


def test_varredura_que_falha_devolve_mapa_vazio(monkeypatch):
    def explodir(*_args, **_kwargs):
        raise OSError("rede fora")

    falso = ModuleType("tinytuya")
    falso.deviceScan = explodir
    monkeypatch.setitem(sys.modules, "tinytuya", falso)

    assert session_fita.enderecos_na_rede() == {}


def test_fita_sem_endereco_nao_chega_a_abrir_conexao(monkeypatch, schema):
    """Sem IP, a tinytuya varreria a rede sozinha ao abrir a conexão.

    Com as fitas em paralelo, seriam varreduras simultâneas na mesma porta.
    """
    abertas = []
    monkeypatch.setattr(session_fita, "_dispositivo", lambda fita: abertas.append(fita))
    fita = session_fita.Fita("Centro", "eb0", "", "k")

    assert session_fita.aplicar(fita, True, "015403e80096") is False
    assert abertas == []
    # Não é fita fora do ar: só ainda não foi achada. Não conta falha.
    assert fita.id not in session_fita._falhas


def test_escolher_no_seletor_ja_acende_a_fita_sem_aplicar(tela, monkeypatch):
    """Cada tentativa de cor aparece na parede na hora, ainda dentro do seletor.

    Antes era preciso abrir o seletor, escolher, confirmar e só então ver — o
    diálogo de cor do GTK só devolve a cor no "Selecionar".
    """
    dialog, jogo = tela
    pedidas = []
    monkeypatch.setattr(session_fita, "previa", pedidas.append)

    dialog.fita_color_button.set_property(
        "rgba", session_fita.cor_para_rgba(session_fita.Cor(200, 1000, 0))
    )

    assert pedidas
    assert abs(pedidas[-1].matiz - 200) <= 2
    # Prévia não é escolha: nada foi gravado sem o Aplicar.
    assert not session_fita.escolhida(jogo.game_id)


def test_a_cor_do_app_vem_de_fabrica_no_roxo(schema):
    assert session_fita.tom_do_app() == session_fita.ROXO_DO_APP


def test_a_cor_escolhida_vira_a_cor_oficial_do_app(falsas, schema):
    """Vermelho escolhido nas Preferências é o que acende com o app aberto."""
    schema.set_boolean("session-fita", True)
    modulos = falsas(False)
    session_fita.salvar_tom_do_app(0, 1000)

    session_fita._guardar_e_vestir()

    cor = session_fita.cor_de_hex(cor_mandada(modulos["eb0"]))
    assert (cor.matiz, cor.saturacao) == (0, 1000)


def test_voltar_ao_roxo_desfaz_a_escolha(schema):
    session_fita.salvar_tom_do_app(210, 800)
    session_fita.redefinir_tom_do_app()
    assert session_fita.tom_do_app() == session_fita.ROXO_DO_APP


def test_jogo_sem_capa_usa_a_cor_escolhida_para_o_app(schema):
    session_fita.salvar_tom_do_app(210, 800)
    jogo = SimpleNamespace(game_id="sem-capa", name="X", get_cover_path=lambda: None)

    cor = session_fita.cor_do_jogo(jogo)

    assert (cor.matiz, cor.saturacao) == (210, 800)


def test_escolher_a_cor_do_app_nas_preferencias_grava_e_mostra(monkeypatch, schema):
    """Sem botão de aplicar: as Preferências gravam na hora, e a fita acompanha."""
    import cartridges.preferences as preferences_module  # noqa: PLC0415
    from cartridges.metadata_refresh import MetadataRefresh  # noqa: PLC0415

    monkeypatch.setattr(preferences_module, "get_metadata_refresh", MetadataRefresh)
    pedidas = []
    monkeypatch.setattr(session_fita, "previa", pedidas.append)
    preferencias = preferences_module.CartridgesPreferences()

    # Abrir a tela não conta como escolha.
    assert session_fita.tom_do_app() == session_fita.ROXO_DO_APP
    assert not preferencias.fita_cor_app_reset.get_visible()
    assert pedidas == []

    preferencias.fita_cor_app_seletor.set_property(
        "rgba", session_fita.cor_para_rgba(session_fita.Cor(210, 1000, 0))
    )

    matiz, saturacao = session_fita.tom_do_app()
    assert abs(matiz - 210) <= 2
    assert abs(saturacao - 1000) <= 10
    assert preferencias.fita_cor_app_reset.get_visible()
    assert pedidas

    preferencias.voltar_ao_roxo()

    assert session_fita.tom_do_app() == session_fita.ROXO_DO_APP
    assert not preferencias.fita_cor_app_reset.get_visible()
