# test_grupo_das_contas_qt.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""O grupo das contas (Microsoft, Epic e EA) sem tela: `ContasDasLojas` (D61).

Trazido de `test_conquistas_preferencias.py` (as contas), com o aviso na `FilaDeAvisos` no lugar do toast do hospedeiro.
O `login.entrar` do Xbox, o `conectar` e o `abrir` do navegador são sempre falsos.
"""

import pytest

from cartridges import shared
from cartridges.conquistas import catalogo, fontes, historico
from cartridges.conquistas.catalogo import Catalogo, ConquistaInfo
from cartridges.conquistas.ea import conta as ea_conta
from cartridges.conquistas.epic import conta as epic_conta
from cartridges.conquistas.formatos import Desbloqueio
from cartridges.conquistas.xbox import conta, login
from cartridges.jogo import Jogo
from cartridges.modelos import contas as modulo
from cartridges.modelos.contas import ContasDasLojas
from cartridges.modelos.conquistas import ConquistasDoJogo
from tests.apoio_conquistas import com_fonte
from tests.apoio_conquistas_qt import _Detalhes

_COD = "0123456789abcdef0123456789abcdef"
_CURL = "curl 'https://accounts.ea.com/connect/auth' -H 'cookie: remid=AAA; _nx_mpcid=BBB'"


def _sincrono(trabalho, entregar):
    entregar(trabalho())


def _contas(avisos, **kw):
    kw.setdefault("em_thread", _sincrono)
    kw.setdefault("abrir", lambda _url: None)
    return ContasDasLojas(avisos, **kw)


def _varredura_falsa(avisos, varridos, pedidos=None):
    class Varredura:
        def varrer_jogos(self, games, filtro=None):
            # O filtro é de quem varre (na thread dela): a falsa aplica aqui o que a varredura de verdade
            # aplicaria lá, a menos que o teste só queira ver o pedido.
            if pedidos is not None:
                pedidos.append((list(games), filtro))
                return
            varridos.extend(game for game in games if filtro is None or filtro(game))

    shared.aplicativo.varredura_conquistas = Varredura()


# A conta Microsoft


def test_conta_desconectada(monkeypatch, avisos):
    monkeypatch.setattr(conta, "conectada", lambda: False)
    grupo = _contas(avisos)
    assert grupo.microsoft == {"titulo": "Conta Microsoft", "subtitulo": "Não conectada", "botao": "Entrar"}


def test_conta_conectada_mostra_o_gamertag(monkeypatch, avisos):
    monkeypatch.setattr(conta, "conectada", lambda: True)
    monkeypatch.setattr(conta, "gamertag", lambda: "Jogador")
    grupo = _contas(avisos)
    assert grupo.microsoft["subtitulo"] == "Jogador"
    assert grupo.microsoft["botao"] == "Sair"


def test_conta_conectada_sem_gamertag_mostra_o_nome_da_conta(monkeypatch, avisos):
    monkeypatch.setattr(conta, "conectada", lambda: True)
    monkeypatch.setattr(conta, "gamertag", lambda: None)
    assert _contas(avisos).microsoft["subtitulo"] == "Conta Microsoft"


def test_entrar_espera_e_cancelar(monkeypatch, avisos):
    monkeypatch.setattr(conta, "conectada", lambda: False)
    pedidos = []

    class Pedido:
        def cancelar(self):
            pedidos.append("cancelado")

    monkeypatch.setattr(login, "entrar", lambda ao_terminar, **_k: pedidos.append(ao_terminar) or Pedido())
    grupo = _contas(avisos)
    grupo.clicarMicrosoft()
    assert grupo.microsoft["subtitulo"] == "Aguardando o login no navegador…"
    assert grupo.microsoft["botao"] == "Cancelar"
    grupo.clicarMicrosoft()
    assert pedidos[-1] == "cancelado"


def test_entrar_que_levanta_vira_aviso_e_nao_escapa(monkeypatch, avisos):
    """Socket bloqueado, limite de handles, falha de bind: o clique não levanta, a linha volta ao estado certo e a
    pessoa vê o aviso."""
    monkeypatch.setattr(conta, "conectada", lambda: False)

    def entrar(_ao_terminar, **_k):
        raise OSError("bloqueado")

    monkeypatch.setattr(login, "entrar", entrar)
    grupo = _contas(avisos)
    grupo.clicarMicrosoft()
    assert avisos.textos == ["Não foi possível entrar na conta Microsoft."]
    assert grupo.microsoft["subtitulo"] == "Não conectada"
    assert grupo.microsoft["botao"] == "Entrar"


@pytest.mark.parametrize(
    "nome, aviso",
    [
        ("SEM_PERFIL_XBOX", "Esta conta Microsoft não tem um perfil Xbox."),
        ("CONTA_INFANTIL", "Esta conta precisa de permissão de um responsável para usar o Xbox."),
        ("FALHOU", "Não foi possível entrar na conta Microsoft."),
        ("SEM_NAVEGADOR", "Não foi possível abrir o navegador. Verifique o navegador padrão do Windows."),
        ("PRAZO_ESGOTADO", "O login da conta Microsoft expirou. Tente novamente."),
        ("CANCELADO", None),
    ],
)
def test_resultado_do_login(monkeypatch, avisos, nome, aviso):
    monkeypatch.setattr(conta, "conectada", lambda: False)
    grupo = _contas(avisos)
    grupo._ao_entrar(login.Resultado[nome])  # noqa: SLF001
    assert avisos.textos == ([aviso] if aviso else [])
    assert grupo.microsoft["botao"] == "Entrar"


def test_login_ok_varre_os_jogos_do_xbox(monkeypatch, avisos, store, make_game):
    monkeypatch.setattr(conta, "conectada", lambda: True)
    monkeypatch.setattr(conta, "gamertag", lambda: "Jogador")
    xbox = make_game(game_id="shortcuts_1", executable='start "" "shell:AppsFolder\\P_a!G"')
    outro = make_game(game_id="shortcuts_2")
    for g in (xbox, outro):
        store.add_game(g, {}, run_pipeline=False)
    varridos = []
    _varredura_falsa(avisos, varridos)
    grupo = _contas(avisos)
    grupo._ao_entrar(login.Resultado.OK)  # noqa: SLF001
    assert varridos == [xbox]
    assert grupo.microsoft["subtitulo"] == "Jogador"


def test_login_ok_nao_olha_o_disco_dos_jogos_na_thread_principal(monkeypatch, avisos, store, make_game):
    """A foto da store sai na thread principal; o filtro (que lê o disco do jogo) vai para a thread da varredura,
    que o aplica lá."""
    monkeypatch.setattr(conta, "conectada", lambda: True)
    monkeypatch.setattr(conta, "gamertag", lambda: "Jogador")
    xbox = make_game(game_id="shortcuts_1", executable='start "" "shell:AppsFolder\\P_a!G"')
    outro = make_game(game_id="shortcuts_2")
    for g in (xbox, outro):
        store.add_game(g, {}, run_pipeline=False)
    consultados = []
    monkeypatch.setattr(fontes, "eh_do_xbox", lambda game: consultados.append(game) or game is xbox)
    pedidos = []
    _varredura_falsa(avisos, [], pedidos)
    grupo = _contas(avisos)
    grupo._ao_entrar(login.Resultado.OK)  # noqa: SLF001
    ((jogos, filtro),) = pedidos
    assert set(jogos) == {xbox, outro}
    assert consultados == []
    assert filtro(xbox) is True and filtro(outro) is False


def test_cancelar_na_troca_com_a_conta_conectada_conta_como_ok(monkeypatch, avisos, store, make_game):
    """Cancelar durante a troca pode deixar a conta conectada: o resultado chega como CANCELADO, mas o que vale é o
    estado da conta."""
    monkeypatch.setattr(conta, "conectada", lambda: True)
    monkeypatch.setattr(conta, "gamertag", lambda: "Jogador")
    xbox = make_game(game_id="shortcuts_1", executable='start "" "shell:AppsFolder\\P_a!G"')
    store.add_game(xbox, {}, run_pipeline=False)
    varridos = []
    _varredura_falsa(avisos, varridos)
    grupo = _contas(avisos)
    grupo._ao_entrar(login.Resultado.CANCELADO)  # noqa: SLF001
    assert varridos == [xbox]
    assert avisos.textos == []
    assert grupo.microsoft["botao"] == "Sair"


def test_falha_com_a_conta_conectada_nao_varre(monkeypatch, avisos, store, make_game):
    monkeypatch.setattr(conta, "conectada", lambda: True)
    monkeypatch.setattr(conta, "gamertag", lambda: "Jogador")
    varridos = []
    _varredura_falsa(avisos, varridos)
    grupo = _contas(avisos)
    grupo._ao_entrar(login.Resultado.FALHOU)  # noqa: SLF001
    assert varridos == []
    assert grupo.microsoft["botao"] == "Sair"


def test_varredura_do_xbox_que_falha_nao_levanta(monkeypatch, avisos, store, make_game):
    monkeypatch.setattr(conta, "conectada", lambda: True)
    monkeypatch.setattr(conta, "gamertag", lambda: "Jogador")

    class Varredura:
        def varrer_jogos(self, games, filtro=None):
            raise RuntimeError("falhou")

    shared.aplicativo.varredura_conquistas = Varredura()
    xbox = make_game(game_id="shortcuts_1", executable='start "" "shell:AppsFolder\\P_a!G"')
    store.add_game(xbox, {}, run_pipeline=False)
    _contas(avisos)._ao_entrar(login.Resultado.OK)  # noqa: SLF001


def test_sair(monkeypatch, avisos):
    estado = {"conectada": True}
    monkeypatch.setattr(conta, "conectada", lambda: estado["conectada"])
    monkeypatch.setattr(conta, "gamertag", lambda: "Jogador")
    monkeypatch.setattr(conta, "sair", lambda: estado.update(conectada=False))
    grupo = _contas(avisos)
    grupo.clicarMicrosoft()
    assert grupo.microsoft["subtitulo"] == "Não conectada"
    assert grupo.microsoft["botao"] == "Entrar"


def test_conta_que_muda_atualiza_a_linha(monkeypatch, avisos):
    estado = {"conectada": False}
    ouvintes = []
    monkeypatch.setattr(conta, "conectada", lambda: estado["conectada"])
    monkeypatch.setattr(conta, "gamertag", lambda: "Jogador")
    monkeypatch.setattr(conta, "ao_mudar", lambda ouvinte: ouvintes.append(ouvinte) or (lambda: None))
    grupo = _contas(avisos)
    estado["conectada"] = True
    ouvintes[0]()
    assert grupo.microsoft["subtitulo"] == "Jogador"


def test_fechar_cancela_o_login_e_solta_o_ouvinte(monkeypatch, avisos):
    cancelados = []
    removidos = []
    monkeypatch.setattr(login, "cancelar_pendente", lambda: cancelados.append(1))
    monkeypatch.setattr(conta, "ao_mudar", lambda _o: lambda: removidos.append(1))
    _contas(avisos).fechar()
    assert cancelados == [1]
    assert removidos == [1]


# A conta Epic


def test_descricao_do_grupo_das_contas(avisos):
    grupo = _contas(avisos)
    assert grupo.titulo == "Contas"
    assert grupo.descricao == (
        "Entre com as contas das lojas para acompanhar as conquistas dos jogos do Xbox, "
        "do Game Pass, da Epic Games Store e do EA app."
    )


def test_conta_epic_desconectada(monkeypatch, avisos):
    monkeypatch.setattr(epic_conta, "conectada", lambda: False)
    assert _contas(avisos).epic == {"titulo": "Conta Epic", "subtitulo": "Não conectada", "botao": "Entrar"}


def test_conta_epic_conectada_mostra_o_nome(monkeypatch, avisos):
    monkeypatch.setattr(epic_conta, "conectada", lambda: True)
    monkeypatch.setattr(epic_conta, "nome", lambda: "Jogador")
    grupo = _contas(avisos)
    assert grupo.epic["subtitulo"] == "Jogador"
    assert grupo.epic["botao"] == "Sair"


def test_entrar_abre_a_janela_e_o_sucesso_varre_os_jogos_da_epic(monkeypatch, avisos, store):
    monkeypatch.setattr(epic_conta, "conectada", lambda: False)
    monkeypatch.setattr(epic_conta, "conectar", lambda _codigo: None)
    pedidos = []
    _varredura_falsa(avisos, [], pedidos)
    abertas = []
    grupo = _contas(avisos, abrir=abertas.append)
    assert grupo.loginEpic is None
    grupo.clicarEpic()
    janela = grupo.loginEpic
    assert janela is not None and janela.aberto is True
    assert abertas == [epic_conta.PAGINA_DE_LOGIN]
    janela.texto = _COD
    janela.conectar()
    assert [filtro for _games, filtro in pedidos] == [fontes.eh_da_epic]
    assert grupo.loginEpic is None  # a janela fechou ao conectar


def test_entrar_com_janela_que_falha_ao_mostrar_deixa_tentar_de_novo(monkeypatch, avisos):
    criadas = []

    def abrir_que_falha(self):
        criadas.append(self)
        raise RuntimeError("falha ao apresentar")

    monkeypatch.setattr(epic_conta, "conectada", lambda: False)
    monkeypatch.setattr(modulo.LoginDaLoja, "abrir", abrir_que_falha)
    grupo = _contas(avisos)
    grupo.clicarEpic()
    grupo.clicarEpic()
    # O segundo clique não fica morto: cria outra janela.
    assert len(criadas) == 2
    assert grupo.loginEpic is None


def test_janela_da_epic_que_falha_ao_mostrar_avisa(monkeypatch, avisos):
    def abrir_que_falha(_self):
        raise RuntimeError("falha ao apresentar")

    monkeypatch.setattr(epic_conta, "conectada", lambda: False)
    monkeypatch.setattr(modulo.LoginDaLoja, "abrir", abrir_que_falha)
    _contas(avisos).clicarEpic()
    assert avisos.textos == ["Não foi possível abrir a janela de login da Epic."]


def test_entrar_com_a_janela_aberta_nao_abre_outra(monkeypatch, avisos):
    monkeypatch.setattr(epic_conta, "conectada", lambda: False)
    grupo = _contas(avisos)
    grupo.clicarEpic()
    primeira = grupo.loginEpic
    grupo.clicarEpic()
    assert grupo.loginEpic is primeira


@pytest.mark.parametrize(
    "modulo_da_conta, clicar, texto",
    [
        (epic_conta, "clicarEpic", "Não foi possível sair da conta Epic."),
        (ea_conta, "clicarEa", "Não foi possível sair da conta EA."),
    ],
)
def test_sair_que_falha_avisa_so_do_sair(monkeypatch, avisos, modulo_da_conta, clicar, texto):
    monkeypatch.setattr(modulo_da_conta, "conectada", lambda: True)
    monkeypatch.setattr(modulo_da_conta, "nome", lambda: "Jogador")

    def quebra():
        raise OSError("cofre")

    monkeypatch.setattr(modulo_da_conta, "sair", quebra)
    getattr(_contas(avisos), clicar)()
    assert avisos.textos == [texto]


def test_sair_da_epic(monkeypatch, avisos):
    estado = {"conectada": True}
    monkeypatch.setattr(epic_conta, "conectada", lambda: estado["conectada"])
    monkeypatch.setattr(epic_conta, "nome", lambda: "Jogador")
    monkeypatch.setattr(epic_conta, "sair", lambda: estado.update(conectada=False))
    grupo = _contas(avisos)
    grupo.clicarEpic()
    assert grupo.epic["subtitulo"] == "Não conectada"


def test_conta_epic_que_muda_atualiza_a_linha(monkeypatch, avisos):
    estado = {"conectada": False}
    ouvintes = []
    monkeypatch.setattr(epic_conta, "conectada", lambda: estado["conectada"])
    monkeypatch.setattr(epic_conta, "nome", lambda: "Jogador")
    monkeypatch.setattr(epic_conta, "ao_mudar", lambda ouvinte: ouvintes.append(ouvinte) or (lambda: None))
    grupo = _contas(avisos)
    estado["conectada"] = True
    ouvintes[0]()
    assert grupo.epic["subtitulo"] == "Jogador"


def test_fechar_o_grupo_fecha_a_janela_e_solta_o_ouvinte(monkeypatch, avisos):
    removidos = []
    monkeypatch.setattr(epic_conta, "conectada", lambda: False)
    monkeypatch.setattr(epic_conta, "ao_mudar", lambda _o: lambda: removidos.append(1))
    grupo = _contas(avisos)
    grupo.clicarEpic()
    janela = grupo.loginEpic
    grupo.fechar()
    assert janela.aberto is False and removidos == [1]
    assert grupo.loginEpic is None


# A conta EA


def test_conta_ea_desconectada(monkeypatch, avisos):
    monkeypatch.setattr(ea_conta, "conectada", lambda: False)
    assert _contas(avisos).ea == {"titulo": "Conta EA", "subtitulo": "Não conectada", "botao": "Entrar"}


def test_conta_ea_conectada_mostra_o_nome(monkeypatch, avisos):
    monkeypatch.setattr(ea_conta, "conectada", lambda: True)
    monkeypatch.setattr(ea_conta, "nome", lambda: "Jogador")
    grupo = _contas(avisos)
    assert grupo.ea["subtitulo"] == "Jogador"
    assert grupo.ea["botao"] == "Sair"


def test_entrar_abre_a_janela_e_o_sucesso_varre_os_jogos_da_ea(monkeypatch, avisos, store):
    monkeypatch.setattr(ea_conta, "conectada", lambda: False)
    monkeypatch.setattr(ea_conta, "conectar", lambda _texto: None)
    pedidos = []
    _varredura_falsa(avisos, [], pedidos)
    abertas = []
    grupo = _contas(avisos, abrir=abertas.append)
    grupo.clicarEa()
    janela = grupo.loginEa
    assert janela is not None and abertas == [ea_conta.PAGINA_DE_LOGIN]
    janela.texto = _CURL
    janela.conectar()
    assert [filtro for _games, filtro in pedidos] == [fontes.eh_da_ea]


def test_janela_da_ea_que_falha_ao_mostrar_avisa(monkeypatch, avisos):
    tentativas = []

    def abrir_que_falha(self):
        tentativas.append(self)
        raise RuntimeError("falha ao apresentar")

    monkeypatch.setattr(ea_conta, "conectada", lambda: False)
    monkeypatch.setattr(modulo.LoginDaLoja, "abrir", abrir_que_falha)
    grupo = _contas(avisos)
    grupo.clicarEa()
    assert avisos.textos == ["Não foi possível abrir a janela de login da EA."]
    grupo.clicarEa()
    assert len(tentativas) == 2


def test_sair_da_ea(monkeypatch, avisos):
    estado = {"conectada": True}
    monkeypatch.setattr(ea_conta, "conectada", lambda: estado["conectada"])
    monkeypatch.setattr(ea_conta, "nome", lambda: "Jogador")
    monkeypatch.setattr(ea_conta, "sair", lambda: estado.update(conectada=False))
    grupo = _contas(avisos)
    grupo.clicarEa()
    assert grupo.ea["subtitulo"] == "Não conectada"


def test_conta_ea_que_muda_atualiza_a_linha(monkeypatch, avisos):
    estado = {"conectada": False}
    ouvintes = []
    monkeypatch.setattr(ea_conta, "conectada", lambda: estado["conectada"])
    monkeypatch.setattr(ea_conta, "nome", lambda: "Jogador")
    monkeypatch.setattr(ea_conta, "ao_mudar", lambda ouvinte: ouvintes.append(ouvinte) or (lambda: None))
    grupo = _contas(avisos)
    estado["conectada"] = True
    ouvintes[0]()
    assert grupo.ea["subtitulo"] == "Jogador"


def test_fechar_o_grupo_fecha_a_janela_da_ea_e_solta_o_ouvinte(monkeypatch, avisos):
    removidos = []
    monkeypatch.setattr(ea_conta, "conectada", lambda: False)
    monkeypatch.setattr(ea_conta, "ao_mudar", lambda _o: lambda: removidos.append(1))
    grupo = _contas(avisos)
    grupo.clicarEa()
    janela = grupo.loginEa
    grupo.fechar()
    assert janela.aberto is False and removidos == [1]


# O grupo como um todo


def test_fechar_duas_vezes_nao_levanta(monkeypatch, avisos):
    monkeypatch.setattr(epic_conta, "conectada", lambda: False)
    monkeypatch.setattr(ea_conta, "conectada", lambda: False)
    grupo = _contas(avisos)
    grupo.clicarEpic()
    grupo.clicarEa()
    grupo.fechar()
    grupo.fechar()
    assert grupo.loginEpic is None and grupo.loginEa is None


def test_depois_de_fechar_a_conta_que_muda_nao_mexe_na_linha(monkeypatch, avisos):
    estado = {"conectada": False}
    monkeypatch.setattr(ea_conta, "conectada", lambda: estado["conectada"])
    monkeypatch.setattr(ea_conta, "nome", lambda: "Jogador")
    grupo = _contas(avisos)
    grupo.fechar()
    estado["conectada"] = True
    ea_conta._notificar(False)  # noqa: SLF001
    assert grupo.ea["subtitulo"] == "Não conectada"


def test_aviso_do_grupo_vai_para_a_fila_de_avisos(monkeypatch, avisos):
    monkeypatch.setattr(conta, "conectada", lambda: False)
    _contas(avisos)._ao_entrar(login.Resultado.FALHOU)  # noqa: SLF001
    assert avisos.textos == ["Não foi possível entrar na conta Microsoft."]


def test_ouvinte_do_grupo_nao_prende_o_grupo(monkeypatch, avisos):
    """Os ouvintes das contas são globais: com o grupo largado, eles não o seguram vivo."""
    import gc  # noqa: PLC0415
    import weakref  # noqa: PLC0415

    grupo = _contas(avisos)
    ref = weakref.ref(grupo)
    del grupo
    gc.collect()
    assert ref() is None


def test_conta_que_cai_atualiza_a_linha_e_o_cartao(avisos, flush_idle, monkeypatch):
    """Review Focus 2: a conta Microsoft recusada no meio da varredura, com a linha do grupo, a página e a lista
    do jogo abertas: um aviso só, a linha volta a "Não conectada" e o cartão some."""
    jogo = Jogo({"game_id": "imported_1", "source": "imported", "name": "Jogo 1"})
    catalogo.guardar(
        "xbox-7", Catalogo((ConquistaInfo("A", "Primeira", "Faça algo.", "", "", False, 55.0),), 0, True)
    )
    historico.registrar(jogo.game_id, [Desbloqueio("A", 100)])
    com_fonte(jogo, "xbox:7")
    monkeypatch.setattr(conta, "_sessao", conta._Sessao("R1", "Jogador", "1"))  # noqa: SLF001
    monkeypatch.setattr(conta, "_avisou", False)
    detalhes = _Detalhes(jogo)
    modelo = ConquistasDoJogo(detalhes)
    monkeypatch.setattr(shared, "conquistas", modelo, raising=False)
    grupo = _contas(avisos)
    detalhes.mostrar(jogo.game_id)
    modelo.abrir(jogo.game_id)
    assert grupo.microsoft["subtitulo"] == "Jogador" and grupo.microsoft["botao"] == "Sair"
    assert modelo.pagina["visivel"] is True and modelo.aberto is True

    conta.recusada()
    conta.recusada()  # a segunda não acha mais conta
    flush_idle()

    assert avisos.textos == ["A conta Microsoft foi desconectada. Entre novamente nas Preferências."]
    assert grupo.microsoft["subtitulo"] == "Não conectada" and grupo.microsoft["botao"] == "Entrar"
    assert modelo.pagina["visivel"] is False
    assert modelo.aberto is False


# O hospedeiro fecha e larga o grupo no meio da troca: a conta conecta mesmo assim, e a leitura dos jogos acontece.


def test_grupo_largado_no_meio_da_troca_ainda_varre(monkeypatch, avisos):
    import gc  # noqa: PLC0415

    monkeypatch.setattr(epic_conta, "conectada", lambda: False)
    monkeypatch.setattr(epic_conta, "conectar", lambda _c: None)
    varridos = []
    monkeypatch.setattr(modulo, "_varrer_jogos_da_loja", lambda _filtro, loja: varridos.append(loja))
    pendente = []
    grupo = _contas(avisos, em_thread=lambda t, e: pendente.append((t, e)))
    grupo.clicarEpic()
    grupo.loginEpic.texto = _COD
    grupo.loginEpic.conectar()
    grupo.fechar()  # a tela que hospedava o grupo fechou durante a troca
    del grupo
    gc.collect()
    trabalho, entregar = pendente[0]
    entregar(trabalho())
    assert varridos == ["Epic"]
    assert not modulo._em_voo  # noqa: SLF001  # o login não fica preso depois de entregar


def test_varre_os_jogos_quando_o_ok_chega_depois_do_cancelar(monkeypatch, avisos):
    estado = {"conectada": False}
    monkeypatch.setattr(conta, "conectada", lambda: estado["conectada"])
    monkeypatch.setattr(login, "cancelar_pendente", lambda: None)
    varridos = []
    monkeypatch.setattr(modulo, "_varrer_jogos_da_loja", lambda _filtro, loja: varridos.append(loja))
    grupo = _contas(avisos)
    grupo._ao_entrar(login.Resultado.CANCELADO)  # noqa: SLF001
    assert varridos == []
    estado["conectada"] = True
    grupo._ao_entrar(login.Resultado.OK)  # noqa: SLF001
    assert varridos == ["Xbox"]
    assert avisos.textos == []


def test_ok_tardio_nao_esquece_o_pedido_novo(monkeypatch, avisos):
    estado = {"conectada": False}
    monkeypatch.setattr(conta, "conectada", lambda: estado["conectada"])
    monkeypatch.setattr(login, "cancelar_pendente", lambda: None)
    monkeypatch.setattr(modulo, "_varrer_jogos_da_loja", lambda _filtro, _loja: None)
    retornos = []

    class Pedido:
        def cancelar(self):
            pass

    monkeypatch.setattr(login, "entrar", lambda ao_terminar, **_k: retornos.append(ao_terminar) or Pedido())
    grupo = _contas(avisos)
    grupo.clicarMicrosoft()
    grupo.clicarMicrosoft()  # cancela o primeiro
    retornos[0](login.Resultado.CANCELADO)
    grupo.clicarMicrosoft()  # pedido novo
    novo = grupo._pedido  # noqa: SLF001
    assert novo is not None
    estado["conectada"] = True  # a troca do antigo acabou conectando a conta
    retornos[0](login.Resultado.OK)  # o OK tardio do antigo
    assert grupo._pedido is novo  # noqa: SLF001


def test_grupo_largado_no_meio_do_login_da_microsoft_ainda_varre(monkeypatch, avisos):
    import gc  # noqa: PLC0415

    estado = {"conectada": False}
    monkeypatch.setattr(conta, "conectada", lambda: estado["conectada"])
    monkeypatch.setattr(login, "cancelar_pendente", lambda: None)
    pedidos = []

    class Pedido:
        def cancelar(self):
            pass

    monkeypatch.setattr(login, "entrar", lambda ao_terminar, **_k: pedidos.append(ao_terminar) or Pedido())
    varridos = []
    monkeypatch.setattr(modulo, "_varrer_jogos_da_loja", lambda _filtro, loja: varridos.append(loja))
    grupo = _contas(avisos)
    grupo.clicarMicrosoft()
    grupo.fechar()
    del grupo
    gc.collect()
    estado["conectada"] = True  # cancelar durante a troca deixou a conta conectada
    pedidos[0](login.Resultado.CANCELADO)
    assert varridos == ["Xbox"]
    assert avisos.textos == []  # a tela já fechou: só a leitura dos jogos
