"""Lógica pura do passeio (tools/passeio_relatorio.py): sem janela, sem rede."""

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
