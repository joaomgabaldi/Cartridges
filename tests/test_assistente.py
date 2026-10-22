import pytest


@pytest.fixture(autouse=True)
def _sem_monitores(monkeypatch):
    # Os testes não dependem dos monitores da máquina; quem precisa sobrescreve.
    from cartridges.utils import window_geometry

    monkeypatch.setattr(window_geometry, "monitores_da_sessao", lambda: [])


def _janela(**kw):
    from cartridges.assistente import JanelaDoAssistente

    terminou, restaurou = [], []
    janela = JanelaDoAssistente(
        ao_terminar=lambda: terminou.append(1),
        ao_restaurar=lambda: restaurou.append(1),
        **kw,
    )
    return janela, terminou, restaurou


def test_mostra_com_biblioteca_vazia(schema):
    from cartridges import assistente

    assert assistente.precisa_mostrar() is True
    assert schema.get_boolean("assistente-concluido") is False


def test_com_jogos_marca_e_nao_mostra(schema, app_dirs):
    from cartridges import assistente

    (app_dirs.games / "1.json").write_text("{}")
    assert assistente.precisa_mostrar() is False
    assert schema.get_boolean("assistente-concluido") is True


def test_concluido_nao_mostra(schema):
    from cartridges import assistente

    schema.set_boolean("assistente-concluido", True)
    assert assistente.precisa_mostrar() is False


def test_concluir_chama_ao_terminar_antes_de_destruir(schema):
    from cartridges.assistente import JanelaDoAssistente

    ordem = []
    janela = JanelaDoAssistente(
        ao_terminar=lambda: ordem.append("terminou"), ao_restaurar=lambda: None
    )
    janela.destroy = lambda: ordem.append("destruida")
    janela.concluir()
    assert ordem == ["terminou", "destruida"]


def test_concluir_destroi_a_janela_mesmo_se_ao_terminar_falhar(schema):
    from cartridges.assistente import JanelaDoAssistente

    destruida = []

    def quebra():
        raise RuntimeError("falha de teste")

    janela = JanelaDoAssistente(ao_terminar=quebra, ao_restaurar=lambda: None)
    janela.destroy = lambda: destruida.append(1)
    with pytest.raises(RuntimeError):
        janela.concluir()
    assert destruida == [1]


def test_concluir_marca_e_chama_ao_terminar(schema):
    janela, terminou, _ = _janela()
    janela.concluir()
    assert schema.get_boolean("assistente-concluido") is True and terminou == [1]


def test_pasta_grava_e_liga_importacao_e_a_ultima_vale(schema, tmp_path):
    janela, _, _ = _janela()
    janela.gravar_pasta(tmp_path / "a")
    janela.gravar_pasta(tmp_path / "b")
    assert schema.get_string("shortcuts-location") == str(tmp_path / "b")
    assert schema.get_boolean("auto-import") is True
    assert janela.pasta_row.get_subtitle() == str(tmp_path / "b").replace("/", "\\")


def test_chave_sgdb_liga_e_apagar_desliga(schema):
    janela, _, _ = _janela()
    janela.chave_sgdb_row.set_text("  k  ")
    assert schema.get_string("sgdb-key") == "k" and schema.get_boolean("sgdb") is True
    assert janela.capas_animadas_switch.get_visible()
    janela.chave_sgdb_row.set_text("")
    assert schema.get_boolean("sgdb") is False
    assert not janela.capas_animadas_switch.get_visible()


def test_capas_animadas_grava_as_duas_chaves(schema):
    janela, _, _ = _janela()
    janela.chave_sgdb_row.set_text("k")
    janela.capas_animadas_switch.set_active(True)
    assert schema.get_boolean("sgdb-animated") and schema.get_boolean("cover-autoplay")


def test_sem_pasta_o_subtitulo_avisa():
    janela, _, _ = _janela()
    assert janela.pasta_row.get_subtitle() == "Nenhuma pasta selecionada"


def test_navegacao_e_rodape(monkeypatch):
    from cartridges.utils import window_geometry

    monkeypatch.setattr(window_geometry, "monitores_da_sessao", lambda: [])
    janela, _, _ = _janela()
    assert len(janela.paginas()) == 7
    assert not janela.botoes.get_visible()
    janela.avancar()
    assert janela.botoes.get_visible()
    janela.voltar()
    assert not janela.botoes.get_visible()


def test_textos_das_telas():
    janela, _, _ = _janela()
    assert janela.get_title() == "Cartridges"
    assert janela.pagina_boas_vindas.get_title() == "Boas-vindas ao Cartridges"
    assert janela.pagina_boas_vindas.get_description() == (
        "Reúna os seus jogos em uma única biblioteca, com capas, tempo de jogo e "
        "conquistas. Configure o essencial em poucos passos."
    )
    assert janela.comecar_botao.get_label() == "Começar"
    assert janela.restaurar_botao.get_label() == "Restaurar um backup"
    assert janela.pular_configuracao_botao.get_label() == "Pular configuração"
    assert janela.pagina_jogos.get_title() == "Seus jogos"
    assert janela.pagina_jogos.get_description() == (
        "O Cartridges adiciona à biblioteca os jogos cujos atalhos estão em uma pasta. "
        "Escolha a pasta onde estão, ou onde ficarão, os atalhos dos seus jogos. Novos "
        "atalhos colocados nela aparecem na biblioteca sempre que o aplicativo é aberto."
    )
    assert janela.pasta_row.get_title() == "Pasta"
    assert janela.escolher_pasta_botao.get_label() == "Escolher"
    assert janela.pagina_capas.get_title() == "Capas e logos"
    assert janela.pagina_capas.get_description() == (
        "O SteamGridDB fornece capas e logos para os seus jogos. Para usá-lo, informe "
        "uma chave da API."
    )
    assert janela.chave_sgdb_row.get_title() == "Chave da API"
    assert janela.capas_animadas_switch.get_title() == "Capas animadas"
    assert janela.pagina_conquistas.get_title() == "Conquistas"
    assert janela.pagina_conquistas.get_description() == (
        "Entre com as contas das lojas para acompanhar as conquistas dos seus jogos."
    )
    assert janela.chave_steam_row.get_title() == "Chave da API"
    assert janela.pagina_iluminacao.get_title() == "Iluminação inteligente"
    assert janela.pagina_iluminacao.get_description() == (
        "O Cartridges pode mudar a cor dos seus dispositivos de iluminação compatíveis "
        "com a Tuya de acordo com o jogo em execução."
    )
    assert janela.configurar_iluminacao_botao.get_label() == "Configurar"
    assert janela.pagina_controle.get_title() == "Controle"
    assert janela.big_picture_switch.get_title() == (
        "Abrir o Big Picture ao conectar um controle"
    )
    assert janela.pagina_monitores.get_title() == "Outros monitores"
    assert janela.mover_switch.get_title() == (
        "Mover o aplicativo para outro monitor ao iniciar um jogo"
    )
    assert janela.monitor_row.get_title() == "Monitor"
    assert janela.identificar_row.get_title() == "Identificar monitores"
    assert janela.papel_de_parede_switch.get_title() == (
        "Trocar o papel de parede dos outros monitores"
    )
    assert janela.pagina_pronto.get_title() == "Tudo pronto"
    assert janela.pagina_pronto.get_description() == (
        "Você pode alterar estas opções a qualquer momento em Preferências."
    )
    assert janela.abrir_biblioteca_botao.get_label() == "Abrir a biblioteca"


def test_campos_nascem_com_o_que_ja_esta_gravado(schema):
    schema.set_string("sgdb-key", "k")
    schema.set_boolean("sgdb-animated", True)
    schema.set_string("conquistas-chave-steam", "s")
    schema.set_boolean("big-picture-ao-conectar", True)
    janela, _, _ = _janela()
    assert janela.chave_sgdb_row.get_text() == "k"
    assert janela.capas_animadas_switch.get_active() and janela.capas_animadas_switch.get_visible()
    assert janela.chave_steam_row.get_text() == "s"
    assert janela.big_picture_switch.get_active()


def test_interruptores_gravam(schema, monkeypatch):
    from cartridges.utils import window_geometry

    monkeypatch.setattr(window_geometry, "monitores_da_sessao", lambda: ["m"])
    monkeypatch.setattr(window_geometry, "preencher_escolha_de_monitor", lambda *_: None)
    janela, _, _ = _janela()
    janela.big_picture_switch.set_active(True)
    janela.mover_switch.set_active(True)
    janela.papel_de_parede_switch.set_active(True)
    assert schema.get_boolean("big-picture-ao-conectar")
    assert schema.get_boolean("session-move-window")
    assert schema.get_boolean("session-wallpaper")


def test_sem_segundo_monitor_a_tela_some():
    janela, _, _ = _janela()
    assert janela.pagina_monitores not in janela.paginas()


def test_sem_3d_a_tela_do_controle_some(monkeypatch):
    from cartridges import big_picture

    monkeypatch.setattr(big_picture, "tem_3d", lambda _j: False)
    janela, _, _ = _janela()
    janela.realize()
    assert janela.pagina_controle not in janela.paginas()


def test_iluminacao_configurada_liga_o_recurso(monkeypatch, schema):
    from cartridges.utils import session_fita

    monkeypatch.setattr(session_fita, "fitas", lambda: ["dispositivo"])
    janela, _, _ = _janela()
    janela.ao_fechar_iluminacao()
    assert schema.get_boolean("session-fita") is True


def test_iluminacao_sem_dispositivos_nao_liga(monkeypatch, schema):
    from cartridges.utils import session_fita

    monkeypatch.setattr(session_fita, "fitas", lambda: [])
    schema.set_boolean("session-fita", False)
    janela, _, _ = _janela()
    janela.ao_fechar_iluminacao()
    assert schema.get_boolean("session-fita") is False


def test_fechar_no_x_cancela_logins_e_nao_marca(monkeypatch, schema):
    janela, terminou, _ = _janela()
    fechados = []
    monkeypatch.setattr(janela.grupo_das_contas, "fechar", lambda: fechados.append(1))
    assert janela.emit("close-request") is False
    assert fechados == [1] and terminou == []
    assert not schema.get_boolean("assistente-concluido")


@pytest.fixture
def sincrono(monkeypatch):
    from cartridges import assistente

    monkeypatch.setattr(assistente, "_em_thread", lambda tarefa: tarefa())
    monkeypatch.setattr(
        assistente, "entregar_na_tela", lambda funcao, *args: funcao(*args)
    )
    dialogos = []
    monkeypatch.setattr(
        assistente,
        "create_dialog",
        lambda _pai, titulo, texto, *a, **k: dialogos.append((titulo, texto)),
    )
    return dialogos


def test_backup_valido_marca_e_restaura(monkeypatch, schema, tmp_path, sincrono):
    from cartridges import assistente

    agendados = []
    monkeypatch.setattr(assistente.backup, "validar", lambda caminho: {})
    monkeypatch.setattr(assistente.backup, "agendar", agendados.append)
    janela, _, restaurou = _janela()
    janela.restaurar_backup(tmp_path / "b.zip")
    assert agendados == [tmp_path / "b.zip"] and restaurou == [1]
    assert schema.get_boolean("assistente-concluido") is True and sincrono == []


def test_backup_invalido_avisa_e_continua(monkeypatch, schema, tmp_path, sincrono):
    from cartridges import assistente

    def invalido(_caminho):
        raise assistente.backup.BackupInvalido()
    monkeypatch.setattr(assistente.backup, "validar", invalido)
    janela, _, restaurou = _janela()
    janela.restaurar_backup(tmp_path / "x.zip")
    assert sincrono == [
        ("Backup inválido", "O arquivo não é um backup válido do Cartridges.")
    ]
    assert restaurou == [] and schema.get_boolean("assistente-concluido") is False


def test_chave_steam_grava_sem_espacos(schema):
    janela, _, _ = _janela()
    janela.chave_steam_row.set_text("  abc  ")
    assert schema.get_string("conquistas-chave-steam") == "abc"


def test_backup_com_falha_generica_avisa_e_continua(
    monkeypatch, schema, tmp_path, sincrono
):
    from cartridges import assistente

    def falha(_caminho):
        raise OSError("disco cheio")

    monkeypatch.setattr(assistente.backup, "validar", lambda caminho: {})
    monkeypatch.setattr(assistente.backup, "agendar", falha)
    janela, _, restaurou = _janela()
    janela.restaurar_backup(tmp_path / "x.zip")
    assert sincrono == [
        (
            "Não foi possível restaurar",
            "Não foi possível restaurar o backup. Tente novamente.",
        )
    ]
    assert restaurou == [] and schema.get_boolean("assistente-concluido") is False
    assert janela.restaurar_botao.get_sensitive()


def test_restaurar_bloqueia_a_tela_ate_terminar(monkeypatch, tmp_path):
    from cartridges import assistente

    pendentes = []
    monkeypatch.setattr(assistente, "_em_thread", pendentes.append)
    monkeypatch.setattr(assistente, "entregar_na_tela", lambda f, *a: f(*a))
    monkeypatch.setattr(assistente, "create_dialog", lambda *a, **k: None)

    def invalido(_caminho):
        raise assistente.backup.BackupInvalido()

    monkeypatch.setattr(assistente.backup, "validar", invalido)
    janela, _, _ = _janela()
    janela.restaurar_backup(tmp_path / "x.zip")
    botoes = (
        janela.comecar_botao,
        janela.restaurar_botao,
        janela.pular_configuracao_botao,
    )
    assert len(pendentes) == 1
    assert not any(b.get_sensitive() for b in botoes)
    # O X também fica sem efeito nesses segundos: o aviso pede para aguardar.
    assert janela._toast_restauracao.get_title() == "Preparando a restauração. Aguarde…"
    pendentes[0]()
    assert all(b.get_sensitive() for b in botoes)


def test_fechar_no_x_espera_a_preparacao_da_restauracao(monkeypatch, tmp_path):
    from cartridges import assistente

    pendentes = []
    monkeypatch.setattr(assistente, "_em_thread", pendentes.append)
    monkeypatch.setattr(assistente, "entregar_na_tela", lambda f, *a: f(*a))
    monkeypatch.setattr(assistente, "create_dialog", lambda *a, **k: None)

    def invalido(_caminho):
        raise assistente.backup.BackupInvalido()

    monkeypatch.setattr(assistente.backup, "validar", invalido)
    janela, _, _ = _janela()
    fechados = []
    monkeypatch.setattr(janela.grupo_das_contas, "fechar", lambda: fechados.append(1))
    janela.restaurar_backup(tmp_path / "x.zip")
    assert janela.emit("close-request") is True and fechados == []
    pendentes[0]()
    assert janela.emit("close-request") is False and fechados == [1]


def test_foco_do_teclado_fica_na_pagina_atual(schema):
    from gi.repository import Gtk

    janela, *_ = _janela()
    janela.present()

    def paginas_alcancadas():
        janela.set_focus(None)
        vistos = set()
        for _passo in range(40):
            if not janela.child_focus(Gtk.DirectionType.TAB_FORWARD):
                break
            foco = janela.get_focus()
            while foco is not None and foco.get_parent() is not janela.carrossel:
                foco = foco.get_parent()
            if foco is not None:
                vistos.add(foco)
        return vistos

    assert paginas_alcancadas() <= {janela.pagina_boas_vindas}
    janela.avancar()
    assert paginas_alcancadas() <= {janela.pagina_jogos}


def test_concluir_cancela_logins(monkeypatch):
    janela, _, _ = _janela()
    fechados = []
    monkeypatch.setattr(janela.grupo_das_contas, "fechar", lambda: fechados.append(1))
    janela.concluir()
    assert fechados == [1]


def test_grupo_das_contas_no_assistente_nao_repete_o_texto_da_pagina(schema):
    # A página já explica as contas; o grupo, aqui, só mostra as linhas.
    janela, *_ = _janela()
    assert janela.grupo_das_contas.get_title() == ""
    assert janela.grupo_das_contas.get_description() == ""


def test_icone_da_iluminacao_e_de_luz(schema):
    janela, *_ = _janela()
    assert janela.pagina_iluminacao.get_icon_name() == "display-brightness-symbolic"


def test_paginas_ocupam_a_largura_do_carrossel(schema):
    janela, *_ = _janela()
    # Pelos atributos: pagina_controle e pagina_monitores podem sair do carrossel.
    for nome in (
        "pagina_boas_vindas",
        "pagina_jogos",
        "pagina_capas",
        "pagina_conquistas",
        "pagina_iluminacao",
        "pagina_controle",
        "pagina_monitores",
        "pagina_pronto",
    ):
        assert getattr(janela, nome).get_hexpand(), nome


def test_pagina_das_conquistas_rola_ate_a_chave_da_steam(schema):
    # Em 640 px a página não cabe: a rolagem interna do StatusPage tem de existir
    # e chegar à chave da Steam Web API.
    from gi.repository import Gtk

    janela, *_ = _janela()
    janela.present()

    def rolagem(widget):
        filho = widget.get_first_child()
        while filho:
            if isinstance(filho, Gtk.ScrolledWindow):
                return filho
            achado = rolagem(filho)
            if achado:
                return achado
            filho = filho.get_next_sibling()

    try:
        # Pelo caminho real: a partir da terceira tela o rodapé aparece e tira
        # altura da página.
        _ir_para_pagina(janela, janela.pagina_conquistas)
        _bombear(0.5)
        assert janela.get_height() == 640
        area = rolagem(janela.pagina_conquistas)
        ajuste = area.get_vadjustment()
        assert ajuste.get_upper() > ajuste.get_page_size()
        ajuste.set_value(ajuste.get_upper() - ajuste.get_page_size())
        _bombear(0.5)
        ok, caixa = janela.chave_steam_row.compute_bounds(area)
        assert ok
        assert caixa.get_y() >= 0
        assert caixa.get_y() + caixa.get_height() <= area.get_height()
    finally:
        janela.destroy()


def _bombear(tempo=0.3):
    import time

    from gi.repository import GLib

    contexto = GLib.MainContext.default()
    limite = time.monotonic() + tempo
    while time.monotonic() < limite:
        while contexto.pending():
            contexto.iteration(False)


def _ir_para_pagina(janela, pagina):
    for _ in range(len(janela.paginas())):
        if janela.paginas()[janela._indice] is pagina:
            return
        janela.avancar()
    assert janela.paginas()[janela._indice] is pagina, "a página não apareceu no assistente"


# Tela 0: o logo do app
def test_boas_vindas_mostra_o_logo_do_app(schema):
    janela, *_ = _janela()
    assert janela.pagina_boas_vindas.get_icon_name() == "io.github.joaomgabaldi.Cartridges"


# Tela 1: Continuar só com a pasta escolhida
def test_continuar_da_tela_dos_jogos_espera_a_pasta(schema, tmp_path):
    janela, *_ = _janela()
    janela.avancar()
    assert janela.paginas()[janela._indice] is janela.pagina_jogos
    assert not janela.continuar_botao.get_sensitive()
    assert janela.pular_botao.get_sensitive()
    janela.gravar_pasta(tmp_path)
    assert janela.continuar_botao.get_sensitive()
    janela.avancar()
    assert janela.continuar_botao.get_sensitive()


def test_continuar_da_tela_dos_jogos_com_pasta_ja_gravada(schema, tmp_path):
    schema.set_string("shortcuts-location", str(tmp_path))
    janela, *_ = _janela()
    janela.avancar()
    assert janela.continuar_botao.get_sensitive()


def test_continuar_volta_a_ficar_ativo_nas_outras_telas(schema):
    janela, *_ = _janela()
    janela.avancar()
    assert not janela.continuar_botao.get_sensitive()
    janela.avancar()  # Pular: segue sem pasta
    assert janela.continuar_botao.get_sensitive()
    janela.voltar()
    assert not janela.continuar_botao.get_sensitive()


# Tela 2: a animação da capa
def test_tela_das_capas_tem_o_palco_com_as_duas_imagens(schema):
    janela, *_ = _janela()
    assert janela.capa_de_exemplo.get_parent() is janela.palco_das_capas
    assert janela.capa_vazia.get_parent() is janela.palco_das_capas
    assert janela.pagina_capas.get_icon_name() in (None, "")


def test_animacao_das_capas_so_roda_com_a_tela_visivel(schema):
    from gi.repository import Adw

    janela, *_ = _janela()
    janela.present()
    try:
        animacao = janela._animacao_das_capas
        assert animacao.get_state() != Adw.AnimationState.PLAYING
        _ir_para_pagina(janela, janela.pagina_capas)
        _bombear()
        assert animacao.get_state() == Adw.AnimationState.PLAYING
        janela.avancar()
        assert animacao.get_state() != Adw.AnimationState.PLAYING
        janela.voltar()
        _bombear()
        assert animacao.get_state() == Adw.AnimationState.PLAYING
    finally:
        janela.destroy()
    assert animacao.get_state() != Adw.AnimationState.PLAYING


def test_sem_animacoes_do_sistema_a_capa_fica_parada(schema, monkeypatch):
    from gi.repository import Adw

    from cartridges import assistente

    monkeypatch.setattr(assistente, "_animacoes_ligadas", lambda: False)
    janela, *_ = _janela()
    janela.present()
    try:
        _ir_para_pagina(janela, janela.pagina_capas)
        _bombear()
        assert janela._animacao_das_capas.get_state() != Adw.AnimationState.PLAYING
        assert janela.capa_de_exemplo.get_opacity() == 1
        assert janela.capa_vazia.get_opacity() == 0
    finally:
        janela.destroy()


def test_quadros_da_animacao_das_capas(schema):
    from cartridges import assistente

    janela, *_ = _janela()
    palco = janela.palco_das_capas
    janela._quadro_das_capas(0)  # placeholder parado no centro
    assert palco.deslocamento == 0
    assert janela.capa_vazia.get_opacity() == 1 and janela.capa_de_exemplo.get_opacity() == 1
    janela._quadro_das_capas(2000)  # a capa sozinha
    assert janela.capa_vazia.get_opacity() == 0 and janela.capa_de_exemplo.get_opacity() == 1
    assert palco.deslocamento == -assistente._DESLOCAMENTO
    janela._quadro_das_capas(3850)  # a capa some
    assert janela.capa_de_exemplo.get_opacity() < 1
    janela._quadro_das_capas(4200)  # o placeholder volta ao centro
    assert 0 < janela.capa_vazia.get_opacity() < 1
    janela._quadro_das_capas(assistente._CICLO)  # emenda do loop: igual ao quadro 0
    assert janela.capa_vazia.get_opacity() == 1 and janela.capa_de_exemplo.get_opacity() == 0
    assert palco.deslocamento == 0


# Tela 2/3: chaves de API
def test_chave_do_steamgriddb_tem_o_link_das_preferencias(schema):
    janela, *_ = _janela()
    assert not hasattr(janela, "obter_chave_botao")
    assert janela.chave_sgdb_grupo.get_description() == (
        "É necessária uma chave da API para usar o SteamGridDB. "
        '<a href="https://www.steamgriddb.com/profile/preferences/api">Obtenha aqui</a>.'
    )


# Tela 3: o cartão de conquista
def test_tela_das_conquistas_mostra_o_cartao_real(schema, monkeypatch):
    from cartridges import conquista_aviso

    recursos = []
    real = conquista_aviso.montar_cartao
    monkeypatch.setattr(
        conquista_aviso,
        "montar_cartao",
        lambda aviso, recurso="": recursos.append(recurso) or real(aviso, recurso),
    )
    janela, *_ = _janela()
    assert recursos == ["/io/github/joaomgabaldi/Cartridges/conquista_de_exemplo.svg"]
    assert janela.pagina_conquistas.get_icon_name() in (None, "")
    assert janela.cartao_de_conquista.has_css_class("conquista-aviso-cartao")
    textos = []

    def coletar(widget):
        filho = widget.get_first_child()
        while filho:
            if hasattr(filho, "get_label"):
                textos.append(filho.get_label())
            coletar(filho)
            filho = filho.get_next_sibling()

    coletar(janela.cartao_de_conquista)
    assert textos == [
        "Conquista desbloqueada · ★ Rara, 2,3%",
        "Lenda das ruas",
        "Vença todas as corridas em primeiro lugar.",
    ]


# O rodapé não é alça de arrastar a janela
def test_rodape_nao_fica_numa_barra_da_janela(schema):
    from gi.repository import Adw

    janela, *_ = _janela()
    pai = janela.rodape.get_parent()
    while pai is not None and not isinstance(pai, Adw.ToolbarView):
        pai = pai.get_parent()
    # Dentro do ToolbarView, mas como conteúdo, não como barra de baixo.
    assert pai is not None and pai.get_content() is janela.rodape.get_parent()
