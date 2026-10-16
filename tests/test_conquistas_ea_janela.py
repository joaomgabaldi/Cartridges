"""A janela de login da EA: colar o pedido copiado do navegador e conectar."""

import pytest

from cartridges.conquistas.ea import conta, janela

_CURL = "curl 'https://accounts.ea.com/connect/auth' -H 'cookie: remid=AAA; _nx_mpcid=BBB'"


def _sincrono(trabalho, entregar):
    entregar(trabalho())


@pytest.fixture
def abertas():
    return []


def _janela(abertas, ao_conectar=lambda: None):
    j = janela.JanelaDeLogin(ao_conectar, abrir=abertas.append, em_thread=_sincrono)
    j.close = lambda: abertas.append("fechou")
    return j


def _colar(j, texto):
    j.texto.get_buffer().set_text(texto)


def test_abre_a_pagina_de_login_ao_abrir(abertas):
    j = _janela(abertas)
    j.present = lambda _pai: None
    j.mostrar(None)
    assert abertas == [conta.PAGINA_DE_LOGIN]


def test_botao_da_pagina_abre_o_token(abertas):
    j = _janela(abertas)
    j.botao_pagina.emit("clicked")
    assert abertas == [conta.TOKEN]


_SEM_NAVEGADOR = "Não foi possível abrir o navegador. Acesse ea.com/login manualmente."


def _sem_navegador(_url):
    raise OSError("sem navegador")


def test_navegador_que_nao_abre_ao_abrir_a_janela_avisa():
    j = janela.JanelaDeLogin(lambda: None, abrir=_sem_navegador, em_thread=_sincrono)
    j.present = lambda _pai: None
    j.mostrar(None)
    assert j.erro.get_visible() and j.erro.get_label() == _SEM_NAVEGADOR


def test_navegador_que_nao_abre_pelo_botao_avisa():
    j = janela.JanelaDeLogin(lambda: None, abrir=_sem_navegador, em_thread=_sincrono)
    j.botao_pagina.emit("clicked")
    assert j.erro.get_visible() and j.erro.get_label() == _SEM_NAVEGADOR


def _abre_so_na_segunda():
    chamadas = []

    def abrir(_url):
        chamadas.append(_url)
        if len(chamadas) == 1:
            raise OSError("sem navegador")

    return abrir


def test_aviso_do_navegador_some_quando_a_pagina_abre_depois():
    j = janela.JanelaDeLogin(lambda: None, abrir=_abre_so_na_segunda(), em_thread=_sincrono)
    j.present = lambda _pai: None
    j.mostrar(None)
    assert j.erro.get_visible() and j.erro.get_label() == _SEM_NAVEGADOR
    j.botao_pagina.emit("clicked")
    assert not j.erro.get_visible()


def test_erro_de_login_permanece_quando_a_pagina_abre(abertas, monkeypatch):
    def recusa(_texto):
        raise conta.LoginRecusado()

    monkeypatch.setattr(conta, "conectar", recusa)
    j = _janela(abertas)
    _colar(j, _CURL)
    j.botao_conectar.emit("clicked")
    j.botao_pagina.emit("clicked")
    assert j.erro.get_visible()


def test_conectar_insensivel_sem_os_dois_cookies(abertas):
    j = _janela(abertas)
    assert not j.botao_conectar.get_sensitive()
    _colar(j, "curl -H 'cookie: remid=AAA'")
    assert not j.botao_conectar.get_sensitive()
    _colar(j, _CURL)
    assert j.botao_conectar.get_sensitive()


def test_sucesso_fecha_e_chama_ao_conectar(abertas, monkeypatch):
    recebidos = []
    monkeypatch.setattr(conta, "conectar", recebidos.append)
    conectados = []
    j = _janela(abertas, lambda: conectados.append(1))
    _colar(j, _CURL)
    j.botao_conectar.emit("clicked")
    assert recebidos == [_CURL] and conectados == [1] and "fechou" in abertas


def test_login_recusado_mantem_aberta(abertas, monkeypatch):
    def recusa(_texto):
        raise conta.LoginRecusado()

    monkeypatch.setattr(conta, "conectar", recusa)
    j = _janela(abertas)
    _colar(j, _CURL)
    j.botao_conectar.emit("clicked")
    assert "fechou" not in abertas and j.erro.get_visible()
    assert j.erro.get_label() == "A EA não reconheceu o login. Entre novamente em ea.com e copie o pedido outra vez."
    buffer = j.texto.get_buffer()
    assert buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False) == ""


def test_outra_falha_mantem_aberta(abertas, monkeypatch):
    def quebra(_texto):
        raise OSError("rede")

    monkeypatch.setattr(conta, "conectar", quebra)
    j = _janela(abertas)
    _colar(j, _CURL)
    j.botao_conectar.emit("clicked")
    assert "fechou" not in abertas
    assert j.erro.get_label() == "Não foi possível entrar na conta EA. Verifique a conexão e tente novamente."
    assert j.botao_conectar.get_sensitive()


def test_resultado_depois_de_fechada_e_descartado(abertas, monkeypatch):
    def quebra(_texto):
        raise OSError("rede")

    monkeypatch.setattr(conta, "conectar", quebra)
    pendente = []
    j = janela.JanelaDeLogin(lambda: None, abrir=abertas.append, em_thread=lambda t, e: pendente.append((t, e)))
    _colar(j, _CURL)
    j.botao_conectar.emit("clicked")
    j.emit("closed")
    trabalho, entregar = pendente[0]
    entregar(trabalho())
    assert not j.erro.get_visible()


def test_texto_colado_nao_vai_ao_log(abertas, monkeypatch, caplog):
    caplog.set_level("DEBUG")

    def quebra(_texto):
        raise ValueError("x")

    monkeypatch.setattr(conta, "conectar", quebra)
    j = _janela(abertas)
    _colar(j, _CURL)
    j.botao_conectar.emit("clicked")
    assert "AAA" not in caplog.text and "BBB" not in caplog.text


def _textos(widget):
    achados = []
    filho = widget.get_first_child() if hasattr(widget, "get_first_child") else None
    if hasattr(widget, "get_label") and isinstance(widget.get_label(), str):
        achados.append(widget.get_label())
    while filho is not None:
        achados.extend(_textos(filho))
        filho = filho.get_next_sibling()
    return achados


def test_textos(abertas):
    j = _janela(abertas)
    assert j.get_title() == "Entrar na conta EA"
    todos = "\n".join(_textos(j.get_child()))
    for esperado in (
        "1. Entre na sua conta EA na página que foi aberta no navegador.",
        "2. No navegador, pressione F12 e abra a aba Rede.",
        "3. Clique em Abrir a página da conta, abaixo.",
        '4. Na aba Rede, clique com o botão direito no pedido que começa com "auth?client_id" '
        "e escolha Copiar › Copiar como cURL.",
        "5. Cole o texto abaixo.",
        "Texto copiado do navegador",
        "Abrir a página da conta",
        "Cancelar",
        "Conectar",
    ):
        assert esperado in todos
