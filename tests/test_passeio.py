"""Lógica pura do passeio (tools/passeio_relatorio.py): sem janela, sem rede."""

import faulthandler
import json
import logging
import types

from tools.passeio_app import Coletor, Motor
from tools.passeio_relatorio import (
    agrupar,
    classificar,
    codigo_de_saida,
    e_de_rede,
    montar_relatorio,
)


def registro(mensagem, nivel=30, logger="root", rastro=None):
    return {"nivel": nivel, "logger": logger, "mensagem": mensagem, "rastro": rastro}


def passo(nome="Abrir os detalhes", estado="ok", registros=(), jogo="Hades", **extra):
    base = {
        "passo": nome,
        "jogo_id": "shortcuts_1" if jogo else None,
        "jogo_nome": jogo,
        "estado": estado,
        "motivo": None,
        "rastro": None,
        "duracao": 0.5,
        "registros": list(registros),
    }
    base.update(extra)
    return base


def test_aviso_de_rede_nao_conta_como_falha():
    rede = registro("HowLongToBeat lookup failed: timed out", nivel=40)
    assert e_de_rede(rede)
    assert classificar(passo(registros=[rede])) == "ok"


def test_logger_de_http_e_de_rede():
    assert e_de_rede(registro("Retrying", logger="urllib3.connectionpool"))


def test_erro_nao_tratado_e_critico_do_gtk_nunca_sao_de_rede():
    assert not e_de_rede(registro("Erro não tratado", nivel=50, rastro="Steam..."))
    critico = registro("Gtk-CRITICAL **: gtk_box_remove: assertion failed", nivel=40)
    assert not e_de_rede(critico)
    assert classificar(passo(registros=[critico])) == "falha"


def test_estado_do_passo_prevalece():
    assert classificar(passo(estado="travou")) == "travou"
    assert classificar(passo(estado="falha")) == "falha"
    assert classificar(passo(estado="pulado")) == "pulado"
    assert classificar(passo(registros=[registro("aviso qualquer")])) == "ok"


def test_agrupa_repetidos_com_contagem_e_primeiro_passo():
    a = registro("Capa ausente")
    passos = [
        passo("Abrir os detalhes", registros=[a]),
        passo("Abrir a edição e cancelar", registros=[a, a]),
    ]
    assert agrupar(passos, de_rede=False) == [("Capa ausente", 3, "Abrir os detalhes · Hades")]


def test_relatorio_resume_e_detalha_a_falha():
    critico = registro("Gtk-CRITICAL **: algo", nivel=40, rastro="Traceback X")
    texto = montar_relatorio(
        [passo(), passo("Abrir a edição e salvar", estado="falha", motivo="Tempo esgotado: salvar",
                        rastro="Traceback Y", registros=[critico])],
        duracao=75.0,
        despejo="",
    )
    assert "Passos executados: 2" in texto
    assert "Falhas: 1" in texto
    assert "Duração: 1 min 15 s" in texto
    assert "Abrir a edição e salvar · Hades" in texto
    assert "Tempo esgotado: salvar" in texto
    assert "Traceback Y" in texto and "Traceback X" in texto


def test_relatorio_traz_o_despejo_do_travamento():
    texto = montar_relatorio([passo(estado="travou")], duracao=1.0, despejo="Thread 0x1 ...")
    assert "Travamentos: 1" in texto
    assert "Thread 0x1 ..." in texto


def test_codigo_de_saida():
    assert codigo_de_saida([passo(), passo(estado="pulado")]) == 0
    assert codigo_de_saida([passo(), passo(estado="falha")]) == 1
    assert codigo_de_saida([passo(estado="travou")]) == 1


def test_erro_em_passo_pulado_vira_falha():
    critico = registro("Gtk-CRITICAL **: algo", nivel=40)
    pulado = passo(estado="pulado", motivo="Jogo sem capa", registros=[critico])
    assert classificar(pulado) == "falha"
    assert codigo_de_saida([pulado]) == 1


def test_rastro_decide_se_e_de_rede_mesmo_citando_a_steam():
    bug = registro(
        "Metadata refresh: could not prefetch Steam tags",
        nivel=40,
        rastro="Traceback (most recent call last):\n  File x\nKeyError: 'x'",
    )
    assert not e_de_rede(bug)
    rede = registro(
        "Metadata refresh: could not prefetch Steam tags",
        nivel=40,
        rastro="Traceback (most recent call last):\n  File x\nrequests.exceptions.ConnectionError: boom",
    )
    assert e_de_rede(rede)


def test_erro_nao_tratado_nunca_e_de_rede_mesmo_com_excecao_de_rede_no_rastro():
    escapou = registro(
        "Erro não tratado",
        nivel=50,
        rastro="Traceback (most recent call last):\n  File x\nrequests.exceptions.ConnectionError: boom",
    )
    assert not e_de_rede(escapou)
    assert classificar(passo(registros=[escapou])) == "falha"


def test_coletor_ignora_info_e_captura_aviso_e_excecao():
    logger = logging.getLogger("teste_passeio_coletor")
    logger.setLevel(logging.DEBUG)
    coletor = Coletor()
    logger.addHandler(coletor)
    try:
        logger.info("isso não deveria ser coletado")
        assert coletor.registros == []

        logger.warning("cuidado")
        assert len(coletor.registros) == 1
        registrado = coletor.registros[0]
        assert set(registrado) == {"nivel", "logger", "mensagem", "rastro"}
        assert registrado["nivel"] == logging.WARNING
        assert registrado["logger"] == "teste_passeio_coletor"
        assert registrado["mensagem"] == "cuidado"
        assert registrado["rastro"] is None

        try:
            raise ValueError("boom")
        except ValueError:
            logger.exception("falhou")
        assert len(coletor.registros) == 2
        rastro = coletor.registros[1]["rastro"]
        assert rastro is not None and "ValueError" in rastro
    finally:
        logger.removeHandler(coletor)


def test_registros_de_antes_do_primeiro_passo_sao_atribuidos_a_ele(tmp_path):
    """Spec: atribuição de registros a passo e jogo.

    O coletor real é pendurado no logger raiz antes de qualquer passo rodar
    (em `main`, junto com `setup_logging`) — não em `Motor.iniciar`. Um aviso
    de antes do primeiro passo (como "Skipping malformed game record", do
    `load_games_from_disk` real) tem de aparecer nos registros desse
    primeiro passo, e não ser descartado.
    """
    app_falso = types.SimpleNamespace(quit=lambda: None)
    motor = Motor(app_falso, tmp_path)
    logger = logging.getLogger()
    logger.addHandler(motor.coletor)
    try:
        logger.warning("aviso de antes do passo (como o startup faria)")

        jogo = types.SimpleNamespace(game_id="jogo_1", name="Jogo Um")

        def fabrica():
            logger.warning("aviso dentro do passo")
            return
            yield  # torna esta função um gerador, nunca alcançado

        motor._comecar(("Passo X", jogo, fabrica))  # pylint: disable=protected-access

        linhas = (tmp_path / "passos.jsonl").read_text(encoding="utf-8").splitlines()
        assert len(linhas) == 1
        linha = json.loads(linhas[0])
        assert linha["passo"] == "Passo X"
        assert linha["jogo_id"] == "jogo_1"
        assert linha["jogo_nome"] == "Jogo Um"
        assert linha["estado"] == "ok"
        mensagens = {r["mensagem"] for r in linha["registros"]}
        assert "aviso de antes do passo (como o startup faria)" in mensagens
        assert "aviso dentro do passo" in mensagens
    finally:
        logger.removeHandler(motor.coletor)
        faulthandler.cancel_dump_traceback_later()
        motor.jsonl.close()
        motor.despejo.close()
