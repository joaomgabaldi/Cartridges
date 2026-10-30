# test_login_da_loja.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A janela de login das lojas (EA e Epic), sem tela: colar o texto copiado do navegador e conectar (D61).

Trazido de `test_conquistas_ea_janela.py` e `test_conquistas_epic_janela.py`, parametrizado pela descrição `LOJA`.
"""

import inspect
from types import SimpleNamespace

import pytest

from cartridges.conquistas import vigia_da_conta
from cartridges.conquistas.ea import conta as ea_conta
from cartridges.conquistas.ea import janela as ea_janela
from cartridges.conquistas.epic import conta as epic_conta
from cartridges.conquistas.epic import janela as epic_janela
from cartridges.modelos.contas import Loja, LoginDaLoja

_CURL = "curl 'https://accounts.ea.com/connect/auth' -H 'cookie: remid=AAA; _nx_mpcid=BBB'"
_COD = "0123456789abcdef0123456789abcdef"

_CASOS = {
    "ea": SimpleNamespace(
        loja=ea_janela.LOJA,
        conta=ea_conta,
        valido=_CURL,
        invalido="curl -H 'cookie: remid=AAA'",
        segredos=("AAA", "BBB"),
        titulo="Entrar na conta EA",
        rotulo="Texto copiado do navegador",
        botao="Abrir a página da conta",
        url_do_botao=ea_conta.TOKEN,
        sem_navegador="Não foi possível abrir o navegador. Acesse ea.com/login manualmente.",
        recusado="A EA não reconheceu o login. Entre novamente em ea.com e copie o pedido outra vez.",
        falhou="Não foi possível entrar na conta EA. Verifique a conexão e tente novamente.",
        recusa=ea_conta.LoginRecusado,
        multilinha=True,
        passos=(
            "1. Entre na sua conta EA na página que foi aberta no navegador.",
            "2. No navegador, pressione F12 e abra a aba Rede.",
            "3. Clique em Abrir a página da conta, abaixo.",
            '4. Na aba Rede, clique com o botão direito no pedido que começa com "auth?client_id" '
            "e escolha Copiar › Copiar como cURL.",
            "5. Cole o texto abaixo.",
        ),
    ),
    "epic": SimpleNamespace(
        loja=epic_janela.LOJA,
        conta=epic_conta,
        valido=_COD,
        invalido="lixo",
        segredos=(_COD,),
        titulo="Entrar na conta Epic",
        rotulo="Código de autorização",
        botao="Abrir a página novamente",
        url_do_botao=epic_conta.PAGINA_DE_LOGIN,
        sem_navegador="Não foi possível abrir o navegador. Copie o endereço abaixo e abra-o no navegador.",
        recusado="O código não foi aceito. Gere um novo código na página da Epic e tente novamente.",
        falhou="Não foi possível entrar na conta Epic.",
        recusa=epic_conta.CodigoRecusado,
        multilinha=False,
        passos=(
            "1. Entre na sua conta na página que foi aberta no navegador.",
            '2. Copie o código exibido em "authorizationCode".',
            "3. Cole o código abaixo.",
        ),
    ),
}


@pytest.fixture(params=list(_CASOS))
def caso(request):
    return _CASOS[request.param]


def _sincrono(trabalho, entregar):
    entregar(trabalho())


class _Janela:
    """O `LoginDaLoja` com o que ele fez ao redor: URLs abertas, fechamentos e conexões."""

    def __init__(self, caso, ao_conectar=None, em_thread=_sincrono, abrir=None):
        self.abertas: list[str] = []
        self.fechou: list[int] = []
        self.conectou: list[int] = []
        # Os lambdas capturam as listas, não o `self`: senão a árvore Qt fica presa num ciclo.
        conectou, fechou = self.conectou, self.fechou
        self.login = LoginDaLoja(
            caso.loja, ao_conectar or (lambda: conectou.append(1)), abrir=abrir or self.abertas.append, em_thread=em_thread
        )
        self.login.fechou.connect(lambda: fechou.append(1))


def _sem_navegador(_url):
    raise OSError("sem navegador")


def _abre_so_na_segunda():
    chamadas = []

    def abrir(url):
        chamadas.append(url)
        if len(chamadas) == 1:
            raise OSError("sem navegador")

    return abrir


def _fechada_com_troca_pendente(caso, ao_conectar):
    """Janela fechada (Cancelar, Esc ou tela fechada) com a troca ainda na rede."""
    pendente = []
    j = _Janela(caso, ao_conectar=ao_conectar, em_thread=lambda t, e: pendente.append((t, e)))
    j.login.abrir()
    j.login.texto = caso.valido
    j.login.conectar()
    j.login.fechar()
    return j, pendente[0]


def test_abre_a_pagina_de_login_ao_abrir(caso):
    j = _Janela(caso)
    assert j.login.aberto is False
    j.login.abrir()
    assert j.login.aberto is True
    assert j.abertas == [caso.conta.PAGINA_DE_LOGIN]


def test_botao_da_pagina_abre_a_url_do_botao(caso):
    j = _Janela(caso)
    j.login.abrirPagina()
    assert j.abertas == [caso.url_do_botao]


def test_navegador_que_nao_abre_ao_abrir_a_janela_avisa(caso):
    j = _Janela(caso, abrir=_sem_navegador)
    j.login.abrir()
    assert j.login.erro == caso.sem_navegador


def test_navegador_que_nao_abre_pelo_botao_avisa(caso):
    j = _Janela(caso, abrir=_sem_navegador)
    j.login.abrirPagina()
    assert j.login.erro == caso.sem_navegador


def test_aviso_do_navegador_some_quando_a_pagina_abre_depois(caso):
    j = _Janela(caso, abrir=_abre_so_na_segunda())
    j.login.abrir()
    assert j.login.erro == caso.sem_navegador
    j.login.abrirPagina()
    assert j.login.erro == ""


def test_erro_de_login_permanece_quando_a_pagina_abre(caso, monkeypatch):
    def recusa(_texto):
        raise caso.recusa()

    monkeypatch.setattr(caso.conta, "conectar", recusa)
    j = _Janela(caso)
    j.login.texto = caso.valido
    j.login.conectar()
    j.login.abrirPagina()
    assert j.login.erro == caso.recusado


def test_conectar_apagado_sem_texto_valido(caso):
    j = _Janela(caso)
    assert j.login.podeConectar is False
    j.login.texto = caso.invalido
    assert j.login.podeConectar is False
    j.login.texto = caso.valido
    assert j.login.podeConectar is True


def test_conectar_com_texto_invalido_nao_faz_nada(caso, monkeypatch):
    recebidos = []
    monkeypatch.setattr(caso.conta, "conectar", recebidos.append)
    j = _Janela(caso)
    j.login.texto = caso.invalido
    j.login.conectar()
    assert recebidos == [] and j.login.ocupada is False and j.login.erro == ""


def test_sucesso_fecha_e_chama_ao_conectar(caso, monkeypatch):
    recebidos = []
    monkeypatch.setattr(caso.conta, "conectar", recebidos.append)
    j = _Janela(caso)
    j.login.abrir()
    j.login.texto = caso.valido
    j.login.conectar()
    assert recebidos == [caso.valido]
    assert j.conectou == [1] and j.fechou == [1]
    assert j.login.aberto is False and j.login.ocupada is False


def test_login_recusado_mantem_aberta_e_limpa_o_texto(caso, monkeypatch):
    def recusa(_texto):
        raise caso.recusa()

    monkeypatch.setattr(caso.conta, "conectar", recusa)
    j = _Janela(caso)
    j.login.abrir()
    j.login.texto = caso.valido
    j.login.conectar()
    assert j.fechou == [] and j.login.aberto is True
    assert j.login.erro == caso.recusado
    assert j.login.texto == ""
    assert j.login.ocupada is False


def test_outra_falha_mantem_aberta_com_o_texto(caso, monkeypatch):
    def quebra(_texto):
        raise OSError("rede")

    monkeypatch.setattr(caso.conta, "conectar", quebra)
    j = _Janela(caso)
    j.login.abrir()
    j.login.texto = caso.valido
    j.login.conectar()
    assert j.fechou == [] and j.conectou == []
    assert j.login.erro == caso.falhou
    assert j.login.texto == caso.valido and j.login.podeConectar is True


def test_ocupada_enquanto_a_troca_esta_na_rede(caso, monkeypatch):
    monkeypatch.setattr(caso.conta, "conectar", lambda _t: None)
    pendente = []
    j = _Janela(caso, em_thread=lambda t, e: pendente.append((t, e)))
    j.login.abrir()
    j.login.texto = caso.valido
    j.login.conectar()
    assert j.login.ocupada is True and j.login.podeConectar is False
    j.login.conectar()  # ocupada: o segundo clique não pede outra troca
    assert len(pendente) == 1


def test_resultado_depois_de_fechada_e_descartado(caso, monkeypatch):
    def quebra(_texto):
        raise OSError("rede")

    monkeypatch.setattr(caso.conta, "conectar", quebra)
    j, (trabalho, entregar) = _fechada_com_troca_pendente(caso, None)
    entregar(trabalho())
    assert j.conectou == [] and j.login.erro == ""


def test_conta_conectada_depois_de_fechada_ainda_avisa(caso, monkeypatch):
    """A conta já conectou: a leitura dos jogos da loja tem de acontecer mesmo sem a janela."""
    monkeypatch.setattr(caso.conta, "conectar", lambda _t: None)
    j, (trabalho, entregar) = _fechada_com_troca_pendente(caso, None)
    entregar(trabalho())
    assert j.conectou == [1]


def test_aviso_de_conta_conectada_que_levanta_nao_escapa(caso, monkeypatch, caplog):
    monkeypatch.setattr(caso.conta, "conectar", lambda _t: None)

    def quebra():
        raise RuntimeError("falha no ouvinte")

    _j, (trabalho, entregar) = _fechada_com_troca_pendente(caso, quebra)
    entregar(trabalho())  # não levanta
    assert "Falha" in caplog.text


def test_texto_colado_nunca_vai_ao_log(caso, monkeypatch, caplog):
    caplog.set_level("DEBUG")

    def quebra(_texto):
        raise ValueError("x")

    monkeypatch.setattr(caso.conta, "conectar", quebra)
    j = _Janela(caso)
    j.login.texto = caso.valido
    j.login.conectar()
    for segredo in caso.segredos:
        assert segredo not in caplog.text


def test_o_padrao_e_o_em_thread_do_vigia_da_conta():
    """A janela usa o `_em_thread` compartilhado, o que não deixa a thread morrer calada."""
    padrao = inspect.signature(LoginDaLoja.__init__).parameters["em_thread"].default
    assert padrao is vigia_da_conta._em_thread


def test_resultado_none_vira_falha_generica(caso):
    j = _Janela(caso, em_thread=lambda _t, entregar: entregar(None))
    j.login.abrir()
    j.login.texto = caso.valido
    j.login.conectar()
    assert j.login.erro == caso.falhou
    assert j.login.podeConectar is True and j.fechou == []


def test_em_thread_que_levanta_vira_falha_generica(caso):
    def quebra(_t, _e):
        raise RuntimeError("sem thread")

    j = _Janela(caso, em_thread=quebra)
    j.login.abrir()
    j.login.texto = caso.valido
    j.login.conectar()
    assert j.login.erro == caso.falhou and j.login.ocupada is False


def test_sem_navegador_mostra_o_endereco_para_copiar_so_na_epic(caso):
    j = _Janela(caso, abrir=_sem_navegador)
    assert j.login.enderecoVisivel is False
    j.login.abrirPagina()
    if caso.loja.mostra_endereco:
        assert j.login.enderecoVisivel is True
        assert j.login.endereco == caso.conta.PAGINA_DE_LOGIN
    else:
        assert j.login.enderecoVisivel is False


def test_endereco_some_quando_a_pagina_abre_depois(caso):
    j = _Janela(caso, abrir=_abre_so_na_segunda())
    j.login.abrirPagina()
    j.login.abrirPagina()
    assert j.login.enderecoVisivel is False


def test_endereco_some_ao_conectar(caso, monkeypatch):
    monkeypatch.setattr(caso.conta, "conectar", lambda _t: None)
    pendente = []
    j = _Janela(caso, abrir=_sem_navegador, em_thread=lambda t, e: pendente.append((t, e)))
    j.login.abrirPagina()
    j.login.texto = caso.valido
    j.login.conectar()
    assert j.login.enderecoVisivel is False


def test_textos(caso):
    login = _Janela(caso).login
    assert login.titulo == caso.titulo
    assert tuple(login.passos) == caso.passos
    assert login.rotuloDoCampo == caso.rotulo
    assert login.botaoDaPagina == caso.botao
    assert login.multilinha is caso.multilinha


def test_a_descricao_e_uma_loja_congelada(caso):
    assert isinstance(caso.loja, Loja)
    with pytest.raises(AttributeError):
        caso.loja.titulo = "outro"  # type: ignore[misc]


def test_fechar_duas_vezes_avisa_uma_vez(caso):
    j = _Janela(caso)
    j.login.abrir()
    j.login.fechar()
    j.login.fechar()
    assert j.fechou == [1]


def test_abrir_nunca_abre_o_navegador_de_verdade(caso, sem_navegador_de_verdade):
    """O padrão de `abrir` é o `_abrir_navegador` do módulo; o `conftest.py` o troca por um que levanta."""
    login = LoginDaLoja(caso.loja, lambda: None, em_thread=_sincrono)
    login.abrir()
    assert sem_navegador_de_verdade == [caso.conta.PAGINA_DE_LOGIN]
    assert login.erro == caso.sem_navegador  # a exceção do guarda foi engolida como "sem navegador"
    sem_navegador_de_verdade.clear()  # provado de propósito: o guarda do fim do teste não reclama
