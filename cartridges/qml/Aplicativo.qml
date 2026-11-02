import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Shapes

// A janela do app: as páginas da biblioteca, os botões da barra e as camadas de aviso e confirmação.
// `paginaTodos`, `paginaZerados`, `filtros`, `aplicativo` e `ponte` vêm do contexto (cartridges/app.py).
Principal {
    id: janela

    // Lido aqui, fora dos Avisos, porque lá o nome da propriedade é o mesmo.
    readonly property QtObject ligacao: ponte
    // O AppUpdater (D82), pelo mesmo motivo; sem ele no contexto (os testes dos outros diálogos) a camada fica sem o diálogo da versão.
    readonly property QtObject servicoDeAtualizacao: typeof atualizador === "undefined" ? null : atualizador
    // O "Sobre o Cartridges" (D84), pelo mesmo motivo; sem ele no contexto o item do menu some e nenhum diálogo existe.
    readonly property QtObject servicoDoSobre: typeof sobre === "undefined" ? null : sobre
    readonly property bool sobreAberto: servicoDoSobre !== null && servicoDoSobre.aberto
    // O "Adicionar a Jogos Zerados" (D85), pelo mesmo motivo; sem ele no contexto o botão "+" some e nenhum modal existe.
    readonly property QtObject servicoDeZerados: typeof zeradosManuais === "undefined" ? null : zeradosManuais
    readonly property bool zeradosAberto: servicoDeZerados !== null && servicoDeZerados.aberto
    // As Novidades (D83), pelo mesmo motivo; sem elas no contexto (os arneses que não as registram) o botão fica oculto.
    readonly property QtObject servicoDeNovidades: typeof novidades === "undefined" ? null : novidades
    // "todos", "zerados", "novidades" ou "jogo" (a página de detalhes, por cima de uma das duas).
    readonly property string paginaAtual: pilha.depth === 0 ? "todos"
        : (pilha.currentItem && pilha.currentItem.objectName === "paginaDoJogo" ? "jogo"
        : (pilha.currentItem && pilha.currentItem.objectName === "paginaDasNovidades" ? "novidades" : "zerados"))

    // Abre a página de detalhes do jogo; o foco inicial é dela (StackView.onActivated).
    function abrirDetalhes(jogoId) { abrirDetalhesDe(jogoId, false) }
    function abrirDetalhesDe(jogoId, anotar) {
        if (paginaAtual === "jogo") return
        if (detalhes.mostrar(jogoId)) empurrar(paginaDoJogo, { anotarAoEntrar: anotar })
    }
    // Fecha a página de detalhes, ou sai de Jogos Zerados; o foco volta ao cartão de onde se saiu.
    function voltar() {
        if (paginaAtual === "jogo") detalhes.esquecer()
        if (paginaAtual === "jogo" && pilha.depth > 1) pilha.pop()
        else if (paginaAtual !== "todos") sairDaPilha()
    }

    // O `StackView` não anima o primeiro `push` numa pilha vazia nem o `clear` que a esvazia (a página de baixo, "Todos os
    // jogos", fica fora dela): o deslize e a sombra da transição dessas duas passagens são feitos aqui, à mão.
    property bool _saindoDaPilha: false
    function empurrar(componente, propriedades) {
        const vazia = pilha.depth === 0
        pilha.push(componente, propriedades || {})
        if (vazia && Tema.animacoes && pilha.currentItem) {
            deslizeDaPagina.target = pilha.currentItem
            deslizeDaPagina.from = pilha.width
            deslizeDaPagina.to = 0
            avancoDaPilha.from = 0
            avancoDaPilha.to = 1
            deslizeDaPagina.restart()
            avancoDaPilha.restart()
        }
    }
    function sairDaPilha() {
        if (!Tema.animacoes || pilha.depth !== 1 || !pilha.currentItem) {
            pilha.clear(StackView.PopTransition)
            return
        }
        if (_saindoDaPilha) return
        _saindoDaPilha = true
        deslizeDaPagina.target = pilha.currentItem
        deslizeDaPagina.from = 0
        deslizeDaPagina.to = pilha.width
        avancoDaPilha.from = 1
        avancoDaPilha.to = 0
        deslizeDaPagina.restart()
        avancoDaPilha.restart()
    }
    NumberAnimation {
        id: deslizeDaPagina
        property: "x"
        duration: 400
        easing.type: Easing.OutCubic
        onFinished: if (janela._saindoDaPilha) { janela._saindoDaPilha = false; pilha.clear(StackView.Immediate) }
    }
    NumberAnimation { id: avancoDaPilha; target: pilha; property: "avanco"; duration: 400; easing.type: Easing.OutCubic }

    // O `y` de um menu aberto por um botão da barra: abaixo dos 47 px dela, fora da área de arrasto do QWindowKit.
    function baseDaBarra(botao) { return botao.height + (alturaDaBarra - botao.height) / 2 }

    telaCheia: bigPicture.visivel || sessao.emAndamento
    // Com um diálogo na frente, a barra de título não arrasta nem aciona nada (J05).
    barraTrancada: modalAberto

    tituloDaBarra: paginaAtual === "todos" ? "Todos os jogos" : paginaAtual === "zerados" ? "Jogos Zerados"
        : paginaAtual === "novidades" ? "Novidades" : detalhes.nome

    // Depois do setup do QWindowKit (Principal.qml), que roda no onCompleted da base.
    Component.onCompleted: visible = true

    // A linha de baixo da barra aparece com o conteúdo da página rolado (`undershoot-top` da `ToolbarView`).
    sombraDaBarra: !!paginaDoControle && paginaDoControle.rolado === true

    // O `key-capture-widget` da `main` é a página inteira: digitar com o foco num botão da barra abre a busca, e Esc
    // volta de Jogos Zerados. Quem decide é a página à vista (`capturar`).
    function capturarNaPagina(event) {
        if (paginaDoControle && typeof paginaDoControle.capturar === "function" && paginaDoControle.capturar(event))
            event.accepted = true
    }
    component BotaoDoApp: BotaoDaBarra {
        Keys.onPressed: event => janela.capturarNaPagina(event)
    }

    // `AdwNavigationView`: Alt+←, a tecla Voltar do teclado e o botão Voltar do mouse voltam uma página (a `main` não
    // desliga). Sem diálogo na frente e fora do Big Picture e da sessão.
    readonly property bool podeVoltarPorAtalho: paginaAtual !== "todos" && !modalAberto && !bigPicture.visivel
        && !sessao.emAndamento
    Shortcut {
        sequences: ["Alt+Left", "Back"]
        enabled: janela.podeVoltarPorAtalho
        onActivated: janela.voltar()
    }
    TapHandler {
        acceptedButtons: Qt.BackButton
        enabled: janela.podeVoltarPorAtalho
        onTapped: janela.voltar()
    }

    inicio: [
        BotaoDoApp {
            id: botaoAdicionar
            objectName: "botaoAdicionar"
            visible: janela.paginaAtual === "todos"
            icone: "list-add"
            dica: "Adicionar jogo"
            onClicked: menuDeAdicionar.open()
            menuAberto: menuDeAdicionar.opened
            MenuDoTema {
                id: menuDeAdicionar
                objectName: "menuDeAdicionar"
                y: janela.baseDaBarra(parent)
                // A seta aponta o centro do botão (34 de largura), com o menu alinhado à esquerda dele.
                setaEm: parent.width / 2
                ItemDoMenu { objectName: "itemAdicionarJogo"; text: "Adicionar jogo"; enabled: !aplicativo.importando; onTriggered: edicao.adicionar() }
                SeparadorDoMenu {}
                ItemDoMenu { text: "Importar"; enabled: !aplicativo.importando; onTriggered: aplicativo.importar() }
            }
        },
        BotaoDoApp {
            id: botaoVoltar
            objectName: "botaoVoltar"
            visible: janela.paginaAtual !== "todos"
            icone: "go-previous"
            dica: "Voltar"
            onClicked: janela.voltar()
        },
        BotaoDoApp {
            id: botaoAdicionarZerado
            objectName: "botaoAdicionarZerado"
            visible: janela.paginaAtual === "zerados" && janela.servicoDeZerados !== null
            icone: "list-add"
            dica: "Adicionar a Jogos Zerados"
            onClicked: janela.servicoDeZerados.abrir()
        }
    ]

    // Da direita para a esquerda: menu principal, "Atualizar" (só nas Novidades), Jogos Zerados, Novidades, Big Picture e busca.
    fim: [
        BotaoDoApp {
            id: botaoMenu
            objectName: "botaoMenu"
            visible: janela.paginaAtual === "todos" || janela.paginaAtual === "zerados"
            icone: "open-menu"
            dica: "Menu principal"
            onClicked: menuPrincipal.open()
            menuAberto: menuPrincipal.opened
            MenuPrincipal {
                id: menuPrincipal
                objectName: "menuPrincipal"
                servicoDoSobre: janela.servicoDoSobre
                y: janela.baseDaBarra(parent)
                x: parent.width - width
                setaEm: width - parent.width / 2
            }
        },
        BotaoDoApp {
            id: botaoAtualizar
            objectName: "botaoAtualizarNovidades"
            visible: janela.paginaAtual === "novidades"
            icone: "view-refresh"
            dica: "Atualizar"
            onClicked: janela.servicoDeNovidades.atualizar()
        },
        BotaoDoApp {
            id: botaoZerados
            objectName: "botaoZerados"
            visible: janela.paginaAtual === "todos"
            icone: "trofeu"
            dica: "Jogos Zerados"
            onClicked: janela.empurrar(zerados)
        },
        BotaoDoApp {
            id: botaoNovidades
            objectName: "botaoNovidades"
            visible: janela.paginaAtual === "todos" && janela.servicoDeNovidades !== null && janela.servicoDeNovidades.visivel
            icone: "novidades"
            tamanhoDoIcone: 20  // window.blp: pixel-size 20
            selo: janela.servicoDeNovidades !== null && janela.servicoDeNovidades.naoVistas
            dica: "Novidades"
            onClicked: { janela.servicoDeNovidades.abrir(); janela.empurrar(paginaDasNovidades) }
        },
        BotaoDoApp {
            id: botaoBigPicture
            indisponivel: !bigPicture.disponivel
            objectName: "botaoBigPicture"
            visible: janela.paginaAtual === "todos"
            icone: "video-display"
            dica: bigPicture.disponivel ? "Big Picture" : "Requer uma placa de vídeo com aceleração 3D."
            onClicked: bigPicture.entrar()
        },
        BotaoDoApp {
            id: botaoBusca
            objectName: "botaoBusca"
            visible: janela.paginaAtual === "todos"
            icone: "system-search"
            dica: "Buscar"
            checkable: true
            checked: todos.buscaAberta
            onClicked: todos.alternarBusca()
        }
    ]

    // O foco do teclado acompanha a página que está na tela.
    onPaginaAtualChanged: if (paginaAtual === "todos") todos.focarGrade()

    PaginaDaBiblioteca {
        id: todos
        objectName: "pagina"
        anchors { fill: parent; topMargin: janela.alturaDoTopo }
        pagina: paginaTodos
        comBusca: true
        ativa: pilha.depth === 0 && !bigPicture.visivel && !sessao.emAndamento
        // Com o diálogo de edição, o Big Picture ou a sessão à frente, nada de trás recebe o mouse nem o Tab.
        enabled: !camadaDeAvisos.dialogoAberto && !edicao.aberto && !historico.aberto && !conquistasDoJogo.aberto && !preferencias.aberto && !saves.aberto && !restauracao.aberta && !janela.sobreAberto && !janela.zeradosAberto && !bigPicture.visivel && !sessao.emAndamento
        onAbrirDetalhes: id => janela.abrirDetalhes(id)
        onEditar: id => edicao.abrir(id)
    }

    // Vazia, a pilha mostra "Todos os jogos"; "Jogos Zerados" entra por cima.
    StackView {
        id: pilha
        objectName: "pilha"
        anchors { fill: parent; topMargin: janela.alturaDoTopo }
        visible: depth > 0
        // `AdwNavigationView`: a página nova desliza da direita e a de baixo recua um quarto da largura; ao voltar,
        // o contrário. shortcut: duração e recuo não medidos na libadwaita (400 ms, 1/4); conferir na rodada visual.
        // O `avanco` (0 a 1) leva o escurecimento e a sombra da página de baixo, logo abaixo.
        property real avanco: 0
        pushEnter: Transition { ParallelAnimation {
            XAnimator { from: pilha.width; to: 0; duration: Tema.animacoes ? 400 : 0; easing.type: Easing.OutCubic }
            NumberAnimation { target: pilha; property: "avanco"; from: 0; to: 1; duration: Tema.animacoes ? 400 : 0; easing.type: Easing.OutCubic }
        } }
        pushExit: Transition { XAnimator { from: 0; to: -pilha.width / 4; duration: Tema.animacoes ? 400 : 0; easing.type: Easing.OutCubic } }
        popEnter: Transition { XAnimator { from: -pilha.width / 4; to: 0; duration: Tema.animacoes ? 400 : 0; easing.type: Easing.OutCubic } }
        popExit: Transition { ParallelAnimation {
            XAnimator { from: 0; to: pilha.width; duration: Tema.animacoes ? 400 : 0; easing.type: Easing.OutCubic }
            NumberAnimation { target: pilha; property: "avanco"; from: 1; to: 0; duration: Tema.animacoes ? 400 : 0; easing.type: Easing.OutCubic }
        } }
        enabled: !camadaDeAvisos.dialogoAberto && !edicao.aberto && !historico.aberto && !conquistasDoJogo.aberto && !preferencias.aberto && !saves.aberto && !restauracao.aberta && !janela.sobreAberto && !janela.zeradosAberto && !bigPicture.visivel && !sessao.emAndamento
    }

    // `AdwNavigationView`: a página de baixo escurece e a que entra projeta uma sombra na borda esquerda. Não medidos:
    // 20% de escurecimento e 32 px de sombra, na libadwaita.
    Item {
        objectName: "sombraDaTransicao"
        anchors { fill: parent; topMargin: janela.alturaDoTopo }
        visible: pilha.avanco > 0 && pilha.avanco < 1
        enabled: false
        readonly property real borda: pilha.width * (1 - pilha.avanco)
        Rectangle { x: 0; width: parent.borda; height: parent.height; color: Qt.rgba(0, 0, 6 / 255, 0.2 * pilha.avanco) }
        Rectangle {
            x: parent.borda - width
            width: 32
            height: parent.height
            gradient: Gradient {
                orientation: Gradient.Horizontal
                GradientStop { position: 0; color: "transparent" }
                GradientStop { position: 1; color: Qt.rgba(0, 0, 6 / 255, 0.25 * pilha.avanco) }
            }
        }
    }

    Component {
        id: zerados
        PaginaDaBiblioteca {
            objectName: "paginaDeZerados"
            pagina: paginaZerados
            // Coberta pelos detalhes, ela não anima capas.
            ativa: StackView.status !== StackView.Inactive && !bigPicture.visivel && !sessao.emAndamento
            onAbrirDetalhes: id => janela.abrirDetalhes(id)
            onEditar: id => edicao.abrir(id)
            onVoltar: janela.voltar()
            StackView.onActivated: focarGrade()
            // O fundo cobre "Todos os jogos" durante a transição.
            Rectangle { anchors.fill: parent; color: Tema.fundo; z: -1 }
        }
    }

    Component {
        id: paginaDasNovidades
        PaginaDasNovidades {
            objectName: "paginaDasNovidades"
            onVoltar: janela.voltar()
        }
    }

    Component {
        id: paginaDoJogo
        PaginaDoJogo {
            objectName: "paginaDoJogo"
            placeholder: paginaTodos.placeholder
            onVoltar: janela.voltar()
            onJogar: detalhes.jogar()
            onEditar: edicao.abrir(detalhes.jogoId)
            onRemover: detalhes.remover()
            onExcluir: detalhes.excluir()
            onAtualizacaoConfirmada: detalhes.confirmarAtualizacao()
            onAbrirHistorico: historico.abrir(detalhes.jogoId)
        }
    }

    // O jogo mostrado foi excluído, removido ou saiu dos Jogos Zerados: a página fecha.
    Connections {
        target: detalhes
        function onSair() { if (janela.paginaAtual === "jogo") janela.voltar() }
    }

    // O botão das tarefas em andamento: sobre as páginas e abaixo de todo diálogo (que vêm depois, na ordem).
    BotaoDasTarefas {
        id: botaoDasTarefas
        anchors.fill: parent
        pagina: janela.paginaAtual
        modalAberto: janela.modalAberto
        emBigPicture: bigPicture.visivel
        emSessao: sessao.emAndamento
    }

    // A janela "Tarefas em andamento": própria, fora desta, posta acima do botão.
    Loader {
        objectName: "carregadorDasTarefas"
        active: painelDasTarefas.aberta
        sourceComponent: Component { JanelaDasTarefas { alvo: botaoDasTarefas.alvo; semAgente: janela.semAgente } }
    }

    // O aviso embaixo (`ToastOverlay` da `main`): sobre as páginas e abaixo de todo diálogo. As Preferências têm o delas.
    Item {
        id: baseDoAviso
        anchors.fill: parent
    }

    // Abaixo da camada de avisos: o erro de uma validação aparece na frente do diálogo.
    DialogoDeEdicao {
        id: dialogoDeEdicao
        // Fechado a partir de um menu, o foco não tem para onde voltar: vai à página à vista.
        onRetornoPerdido: janela.paginaDoControle.focarGrade()
    }

    // O histórico de sessões, aberto pelo tempo de jogo da página de detalhes; abaixo da camada da sessão.
    DialogoDoHistorico {
        id: dialogoDoHistorico
    }

    // A lista de conquistas, aberta pelo cartão da página de detalhes; abaixo da camada da sessão.
    DialogoDeConquistas {
        id: dialogoDeConquistas
    }

    // As Preferências: por cima da edição (o erro do SteamGridDB a deixa aberta) e abaixo da camada da sessão.
    DialogoDePreferencias {
        id: dialogoDePreferencias
        avisoAberto: camadaDeAvisos.dialogoAberto
        // Fechado a partir de um menu, o foco não tem para onde voltar: vai ao editor, se aberto, ou à página à vista.
        onRetornoPerdido: edicao.aberto ? dialogoDeEdicao.devolverFoco() : janela.paginaDoControle.focarGrade()
    }

    // As versões guardadas dos saves, abertas pelo menu do jogo; acima das páginas e abaixo dos avisos.
    DialogoDeVersoes {
        id: dialogoDeVersoes
        // Aberto pelo menu do jogo, que já fechou: o foco vai à página à vista.
        onRetornoPerdido: janela.paginaDoControle.focarGrade()
    }

    // O "Sobre o Cartridges" (D84), aberto pelo menu principal; acima das páginas e abaixo dos avisos.
    DialogoSobre {
        id: dialogoSobre
        modelo: janela.servicoDoSobre
        // Aberto pelo menu principal, que já fechou: o foco vai à página à vista.
        onRetornoPerdido: janela.paginaDoControle.focarGrade()
    }

    // O "Adicionar a Jogos Zerados" (D85), aberto pelo "+" da página; acima das páginas e abaixo dos avisos.
    SeletorDeZerados {
        id: seletorDeZerados
        modelo: janela.servicoDeZerados
        // Aberto pelo botão da barra, que ficou desabilitado: o foco vai à página à vista.
        onRetornoPerdido: janela.paginaDoControle.focarGrade()
    }

    // A continuação da restauração de um backup (D81): acima das páginas e abaixo dos avisos. A pasta de atalhos
    // vem primeiro e os outros três se empilham sobre a lista dos jogos sem atalho, na ordem em que se abrem.
    DialogoDaPastaDeAtalhos {
        id: dialogoDaPasta
    }
    JanelaDosPendentes {
        id: janelaDosPendentes
        // A lista de trás só volta a ouvir quando a escolha e o conflito saem.
        enabled: !restauracao.escolhaAberta && !restauracao.conflitoAberto
        onRetornoPerdido: janela.paginaDoControle.focarGrade()
    }
    EscolhaDoAtalho {
        id: escolhaDoAtalho
        // A lista foi relida e quem abriu sumiu: o foco vai ao "Lembrar mais tarde", ou à página à vista.
        onRetornoPerdido: restauracao.pendentesAbertos ? janelaDosPendentes.focarInicial() : janela.paginaDoControle.focarGrade()
    }
    DadosDoJogo {
        id: dadosDoJogo
        onRetornoPerdido: restauracao.pendentesAbertos ? janelaDosPendentes.focarInicial() : janela.paginaDoControle.focarGrade()
    }

    // Por cima do diálogo de edição, que os abre; o foco volta ao botão que abriu cada um.
    SeletorDeImagens {
        id: seletorDeCapa
        objectName: "seletorDeCapa"
        seletor: edicao.seletorDeCapa
        titulo: "Escolher capa"
        rotuloDoAtalho: "Animadas"
        dicaDoAtalho: "Mostrar capas animadas"
        atalhoAlterna: true
        onAtalhoClicado: seletor.animadas = !seletor.animadas
        onRetornoPerdido: dialogoDeEdicao.devolverFoco()
    }
    SeletorDeImagens {
        id: seletorDeLogo
        objectName: "seletorDeLogo"
        seletor: edicao.seletorDeLogo
        titulo: "Escolher logo"
        rotuloDoAtalho: "Usar o título"
        dicaDoAtalho: "Não usar logo neste jogo"
        horizontal: true
        onAtalhoClicado: seletor.usarTitulo()
        onRetornoPerdido: dialogoDeEdicao.devolverFoco()
    }

    SeletorDePapelDeParede {
        id: seletorDePapel
        objectName: "seletorDePapel"
        seletor: edicao.seletorDePapelDeParede
        onRetornoPerdido: dialogoDeEdicao.devolverFoco()
    }

    SeletorDaSteam {
        id: seletorDaSteam
        objectName: "seletorDaSteam"
        seletor: edicao.seletorDaSteam
        onRetornoPerdido: dialogoDeEdicao.devolverFoco()
    }
    SeletorDoLudusavi {
        id: seletorDoLudusavi
        objectName: "seletorDoLudusavi"
        seletor: edicao.seletorDoLudusavi
        onRetornoPerdido: dialogoDeEdicao.devolverFoco()
    }

    // Acima das páginas e abaixo dos avisos. A entrada e a saída são do `bigPicture` (Python).
    BigPicture {
        id: camadaDoBigPicture
        anchors.fill: parent
        visible: bigPicture.visivel
        animarPasso: bigPicture.animacoes
        sessaoEmAndamento: sessao.emAndamento
        // Com a confirmação do comando na frente a camada não recebe teclas nem toques; ao fechar, retoma o foco.
        enabled: !camadaDeAvisos.dialogoAberto && !sessao.emAndamento
        onVisibleChanged: if (visible) forceActiveFocus()
        onEnabledChanged: if (enabled && visible) forceActiveFocus()
        onAbrir: bigPicture.abrirJogo()
        onSair: bigPicture.sair()
    }

    // De volta à grade, o foco fica no cartão do jogo que estava no centro.
    Connections {
        target: bigPicture
        function onSaiu(jogoId) { todos.focarJogo(jogoId) }
    }

    // Acima do Big Picture e abaixo dos avisos (D49).
    CamadaDaSessao {
        id: camadaDaSessao
        anchors.fill: parent
        visible: sessao.emAndamento
    }

    // Com os saves em andamento, ou com a janela das tarefas aberta e alguma tarefa, a principal só some (D78); o
    // painel repassa o resto à sessão (a manual e o aviso de conquista na tela fecham o app).
    onClosing: (fechar) => fechar.accepted = painelDasTarefas.principalFechando()

    // A janela "Jogando {nome}" da sessão manual: própria, fora desta (D50).
    Loader {
        objectName: "carregadorDaJanelaManual"
        active: sessao.janelaManual
        source: "JanelaDaSessao.qml"
    }

    Avisos {
        id: camadaDeAvisos
        objectName: "camadaDeAvisos"
        onRetornoPerdido: janela.paginaDoControle.focarGrade()
        anchors.fill: parent
        ponte: janela.ligacao
        fila: aplicativo.avisos
        app: aplicativo
        atualizador: janela.servicoDeAtualizacao
        lugarDoAviso: preferencias.aberto ? dialogoDePreferencias : janela.telaCheia ? null : baseDoAviso
    }

    // Atalhos arrastados do Explorer: só com a janela livre de diálogos.
    DropArea {
        id: alvoDeSoltar
        objectName: "alvoDeSoltar"
        anchors.fill: parent
        enabled: !camadaDeAvisos.dialogoAberto && !edicao.aberto && !historico.aberto && !conquistasDoJogo.aberto && !preferencias.aberto && !saves.aberto && !restauracao.aberta && !janela.sobreAberto && !janela.zeradosAberto
        onEntered: (arrasto) => arrasto.accepted = arrasto.hasUrls
        onDropped: (soltou) => {
            if (soltou.hasUrls) aplicativo.soltar(soltou.urls)
        }
    }

    // `.aviso-de-soltar`: a janela a 12% de transparência por cima, com a moldura tracejada no meio.
    Rectangle {
        id: avisoDeSoltar
        objectName: "avisoDeSoltar"
        anchors.fill: parent
        color: Qt.alpha(Tema.fundo, 0.88)
        opacity: alvoDeSoltar.containsDrag ? 1 : 0
        visible: opacity > 0
        Behavior on opacity { NumberAnimation { duration: 150 } }

        // `.moldura-de-soltar`: 420 de largura, padding 44/32, tracejado de 2 px em 45% do texto, raio 16, texto a 80%.
        Item {
            id: moldura
            anchors.centerIn: parent
            width: Math.min(420, avisoDeSoltar.width - 48)
            height: coluna.implicitHeight + 88
            Shape {
                anchors.fill: parent
                ShapePath {
                    strokeColor: Qt.alpha(Tema.texto, Tema.texto.a * 0.45)
                    strokeWidth: 2
                    strokeStyle: ShapePath.DashLine
                    dashPattern: [3, 3]
                    fillColor: "transparent"
                    PathRectangle { x: 1; y: 1; width: moldura.width - 2; height: moldura.height - 2; radius: 15 }
                }
            }
            Column {
                id: coluna
                anchors { centerIn: parent }
                spacing: 14
                Icone {
                    anchors.horizontalCenter: parent.horizontalCenter
                    nome: "folder-download"
                    tamanho: 40
                    cor: Tema.texto
                    opacity: 0.8
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: "Solte aqui para importar"
                    textFormat: Text.PlainText
                    color: Qt.alpha(Tema.texto, Tema.texto.a * 0.8)
                    font { family: Tema.fonte; pixelSize: Tema.titulo3; weight: Tema.pesoTitulo3 }
                }
            }
        }
    }

    // O botão "Anotar" do aviso do fim da sessão abre os detalhes do jogo, já com o balão.
    Connections {
        target: sessao
        function onAnotarPedido(jogoId) {
            // Outro jogo nos detalhes: sai dele antes de abrir o da sessão.
            if (janela.paginaAtual === "jogo" && detalhes.jogoId !== jogoId) janela.voltar()
            if (janela.paginaAtual === "jogo") pilha.currentItem.abrirAnotacao()
            else janela.abrirDetalhesDe(jogoId, true)
        }
    }

    Connections {
        target: janela.ligacao
        function onSairDaFrente() { sessao.minimizar() }
    }

    // --- Controle do Xbox -------------------------------------------------------------------------------
    // A página à vista: "Todos os jogos", "Jogos Zerados" ou a de detalhes.
    readonly property var paginaDoControle: pilha.depth === 0 ? todos : pilha.currentItem
    // Algum diálogo na frente (os menus não contam): o botão das tarefas some.
    readonly property bool modalAberto: camadaDeAvisos.dialogoAberto || edicao.aberto || historico.aberto || conquistasDoJogo.aberto || preferencias.aberto || saves.aberto || restauracao.aberta || sobreAberto || zeradosAberto
        || (paginaDoControle !== null && paginaDoControle.dialogoAberto === true)
    // Menu ou diálogo na frente: o controle navega nele pelas teclas, como o teclado faria.
    readonly property bool popupAberto: menuPrincipal.opened || modalAberto
        || (paginaDoControle !== null && paginaDoControle.menuDoJogoAberto)
    property bool ponteiroEscondido: false
    property point posicaoDoPonteiro

    // Os botões da barra que o controle alcança com ↑ na primeira linha.
    readonly property var botoesDaBarra: [botaoAdicionar, botaoVoltar, botaoAdicionarZerado, botaoZerados, botaoNovidades, botaoAtualizar, botaoBigPicture, botaoBusca, botaoMenu]
    function botaoFocado() {
        for (var i = 0; i < botoesDaBarra.length; ++i)
            if (botoesDaBarra[i].activeFocus) return botoesDaBarra[i]
        return null
    }
    // O botão visível da barra mais próximo, na horizontal, de `x`; `exceto` não conta e, com `sentido`
    // (-1 ou 1), só valem os que ficam desse lado.
    function botaoPerto(x, exceto, sentido) {
        var melhor = null, distancia = 1e9
        for (var i = 0; i < botoesDaBarra.length; ++i) {
            var b = botoesDaBarra[i]
            if (!b.visible || !b.enabled || b.indisponivel === true || b === exceto) continue
            var dx = b.mapToItem(null, b.width / 2, 0).x - x
            if (sentido && dx * sentido <= 0) continue
            var d = Math.abs(dx)
            if (d < distancia) { distancia = d; melhor = b }
        }
        return melhor
    }
    function focarBotao(b) { b.forceActiveFocus(Qt.TabFocusReason) }

    function teclaDoPasso(dx, dy) {
        return dy < 0 ? Qt.Key_Up : dy > 0 ? Qt.Key_Down : dx < 0 ? Qt.Key_Left : Qt.Key_Right
    }

    // O Big Picture manda no controle desde o escuro da entrada até o fim da saída: a grade escondida não recebe nada.
    readonly property bool bigPictureNaFrente: bigPicture.visivel || bigPicture.ocupada

    Binding { target: controle; property: "modoBigPicture"; value: bigPicture.visivel && !janela.popupAberto }  // com diálogo na frente vale a repetição da grade

    // Com a camada da sessão à vista o controle não age por baixo dela: nem abre outro jogo, nem entra no
    // Big Picture ao ser conectado (como a `main`). O `ModeloDaSessao` também suspende a leitura; isto vale
    // mesmo sem ela.
    Connections {
        target: controle
        enabled: !sessao.emAndamento
        function onMover(dx, dy) {
            if (janela.popupAberto) { controle.teclar(janela.teclaDoPasso(dx, dy)); return }
            if (janela.bigPictureNaFrente) {
                // Só ← e →; ocupada, a página não anda e o toque não vibra.
                if (bigPicture.ocupada || dx === 0) return
                if (bigPicture.mover(dx)) controle.trocarCapa()
                else controle.bater()
                return
            }
            var focado = janela.botaoFocado()
            if (focado) {
                // Na barra: ↓ volta à grade; ← e → vão ao botão vizinho.
                var x = focado.mapToItem(null, focado.width / 2, 0).x
                if (dy > 0) {
                    janela.paginaDoControle.mostrarSelecao()
                    janela.paginaDoControle.focarGrade()
                } else if (dx !== 0) {
                    var vizinho = janela.botaoPerto(x, focado, dx)
                    if (vizinho) { janela.focarBotao(vizinho); controle.passar() }
                    else controle.bater()
                } else controle.bater()
            } else if (janela.paginaDoControle) {
                if (janela.paginaDoControle.moverSelecao(dx, dy)) {
                    controle.passar()
                } else if (dy < 0) {
                    // ↑ na primeira linha: o botão da barra mais perto na horizontal.
                    var botao = janela.botaoPerto(janela.paginaDoControle.xDoAtual(), null, 0)
                    if (botao) janela.focarBotao(botao)
                    else controle.bater()
                } else controle.bater()
            }
        }
        function onPular(delta) {
            if (janela.popupAberto || !janela.bigPictureNaFrente || bigPicture.ocupada) return
            if (bigPicture.mover(delta)) controle.saltar()
            else controle.bater()
        }
        function onConectado() {
            bigPicture.controleConectado(janela.paginaAtual === "todos" && !janela.popupAberto)
        }
        function onPresente() {
            if (janela.bigPictureNaFrente) return
            if (!janela.popupAberto && !janela.botaoFocado() && janela.paginaDoControle)
                janela.paginaDoControle.mostrarSelecao()
        }
        function onAtivar() {
            if (janela.popupAberto) { controle.teclar(Qt.Key_Return); return }
            if (janela.bigPictureNaFrente) { if (!bigPicture.ocupada) bigPicture.abrirJogo(); return }
            var focado = janela.botaoFocado()
            if (focado) focado.click()
            else if (janela.paginaDoControle) janela.paginaDoControle.abrirDetalhesDoAtual()
        }
        function onVoltar() {
            if (janela.popupAberto) { controle.teclar(Qt.Key_Escape); return }
            if (janela.bigPictureNaFrente) { if (!bigPicture.ocupada) bigPicture.sair(); return }
            if (janela.paginaAtual !== "todos") janela.voltar()
            else if (todos.buscaAberta) todos.buscaAberta = false
        }
        function onMenuPrincipal() { if (!janela.bigPictureNaFrente && !janela.popupAberto) menuPrincipal.open() }
        function onMenuDoJogo() { if (!janela.bigPictureNaFrente && !janela.popupAberto && janela.paginaDoControle) janela.paginaDoControle.abrirMenuDoAtual() }
        function onBuscar() { if (!janela.bigPictureNaFrente && !janela.popupAberto && janela.paginaAtual === "todos") todos.alternarBusca() }
        function onUsado() {
            janela.posicaoDoPonteiro = ponteiro.point.position
            janela.ponteiroEscondido = true
        }
    }

    // O ponteiro some enquanto o controle está em uso e volta quando o mouse anda mais de 1 px.
    HoverHandler {
        id: ponteiro
        cursorShape: janela.ponteiroEscondido ? Qt.BlankCursor : Qt.ArrowCursor
        onPointChanged: {
            if (!janela.ponteiroEscondido) return
            var p = point.position
            if (Math.abs(p.x - janela.posicaoDoPonteiro.x) > 1 || Math.abs(p.y - janela.posicaoDoPonteiro.y) > 1)
                janela.ponteiroEscondido = false
        }
    }
}
