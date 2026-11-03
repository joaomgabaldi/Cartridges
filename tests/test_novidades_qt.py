# test_novidades_qt.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""As Novidades (D83): o `NewsChecker`, a lógica de tela `Novidades` e o botão, o selo e a página no `Aplicativo.qml`.

Nada de verdade: o `fetch_news` é falso (a rede também é recusada pelo `sem_rede`), o navegador é o guarda
`_sem_navegador` (abaixo: `abrir_url` anota em vez de abrir) e os timers do checker são parados antes e depois de cada teste.
"""

import subprocess
import sys
import threading
from pathlib import Path

import pytest
import requests
from PySide6.QtCore import QMetaObject, Qt
from PySide6.QtTest import QTest

from cartridges import shared
from cartridges.modelos import novidades as modulo_novidades
from cartridges.modelos.avisos import FilaDeAvisos
from cartridges.modelos.novidades import Novidades
from cartridges.utils import news_checker
from cartridges.utils.news_checker import NewsChecker
from tests.apoio_janela_atualizacao import Janela, achar, avaliar, esperar
from tests.apoio_novidades import CheckerFalso, post

RAIZ = Path(__file__).resolve().parent.parent
_ULTIMA = "news-last-seen-ts"


@pytest.fixture(autouse=True)
def _checkers_parados(monkeypatch):
    """Os timers dos checkers criados no teste param antes e depois (lição c do plano 7)."""
    criados = []
    original = NewsChecker.__init__

    def rastrear(self, *args, **kwargs):
        original(self, *args, **kwargs)
        criados.append(self)

    monkeypatch.setattr(NewsChecker, "__init__", rastrear)
    yield
    for checker in criados:
        checker.stop()


@pytest.fixture(autouse=True)
def _sem_navegador(monkeypatch):
    """`abrir_url` (QDesktopServices) nunca abre o navegador de verdade: anota e o teste que o pede lê a lista."""
    abertos = []
    monkeypatch.setattr(modulo_novidades, "abrir_url", abertos.append)
    return abertos


@pytest.fixture
def feed(monkeypatch):
    """O `fetch_news` falso: `feed.posts` é o que a próxima busca devolve (ou `feed.erro`, que ela levanta)."""

    class Feed:
        posts = []
        erro = None
        buscas = 0

    def falso():
        Feed.buscas += 1
        if Feed.erro is not None:
            raise Feed.erro
        return list(Feed.posts)

    monkeypatch.setattr(news_checker, "fetch_news", falso)
    return Feed


def _tela(checker=None):
    fila = FilaDeAvisos()
    return Novidades(fila, checker or NewsChecker()), fila


def _buscar(novidades, feed_):
    antes = feed_.buscas
    novidades._checker.check_async()  # noqa: SLF001
    assert esperar(lambda: feed_.buscas > antes and not novidades._checker.loading)  # noqa: SLF001


def test_news_checker_sem_gi():
    codigo = (
        "import builtins, sys; builtins._ = lambda m: m; "
        "import cartridges.utils.news_checker, cartridges.modelos.novidades; sys.exit('gi' in sys.modules)"
    )
    resultado = subprocess.run(
        [sys.executable, "-c", codigo], cwd=RAIZ, capture_output=True, text=True, timeout=60, check=False
    )
    assert resultado.returncode == 0, resultado.stderr


def test_b26_busca_que_falhou_nao_diz_atualizadas(app_qt):
    checker = NewsChecker()
    checker._posts = (post(1),)  # noqa: SLF001
    resultados = []
    checker.buscaTerminou.connect(resultados.append)

    checker._apply(None)  # noqa: SLF001

    assert resultados == [False]
    assert checker.posts, "o cache fica"


def test_primeira_busca_vira_linha_de_base_sem_selo(app_qt, feed):
    feed.posts = [post(300), post(200)]
    novidades, _ = _tela()
    avisos_do_selo = []
    novidades._checker.naoVistasMudou.connect(avisos_do_selo.append)  # noqa: SLF001

    _buscar(novidades, feed)

    assert shared.state_schema.get_int64(_ULTIMA) == 300
    assert novidades.naoVistas is False
    assert avisos_do_selo == []


def test_post_novo_acende_o_selo_e_abrir_apaga(app_qt, feed):
    shared.state_schema.set_int64(_ULTIMA, 100)
    feed.posts = [post(200)]
    novidades, _ = _tela()

    _buscar(novidades, feed)
    assert novidades.naoVistas is True
    assert shared.state_schema.get_int64(_ULTIMA) == 100

    novidades.abrir()
    assert novidades.naoVistas is False
    assert shared.state_schema.get_int64(_ULTIMA) == 200


def test_posts_iguais_nao_refazem_a_lista(app_qt, feed):
    feed.posts = [post(200)]
    novidades, _ = _tela()
    refeitas = []
    novidades.listaRefeita.connect(lambda: refeitas.append(1))

    _buscar(novidades, feed)
    _buscar(novidades, feed)
    assert refeitas == [1]

    feed.posts = [post(300), post(200)]
    _buscar(novidades, feed)
    assert refeitas == [1, 1]


def test_posts_novos_com_a_pagina_a_vista_ja_nascem_vistos(app_qt, feed):
    shared.state_schema.set_int64(_ULTIMA, 100)
    feed.posts = [post(200)]
    novidades, _ = _tela()
    novidades.paginaVisivel(True)

    _buscar(novidades, feed)

    assert novidades.naoVistas is False
    assert shared.state_schema.get_int64(_ULTIMA) == 200


@pytest.mark.parametrize(("horas", "armado"), [(0, False), (-3, False), (6, True)])
def test_intervalo_zero_nao_arma_o_timer(app_qt, feed, horas, armado):
    shared.schema.set_int("news-check-interval", horas)
    checker = NewsChecker()
    checker.start()
    assert checker._timer.isActive() is armado  # noqa: SLF001
    if armado:
        assert checker._timer.interval() == 6 * 3600 * 1000  # noqa: SLF001
        # Já armado e depois desligado: o relógio velho não sobrevive.
        shared.schema.set_int("news-check-interval", 0)
        checker.start()
        assert checker._timer.isActive() is False  # noqa: SLF001
    checker.stop()


def test_intervalo_enorme_nao_estoura_o_temporizador(app_qt, feed):
    shared.schema.set_int("news-check-interval", 2147483647)
    checker = NewsChecker()
    checker.start()
    assert checker._timer.isActive() is True  # noqa: SLF001
    assert checker._timer.interval() == 2**31 - 1  # noqa: SLF001
    checker.stop()


def test_resultado_da_busca_depois_do_stop_e_descartado(app_qt, feed):
    """Review Focus 3: a busca em voo que chega depois do `stop()` só solta a trava."""
    feed.posts = [post(200)]
    checker = NewsChecker()
    emitidos = []
    checker.postsMudaram.connect(lambda: emitidos.append("posts"))
    checker.buscaTerminou.connect(lambda _ok: emitidos.append("fim"))
    checker.naoVistasMudou.connect(lambda _v: emitidos.append("selo"))

    checker.check_async()
    checker.stop()  # antes de o laço entregar o resultado da thread
    assert esperar(lambda: not checker.loading)

    assert emitidos == []
    assert checker.posts == ()
    assert shared.state_schema.get_int64(_ULTIMA) == 0
    # Parado, nem uma busca nova começa.
    antes = feed.buscas
    checker.check_async()
    esperar()
    assert feed.buscas == antes


def test_estado_da_pagina_lista_carregando_vazio(app_qt):
    checker = CheckerFalso()
    novidades, _ = _tela(checker)
    assert novidades.estado == "vazio"

    checker.loading = True
    assert novidades.estado == "carregando"

    checker.posts = (post(1),)
    assert novidades.estado == "lista"  # com posts a lista vence a busca em voo

    checker.loading = False
    checker.posts = ()
    assert novidades.estado == "vazio"


def test_abrir_sem_posts_busca_e_com_posts_so_reconhece(app_qt):
    checker = CheckerFalso()
    novidades, _ = _tela(checker)

    novidades.abrir()
    assert checker.chamadas == ["mark_seen", "check_async"]

    checker.chamadas.clear()
    checker.posts = (post(1),)
    novidades.abrir()
    assert checker.chamadas == ["mark_seen"]


def test_datas_relativas_refeitas_ao_abrir(app_qt, monkeypatch):
    """A data relativa envelhece com o app aberto: abrir a página a refaz, sem mandar a lista ao topo."""
    checker = CheckerFalso()
    checker.posts = (post(100),)
    datas = ["hoje"]
    monkeypatch.setattr(modulo_novidades, "relative_date", lambda _ts: datas[0])
    novidades, _ = _tela(checker)
    refeitas = []
    avisos_de_mudanca = []
    novidades.listaRefeita.connect(lambda: refeitas.append(1))
    novidades.alterado.connect(lambda: avisos_de_mudanca.append(1))
    assert novidades.posts[0]["subtitulo"].startswith("hoje")

    datas[0] = "ontem"
    # DA-37: a página voltar a ficar à vista não refaz a lista (recolheria as linhas abertas); abrir refaz.
    novidades.paginaVisivel(True)
    assert novidades.posts[0]["subtitulo"].startswith("hoje")
    novidades.abrir()

    assert novidades.posts[0]["subtitulo"].startswith("ontem")
    assert avisos_de_mudanca and refeitas == []


def test_atualizar_avisa_e_troca_o_aviso_pelo_resultado(app_qt, feed):
    feed.posts = [post(200)]
    novidades, fila = _tela()

    novidades.atualizar()
    assert esperar(lambda: fila.texto == "Atualizando novidades…")
    assert esperar(lambda: fila.texto == "Novidades atualizadas")
    assert fila.visivel is True  # o "Atualizando…" saiu, o resultado ficou

    fila.fechar()  # o aviso do resultado sai da frente; o próximo pedido é um aviso novo
    QTest.qWait(250)  # o fade: um "Atualizando…" enfileirado aqui sairia da fila antes de aparecer
    feed.erro = requests.ConnectionError("sem rede")
    novidades.atualizar()
    assert esperar(lambda: fila.texto == "Atualizando novidades…")
    assert esperar(lambda: fila.texto == "Não foi possível atualizar as novidades")
    # O cache da busca anterior continua à mostra.
    assert novidades.estado == "lista"


def test_busca_automatica_termina_em_silencio(app_qt, feed):
    feed.posts = [post(200)]
    novidades, fila = _tela()
    _buscar(novidades, feed)
    assert fila.visivel is False


def test_atualizar_com_busca_em_voo_nao_comeca_outra(app_qt):
    checker = CheckerFalso()
    checker.loading = True
    shared.schema.set_boolean("show-news-button", True)  # feed ligado: a busca em voo é a que responde
    novidades, fila = _tela(checker)

    novidades.atualizar()

    assert "check_async" not in checker.chamadas
    assert esperar(lambda: fila.texto == "Atualizando novidades…")
    # O fim da busca em voo responde ao pedido do mesmo jeito.
    checker.buscaTerminou.emit(True)
    assert esperar(lambda: fila.texto == "Novidades atualizadas")
def test_desligar_a_chave_tira_o_aviso_de_atualizando(app_qt):
    checker = CheckerFalso()
    novidades, fila = _tela(checker)
    novidades.atualizar()
    assert fila.visivel is True

    novidades.ligar()  # `show-news-button` desligada: o feed para e nenhuma busca responderia

    assert fila.visivel is False


def test_atualizar_com_o_feed_parado_nao_deixa_aviso_eterno(app_qt, feed):
    """Página aberta e chave desligada: o checker parado não busca; o "Atualizando…" (sem prazo) não pode ficar."""
    novidades, fila = _tela()
    novidades.ligar()  # chave desligada: `stop()`

    novidades.atualizar()

    assert feed.buscas == 0
    assert esperar(lambda: fila.texto == "Não foi possível atualizar as novidades")
    fila.fechar()
    assert fila.visivel is False  # nada ficou na fila atrás


def test_atualizar_com_busca_em_voo_e_chave_desligada_nao_deixa_aviso_eterno(app_qt, monkeypatch):
    """Review final: busca em voo + chave desligada + "Atualizar" antes do fim: a busca abandonada nunca responderia."""
    soltar = threading.Event()
    monkeypatch.setattr(news_checker, "fetch_news", lambda: soltar.wait(10) and [])
    novidades, fila = _tela()
    try:
        shared.schema.set_boolean("show-news-button", True)
        novidades.ligar()  # a primeira busca fica em voo
        assert esperar(lambda: novidades._checker.loading)  # noqa: SLF001
        shared.schema.set_boolean("show-news-button", False)
        novidades.ligar()  # `stop()`: a busca em voo é abandonada, mas `loading` segue verdadeiro

        novidades.atualizar()

        assert esperar(lambda: fila.texto == "Não foi possível atualizar as novidades")
    finally:
        soltar.set()
        assert esperar(lambda: not novidades._checker.loading)  # noqa: SLF001
        novidades.parar()


def test_acompanhar_a_chave_duas_vezes_liga_uma_so(app_qt):
    checker = CheckerFalso()
    novidades, _ = _tela(checker)
    novidades.acompanhar_a_chave()
    novidades.acompanhar_a_chave()

    shared.schema.set_boolean("show-news-button", True)
    assert checker.chamadas == ["start"]
    novidades.parar()  # o `stop()` do próprio `parar`; a chave solta depois não liga nada
    shared.schema.set_boolean("show-news-button", False)
    assert checker.chamadas == ["start", "stop"]


def test_chave_liga_e_desliga_o_feed(app_qt):
    checker = CheckerFalso()
    novidades, _ = _tela(checker)
    novidades.acompanhar_a_chave()

    shared.schema.set_boolean("show-news-button", True)
    shared.schema.set_boolean("show-news-button", False)
    novidades.parar()
    shared.schema.set_boolean("show-news-button", True)  # depois do `parar()` nada mais é ligado

    assert checker.chamadas == ["start", "stop", "stop"]


def test_abrir_no_navegador_so_aceita_url_da_lista(app_qt, _sem_navegador):
    checker = CheckerFalso()
    checker.posts = (post(2, url="https://x/2"), post(1, url=""))
    novidades, _ = _tela(checker)
    abertos = _sem_navegador

    novidades.abrirNoNavegador("https://x/2")
    novidades.abrirNoNavegador("https://fora/da-lista")
    novidades.abrirNoNavegador("")

    assert abertos == ["https://x/2"]


def test_subtitulo_sem_partes_vazias(app_qt):
    checker = CheckerFalso()
    checker.posts = (post(0, categoria="Anúncio"), post(1_000_000_000, categoria=""), post(1_000_000_000))
    novidades, _ = _tela(checker)

    assert novidades.posts[0]["subtitulo"] == "Anúncio"  # sem data (timestamp 0), só a categoria
    assert " · " not in novidades.posts[1]["subtitulo"]
    assert novidades.posts[2]["subtitulo"].endswith(" · Repack")
    assert set(novidades.posts[0]) == {"titulo", "subtitulo", "resumo", "url"}


# -- a janela inteira ------------------------------------------------------------------------------------------


@pytest.fixture
def janela(app_qt, monkeypatch, sem_instalador_de_verdade, feed):  # noqa: ARG001
    j = Janela()
    monkeypatch.setattr(shared, "aplicativo", j.aplicativo, raising=False)
    j.novidades.acompanhar_a_chave()
    yield j
    j.novidades.parar()
    j.fechar()


def _ligar(janela):
    shared.schema.set_boolean("show-news-button", True)
    esperar()


def _clique(janela, nome):
    QMetaObject.invokeMethod(janela.achar(nome), "click", Qt.ConnectionType.DirectConnection)


def _abrir_a_pagina(janela):
    _ligar(janela)
    _clique(janela, "botaoNovidades")
    assert esperar(lambda: janela.achar("pilha").property("depth") == 1)


def _posts_na_lista(janela):
    lista = janela.achar("listaDasNovidades")
    return [i for i in lista.property("contentItem").childItems() if i.property("expansivel") is not None]


def _texto(raiz, conteudo):
    """O `Text` abaixo de `raiz` cujo texto é `conteudo`."""
    pilha = [raiz]
    while pilha:
        atual = pilha.pop()
        if atual.property("text") == conteudo and avaliar(atual, "textFormat === Text.PlainText") is True:
            return atual
        pilha.extend(atual.childItems())
    return None


def test_botao_entre_zerados_e_big_picture_so_com_a_chave(janela):
    botao = janela.achar("botaoNovidades")
    assert botao.property("visible") is False

    _ligar(janela)
    assert botao.property("visible") is True
    assert botao.property("dica") == "Novidades"

    def x(nome):
        item = janela.achar(nome)
        return item.mapToScene(item.position()).x()

    # Da direita para a esquerda: menu, troféu, novidades, Big Picture, busca.
    assert x("botaoMenu") > x("botaoZerados") > x("botaoNovidades") > x("botaoBigPicture") > x("botaoBusca")

    shared.schema.set_boolean("show-news-button", False)
    esperar()
    assert botao.property("visible") is False


def test_selo_acompanha_nao_vistas(janela, feed):
    shared.state_schema.set_int64(_ULTIMA, 100)
    feed.posts = [post(200)]
    _ligar(janela)
    selo = achar(janela.achar("botaoNovidades"), "seloDoBotao")
    assert esperar(lambda: selo.property("visible") is True)
    assert janela.achar("botaoNovidades").property("selo") is True

    _clique(janela, "botaoNovidades")
    assert esperar(lambda: selo.property("visible") is False)
    assert shared.state_schema.get_int64(_ULTIMA) == 200


def test_pagina_na_pilha_e_voltar(janela, feed):
    feed.posts = [post(200, titulo="Alfa")]
    _ligar(janela)
    assert janela.achar("botaoAtualizarNovidades").property("visible") is False

    _abrir_a_pagina(janela)
    assert janela.janela.property("paginaAtual") == "novidades"
    assert avaliar(janela.janela, "tituloDaBarra") == "Novidades"
    assert janela.achar("botaoAtualizarNovidades").property("visible") is True
    assert janela.achar("botaoVoltar").property("visible") is True
    # Fora de "Todos os jogos" os botões da biblioteca somem.
    assert janela.achar("botaoNovidades").property("visible") is False
    assert janela.achar("botaoZerados").property("visible") is False

    _clique(janela, "botaoVoltar")
    assert esperar(lambda: janela.achar("pilha").property("depth") == 0)
    assert janela.janela.property("paginaAtual") == "todos"
    assert janela.achar("botaoAtualizarNovidades").property("visible") is False


def test_atualizar_da_barra_busca_e_avisa(janela, feed):
    feed.posts = [post(200)]
    _abrir_a_pagina(janela)
    buscas = feed.buscas

    _clique(janela, "botaoAtualizarNovidades")

    assert esperar(lambda: feed.buscas > buscas)
    assert esperar(lambda: janela.aplicativo.avisos.texto == "Novidades atualizadas")


def test_tentar_novamente_busca(janela, feed):
    feed.erro = requests.ConnectionError("sem rede")
    _abrir_a_pagina(janela)
    vazio = janela.achar("novidadesVazias")
    assert esperar(lambda: vazio.property("visible") is True)
    assert vazio.property("titulo") == "Sem novidades"
    assert vazio.property("descricao") == "Não foi possível carregar as novidades."
    assert vazio.property("rotuloDoBotao") == "Tentar novamente"

    feed.erro = None
    feed.posts = [post(200, titulo="Voltou")]
    buscas = feed.buscas
    avaliar(vazio, "botaoClicado()")

    assert esperar(lambda: feed.buscas > buscas)
    assert esperar(lambda: janela.achar("listaDasNovidades").property("visible") is True)
    assert vazio.property("visible") is False


def test_carregando_mostra_o_indicador(janela):
    checker = janela.novidades._checker  # noqa: SLF001
    checker._running = True  # noqa: SLF001
    try:
        _abrir_a_pagina(janela)
        assert esperar(lambda: janela.achar("carregandoNovidades").property("visible") is True)
        assert janela.achar("novidadesVazias").property("visible") is False
    finally:
        checker._running = False  # noqa: SLF001


def test_post_com_tags_aparece_em_texto_puro(janela, feed):
    """Review Focus 2: o feed é de terceiros; `&`, `<b>` e `<a href>` aparecem como estão."""
    resumo_do_feed = 'Veja <a href="x">aqui</a> & <i>já</i>'
    feed.posts = [post(200, titulo="Tom & <b>Jerry</b>", resumo=resumo_do_feed, url="https://x/1")]
    _abrir_a_pagina(janela)
    assert esperar(lambda: len(_posts_na_lista(janela)) == 1)
    linha = _posts_na_lista(janela)[0]

    titulo = _texto(linha, "Tom & <b>Jerry</b>")
    assert titulo is not None
    assert avaliar(titulo, "textFormat === Text.PlainText") is True

    linha.setProperty("aberta", True)
    esperar()
    resumo = _texto(linha, resumo_do_feed)
    assert resumo is not None
    assert avaliar(resumo, "textFormat === Text.PlainText") is True


def test_post_sem_resumo_nem_link_e_linha_simples(janela, feed):
    feed.posts = [post(200, titulo="Só título", resumo="", url=""), post(100, titulo="Completo")]
    _abrir_a_pagina(janela)
    assert esperar(lambda: len(_posts_na_lista(janela)) == 2)
    simples, completa = _posts_na_lista(janela)

    assert simples.property("expansivel") is False
    assert completa.property("expansivel") is True
    avaliar(simples, "alternar()")
    assert simples.property("aberta") is False


def test_teclado_setas_e_enter_expandem_e_tab_chega_ao_link(janela, feed):
    feed.posts = [post(200, titulo="Alfa"), post(100, titulo="Beta")]
    _abrir_a_pagina(janela)
    assert esperar(lambda: len(_posts_na_lista(janela)) == 2)
    primeira, segunda = _posts_na_lista(janela)
    assert esperar(lambda: primeira.property("activeFocus") is True)

    QTest.keyClick(janela.janela, Qt.Key.Key_Down)
    assert esperar(lambda: segunda.property("activeFocus") is True)
    QTest.keyClick(janela.janela, Qt.Key.Key_Return)
    assert segunda.property("aberta") is True
    assert primeira.property("aberta") is False
    QTest.keyClick(janela.janela, Qt.Key.Key_Tab)
    assert esperar(lambda: janela.achar("abrirNoNavegador").property("activeFocus") is True)
    QTest.keyClick(janela.janela, Qt.Key.Key_Escape)
    assert esperar(lambda: janela.janela.property("paginaAtual") == "todos")


def test_grupo_barra_superior_e_o_primeiro_da_personalizacao(janela):
    janela.preferencias.abrir("session")
    esperar()
    grupo = janela.achar("grupoBarraSuperior")
    assert grupo.property("titulo") == "Barra superior"
    assert grupo.property("y") < janela.achar("grupoBiblioteca").property("y")

    interruptor = janela.achar("interruptor-show-news-button")
    assert interruptor.property("titulo") == "Mostrar o botão Novidades"
    assert interruptor.property("buscavel") is True
    assert interruptor.property("checked") is False

    janela.preferencias.definir("show-news-button", True)  # grava de verdade: a chave voltou à lista
    assert shared.schema.get_boolean("show-news-button") is True
    assert esperar(lambda: interruptor.property("checked") is True)
    assert janela.achar("botaoNovidades").property("visible") is True


def test_sem_novidades_no_contexto_o_botao_fica_oculto_sem_erro(app_qt, monkeypatch, sem_instalador_de_verdade):  # noqa: ARG001
    j = Janela(com_novidades=False)
    try:
        shared.schema.set_boolean("show-news-button", True)
        esperar()
        botao = j.achar("botaoNovidades")
        assert botao.property("visible") is False
        assert botao.property("selo") is False
    finally:
        j.fechar()


def test_posts_que_chegam_com_a_pagina_aberta_nao_puxam_o_foco(janela):
    """DA-36: refazer a lista não leva o foco à primeira linha (a `main` não o move; o Tab já entra nela)."""
    checker = janela.checker
    checker._running = True  # noqa: SLF001
    _abrir_a_pagina(janela)
    assert esperar(lambda: janela.achar("carregandoNovidades").property("visible") is True)

    checker._apply([post(200, titulo="Alfa")])  # noqa: SLF001

    assert esperar(lambda: len(_posts_na_lista(janela)) == 1)
    esperar()
    assert _posts_na_lista(janela)[0].property("activeFocus") is False
