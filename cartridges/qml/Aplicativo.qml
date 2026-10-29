import QtQuick
import QtQuick.Controls.Basic

// A janela do app: as páginas da biblioteca, os botões da barra e as camadas de aviso e confirmação.
// `paginaTodos`, `paginaZerados`, `filtros`, `aplicativo` e `ponte` vêm do contexto (cartridges/app.py).
Principal {
    id: janela

    // Lido aqui, fora dos Avisos, porque lá o nome da propriedade é o mesmo.
    readonly property QtObject ligacao: ponte
    // "todos", "zerados" ou "jogo" (a página de detalhes, por cima de uma das duas).
    readonly property string paginaAtual: pilha.depth === 0 ? "todos"
        : (pilha.currentItem && pilha.currentItem.objectName === "paginaDoJogo" ? "jogo" : "zerados")

    // Abre a página de detalhes do jogo; o foco inicial é dela (StackView.onActivated).
    function abrirDetalhes(jogoId) {
        if (paginaAtual === "jogo") return
        if (detalhes.mostrar(jogoId)) pilha.push(paginaDoJogo)
    }
    // Fecha a página de detalhes, ou sai de Jogos Zerados; o foco volta ao cartão de onde se saiu.
    function voltar() {
        if (paginaAtual === "jogo") detalhes.esquecer()
        if (paginaAtual === "jogo" && pilha.depth > 1) pilha.pop()
        else if (paginaAtual !== "todos") pilha.clear(StackView.PopTransition)
    }

    // O `y` de um menu aberto por um botão da barra: abaixo dos 46 px dela, fora da área de arrasto do QWindowKit.
    function baseDaBarra(botao) { return botao.height + (alturaDaBarra - botao.height) / 2 }

    tituloDaBarra: paginaAtual === "todos" ? "Todos os jogos" : paginaAtual === "zerados" ? "Jogos Zerados" : detalhes.nome

    // Depois do setup do QWindowKit (Principal.qml), que roda no onCompleted da base.
    Component.onCompleted: visible = true

    inicio: [
        BotaoDaBarra {
            id: botaoAdicionar
            enabled: !edicao.aberto
            objectName: "botaoAdicionar"
            visible: janela.paginaAtual === "todos"
            glifo: ""
            dica: "Adicionar jogo"
            onClicked: menuDeAdicionar.open()
            menuAberto: menuDeAdicionar.opened
            MenuDoTema {
                id: menuDeAdicionar
                objectName: "menuDeAdicionar"
                y: janela.baseDaBarra(parent)
                ItemDoMenu { objectName: "itemAdicionarJogo"; text: "Adicionar jogo"; onTriggered: edicao.adicionar() }
                MenuSeparator {}
                ItemDoMenu { text: "Importar"; enabled: !aplicativo.importando; onTriggered: aplicativo.importar() }
            }
        },
        BotaoDaBarra {
            id: botaoVoltar
            enabled: !edicao.aberto
            objectName: "botaoVoltar"
            visible: janela.paginaAtual !== "todos"
            glifo: ""
            dica: "Voltar"
            onClicked: janela.voltar()
        }
    ]

    // Da direita para a esquerda: menu principal, Jogos Zerados e busca.
    fim: [
        BotaoDaBarra {
            id: botaoMenu
            enabled: !edicao.aberto
            objectName: "botaoMenu"
            glifo: ""
            dica: "Menu principal"
            onClicked: menuPrincipal.open()
            menuAberto: menuPrincipal.opened
            MenuPrincipal {
                id: menuPrincipal
                objectName: "menuPrincipal"
                y: janela.baseDaBarra(parent)
                x: parent.width - width
            }
        },
        BotaoDaBarra {
            id: botaoZerados
            enabled: !edicao.aberto
            objectName: "botaoZerados"
            visible: janela.paginaAtual === "todos"
            trofeu: true
            dica: "Jogos Zerados"
            onClicked: pilha.push(zerados)
        },
        BotaoDaBarra {
            id: botaoBusca
            enabled: !edicao.aberto
            objectName: "botaoBusca"
            visible: janela.paginaAtual === "todos"
            glifo: ""
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
        anchors.fill: parent
        pagina: paginaTodos
        comBusca: true
        ativa: pilha.depth === 0
        // Com o diálogo de edição aberto, nada de trás recebe o mouse nem o Tab.
        enabled: !edicao.aberto
        onAbrirDetalhes: id => janela.abrirDetalhes(id)
        onEditar: id => edicao.abrir(id)
    }

    // Vazia, a pilha mostra "Todos os jogos"; "Jogos Zerados" entra por cima.
    StackView {
        id: pilha
        anchors.fill: parent
        visible: depth > 0
        enabled: !edicao.aberto
    }

    Component {
        id: zerados
        PaginaDaBiblioteca {
            objectName: "paginaDeZerados"
            pagina: paginaZerados
            // Coberta pelos detalhes, ela não anima capas.
            ativa: StackView.status !== StackView.Inactive
            onAbrirDetalhes: id => janela.abrirDetalhes(id)
            onEditar: id => edicao.abrir(id)
            StackView.onActivated: focarGrade()
            // O fundo cobre "Todos os jogos" durante a transição.
            Rectangle { anchors.fill: parent; color: Tema.fundo; z: -1 }
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
        }
    }

    // O jogo mostrado foi excluído, removido ou saiu dos Jogos Zerados: a página fecha.
    Connections {
        target: detalhes
        function onSair() { if (janela.paginaAtual === "jogo") janela.voltar() }
    }

    // Abaixo da camada de avisos: o erro de uma validação aparece na frente do diálogo.
    DialogoDeEdicao {
        id: dialogoDeEdicao
        // Fechado a partir de um menu, o foco não tem para onde voltar: vai à página à vista.
        onRetornoPerdido: janela.paginaDoControle.focarGrade()
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

    Avisos {
        id: camadaDeAvisos
        objectName: "camadaDeAvisos"
        anchors.fill: parent
        ponte: janela.ligacao
        fila: aplicativo.avisos
        app: aplicativo
    }

    // Atalhos arrastados do Explorer: só com a janela livre de diálogos.
    DropArea {
        id: alvoDeSoltar
        objectName: "alvoDeSoltar"
        anchors.fill: parent
        enabled: !camadaDeAvisos.dialogoAberto && !edicao.aberto
        onEntered: (arrasto) => arrasto.accepted = arrasto.hasUrls
        onDropped: (soltou) => {
            if (soltou.hasUrls) aplicativo.soltar(soltou.urls)
        }
    }

    Rectangle {
        id: avisoDeSoltar
        objectName: "avisoDeSoltar"
        anchors.fill: parent
        color: "#99000000"
        opacity: alvoDeSoltar.containsDrag ? 1 : 0
        visible: opacity > 0
        Behavior on opacity { NumberAnimation { duration: 150 } }

        Rectangle {
            anchors.centerIn: parent
            width: Math.min(420, avisoDeSoltar.width - 48)
            height: 140
            radius: 12
            color: Tema.fundo
            border { color: Tema.destaque; width: 2 }
            Text {
                anchors.centerIn: parent
                text: "Solte aqui para importar"
                textFormat: Text.PlainText
                color: Tema.texto
                font { family: Tema.fonte; pixelSize: 20; weight: Font.DemiBold }
            }
        }
    }

    Connections {
        target: janela.ligacao
        function onSairDaFrente() { janela.showMinimized() }
    }

    // --- Controle do Xbox -------------------------------------------------------------------------------
    // A página à vista: "Todos os jogos", "Jogos Zerados" ou a de detalhes.
    readonly property var paginaDoControle: pilha.depth === 0 ? todos : pilha.currentItem
    // Menu ou diálogo na frente: o controle navega nele pelas teclas, como o teclado faria.
    readonly property bool popupAberto: menuPrincipal.opened || camadaDeAvisos.dialogoAberto || edicao.aberto
        || (paginaDoControle !== null && paginaDoControle.menuDoJogoAberto)
    property bool ponteiroEscondido: false
    property point posicaoDoPonteiro

    // Os botões da barra que o controle alcança com ↑ na primeira linha.
    readonly property var botoesDaBarra: [botaoAdicionar, botaoVoltar, botaoZerados, botaoBusca, botaoMenu]
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
            if (!b.visible || !b.enabled || b === exceto) continue
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

    Connections {
        target: controle
        function onMover(dx, dy) {
            var focado = janela.botaoFocado()
            if (janela.popupAberto) {
                controle.teclar(janela.teclaDoPasso(dx, dy))
            } else if (focado) {
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
        function onPresente() {
            if (!janela.popupAberto && !janela.botaoFocado() && janela.paginaDoControle)
                janela.paginaDoControle.mostrarSelecao()
        }
        function onAtivar() {
            var focado = janela.botaoFocado()
            if (janela.popupAberto) controle.teclar(Qt.Key_Return)
            else if (focado) focado.click()
            else if (janela.paginaDoControle) janela.paginaDoControle.abrirDetalhesDoAtual()
        }
        function onVoltar() {
            if (janela.popupAberto) controle.teclar(Qt.Key_Escape)
            else if (janela.paginaAtual !== "todos") janela.voltar()
            else if (todos.buscaAberta) todos.buscaAberta = false
        }
        function onMenuPrincipal() { if (!janela.popupAberto) menuPrincipal.open() }
        function onMenuDoJogo() { if (!janela.popupAberto && janela.paginaDoControle) janela.paginaDoControle.abrirMenuDoAtual() }
        function onBuscar() { if (!janela.popupAberto && janela.paginaAtual === "todos") todos.alternarBusca() }
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
