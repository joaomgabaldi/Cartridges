# test_seletor_do_ludusavi.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A janela que escolhe o jogo do manifesto do Ludusavi."""

import time

from gi.repository import GLib

from cartridges import shared

MANIFESTO = 'Zelda:\n  files: {}\n"Alien: Isolation":\n  files: {}\nPortal:\n  files: {}\n'


def _girar(condicao, limite=5.0):
    contexto = GLib.MainContext.default()
    fim = time.monotonic() + limite
    while not condicao() and time.monotonic() < fim:
        contexto.iteration(False)
        time.sleep(0.005)
    assert condicao()


def _criar(atual="", manifesto=MANIFESTO):
    from cartridges.seletor_do_ludusavi import SeletorDoLudusavi  # noqa: PLC0415

    pasta = shared.app_dir / "ludusavi"
    pasta.mkdir(parents=True, exist_ok=True)
    if manifesto is not None:
        (pasta / "manifest.yaml").write_text(manifesto, encoding="utf-8")
    escolhidos = []
    janela = SeletorDoLudusavi(atual, escolhidos.append)
    return janela, escolhidos


def _nomes(janela):
    modelo = janela.filtrado
    return [modelo.get_item(i).get_string() for i in range(modelo.get_n_items())]


def test_mostra_todos_os_nomes_lidos_fora_da_tela():
    janela, _ = _criar()
    _girar(lambda: janela.pilha.get_visible_child_name() == "lista")
    assert _nomes(janela) == ["Alien: Isolation", "Portal", "Zelda"]


def test_digitar_filtra_sem_diferenciar_maiusculas():
    janela, _ = _criar()
    _girar(lambda: janela.pilha.get_visible_child_name() == "lista")
    janela.campo_busca.set_text("alien")
    _girar(lambda: _nomes(janela) == ["Alien: Isolation"])


def test_ativar_uma_linha_escolhe_e_fecha():
    janela, escolhidos = _criar()
    _girar(lambda: janela.pilha.get_visible_child_name() == "lista")
    janela.lista.emit("activate", 0)
    assert escolhidos == ["Alien: Isolation"]


def test_nenhum_escolhe_vazio():
    janela, escolhidos = _criar(atual="Portal")
    _girar(lambda: janela.pilha.get_visible_child_name() == "lista")
    janela.caixa_nenhum.emit("row-activated", janela.linha_nenhum)
    assert escolhidos == [""]


def test_manifesto_ilegivel_mostra_o_erro_e_nao_escolhe():
    janela, escolhidos = _criar(manifesto=None)
    _girar(lambda: janela.pilha.get_visible_child_name() == "erro")
    assert (
        janela.pagina_erro.get_title()
        == "Não foi possível ler a lista de jogos do Ludusavi."
    )
    assert escolhidos == []


def test_manifesto_truncado_sem_jogo_tambem_e_erro():
    janela, _ = _criar(manifesto="# nada\n")
    _girar(lambda: janela.pilha.get_visible_child_name() == "erro")


def test_a_opcao_fixa_diz_que_desliga_o_backup():
    janela, _ = _criar()
    assert janela.linha_nenhum.get_title() == "Nenhum (desliga o backup)"
