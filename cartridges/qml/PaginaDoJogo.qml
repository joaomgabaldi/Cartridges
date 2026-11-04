import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Effects
import QtQuick.Layouts
import QtQuick.Window

// A página de detalhes de um jogo: capa à esquerda, dados à direita e ações embaixo; abaixo de 850 px vira uma coluna.
Item {
    id: raiz

    property string placeholder: ""

    signal voltar()
    signal jogar()
    signal editar()
    signal remover()
    signal excluir()
    signal atualizacaoConfirmada()
    signal abrirHistorico()

    readonly property bool menuDoJogoAberto: menuDeStatus.opened || menuDeBuscas.opened || balaoDaAnotacao.opened
        || dialogoExcluir.visible || dialogoAtualizacao.visible
    readonly property bool dialogoAberto: dialogoExcluir.aberto || dialogoAtualizacao.aberto
    readonly property bool compacta: width <= 850
    readonly property int larguraDaCapa: compacta ? 280 : 420
    readonly property int alturaDaCapa: larguraDaCapa * 3 / 2
    // Larguras de texto: o "0" do Segoe UI vezes 72 caracteres (24 no título); a quebra de linha real pede 7,4 px por caractere.
    readonly property real tetoDoTexto: 72 * 7.4
    readonly property real tetoDoTitulo: 24 * zeroDoTitulo.advanceWidth
    // O logo só vale enquanto o arquivo decodifica: um PNG truncado passa pela leitura do cabeçalho.
    readonly property bool logoVisivel: detalhes.logo !== "" && logo.status !== Image.Error
    readonly property color corDeAviso: Tema.avisoIcone
    property bool tecladoEmUso: false

    TextMetrics { id: zeroDoTitulo; text: "0"; font { family: Tema.fonte; pixelSize: Tema.titulo1; weight: Tema.pesoTitulo1 } }

    function focarInicial() {
        (detalhes.zerado ? botaoStatus : botaoJogar).forceActiveFocus(tecladoEmUso ? Qt.TabFocusReason : Qt.OtherFocusReason)
    }
    function focarGrade() { focarInicial() }
    function mostrarSelecao() {}
    function abrirMenuDoAtual() {}
    function xDoAtual() { return raiz.mapToItem(null, raiz.width / 2, 0).x }

    function linhasDeBotoes() {
        var linhas = [[cartaoDeConquistas.botao], [botaoStatus, botaoAnotacao], [avisoDeAtualizacao],
                      [botaoJogar, botaoEditar, botaoExcluir, botaoRemover, botaoBuscar]]
        return linhas.map(l => l.filter(b => b.visible && b.enabled)).filter(l => l.length > 0)
    }
    function moverSelecao(dx, dy) {
        var linhas = linhasDeBotoes()
        var foco = Window.window ? Window.window.activeFocusItem : null
        var r = -1, c = -1
        for (var i = 0; i < linhas.length; ++i) {
            var j = linhas[i].indexOf(foco)
            if (j >= 0) { r = i; c = j }
        }
        if (r < 0) { focarInicial(); return true }
        var botao
        if (dx !== 0) {
            if (c + dx < 0 || c + dx >= linhas[r].length) return false
            botao = linhas[r][c + dx]
        } else {
            if (r + dy < 0 || r + dy >= linhas.length) return false
            var alvo = linhas[r + dy]
            botao = alvo[Math.min(c, alvo.length - 1)]
        }
        botao.forceActiveFocus(Qt.TabFocusReason)
        mostrarBotao(botao)
        return true
    }
    function mostrarBotao(botao) {
        var topo = botao.mapToItem(rolagem.contentItem, 0, 0).y
        var fim = topo + botao.height
        if (topo < rolagem.contentY) rolagem.contentY = Math.max(0, topo)
        else if (fim > rolagem.contentY + rolagem.height) rolagem.contentY = Math.min(rolagem.contentHeight - rolagem.height, fim - rolagem.height)
    }
    function abrirDetalhesDoAtual() {
        var foco = Window.window ? Window.window.activeFocusItem : null
        if (foco && foco.click) foco.click()
    }

    focus: true
    Keys.onEscapePressed: voltar()
    Keys.onLeftPressed: event => event.accepted = moverSelecao(-1, 0)
    Keys.onRightPressed: event => event.accepted = moverSelecao(1, 0)
    Keys.onUpPressed: event => event.accepted = moverSelecao(0, -1)
    Keys.onDownPressed: event => event.accepted = moverSelecao(0, 1)
    Keys.onReturnPressed: abrirDetalhesDoAtual()
    Keys.onEnterPressed: abrirDetalhesDoAtual()

    // Quem tinha o foco (a grade) diz se foi pelo teclado: com o mouse, o foco inicial não tem anel.
    Component.onCompleted: {
        for (var p = Window.window ? Window.window.activeFocusItem : null; p; p = p.parent) {
            if (p.porTeclado === true || p.visualFocus === true) { tecladoEmUso = true; break }
        }
    }
    // Depois do foco que a própria StackView dá à página ao ativá-la.
    StackView.onActivated: Qt.callLater(() => {
        focarInicial()
        if (anotarAoEntrar) abrirAnotacao()
    })
    property bool anotarAoEntrar: false
    function abrirAnotacao() { if (botaoAnotacao.visible) balaoDaAnotacao.open() }

    // Branco (claro) ou preto (escuro) sob a capa desfocada; a imagem continua sob a barra transparente (daí o `y` negativo).
    readonly property int sobreABarra: Window.window && Window.window.alturaDaBarra ? Window.window.alturaDaBarra : 0
    Rectangle { anchors.fill: parent; color: Tema.escuro ? "black" : "white"; z: -2 }

    Item {
        anchors.fill: parent
        z: -1
        clip: true
        Image {
            id: fundo
            objectName: "fundoDesfocado"
            y: -raiz.sobreABarra
            width: parent.width
            height: parent.height + raiz.sobreABarra
            source: detalhes.fundo
            fillMode: Image.Stretch
            asynchronous: false  // provedor Python na thread de imagens trava: ela espera o GIL segurando o mutex do cache
            opacity: detalhes.opacidadeDoFundo
            visible: detalhes.fundo !== ""
        }
    }

    component Dado: Text {
        id: dado
        Layout.fillWidth: true
        Layout.preferredWidth: Math.min(gemeo.implicitWidth, raiz.tetoDoTexto)
        Layout.maximumWidth: Math.min(gemeo.implicitWidth, raiz.tetoDoTexto)
        Layout.alignment: raiz.compacta ? Qt.AlignHCenter : Qt.AlignLeft
        visible: text !== ""
        textFormat: Text.PlainText
        wrapMode: Text.Wrap
        horizontalAlignment: raiz.compacta ? Text.AlignHCenter : Text.AlignLeft
        color: Tema.textoSecundario
        font { family: Tema.fonte; pixelSize: Tema.corpo }
        // A linha do Segoe UI de 12 tem 17 px (o Qt dá 16); a diferença pesa 14 px na coluna inteira.
        lineHeightMode: Text.FixedHeight
        lineHeight: Tema.alturaDoCorpo
        Text {
            id: gemeo
            visible: false
            text: dado.text
            textFormat: Text.PlainText
            font: dado.font
        }
    }

    component Linha: Text {
        id: linhaDeData
        Layout.fillWidth: true
        Layout.preferredWidth: gemeoDaLinha.implicitWidth
        Layout.maximumWidth: gemeoDaLinha.implicitWidth
        visible: text !== ""
        textFormat: Text.PlainText
        wrapMode: Text.Wrap
        horizontalAlignment: Text.AlignHCenter
        color: Tema.texto
        font { family: Tema.fonte; pixelSize: Tema.corpo }
        lineHeightMode: Text.FixedHeight
        lineHeight: Tema.alturaDoCorpo
        Text {
            id: gemeoDaLinha
            visible: false
            text: linhaDeData.text
            textFormat: Text.PlainText
            font: linhaDeData.font
        }
    }

    component BotaoDeMenu: Botao {
        id: botaoDeMenu
        dicaSomeAoClicar: false
        estilo: "plano"
        leftPadding: 10
        rightPadding: 10
        implicitWidth: contentItem.implicitWidth + 20
        contentItem: Item {
            implicitWidth: rotuloESeta.implicitWidth
            implicitHeight: rotuloESeta.implicitHeight
            Row {
                id: rotuloESeta
                anchors.centerIn: parent
                spacing: 6
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: botaoDeMenu.text
                    textFormat: Text.PlainText
                    color: Tema.texto
                    font { family: Tema.fonte; pixelSize: Tema.corpo; weight: Tema.pesoForte }
                }
                Icone { anchors.verticalCenter: parent.verticalCenter; nome: "pan-down" }
            }
        }
    }

    component TituloDeSecao: Item {
        property string texto
        implicitHeight: 32
        implicitWidth: rotulo.implicitWidth + 24
        Text {
            id: rotulo
            anchors { left: parent.left; leftMargin: 12; verticalCenter: parent.verticalCenter }
            text: parent.texto
            textFormat: Text.PlainText
            color: Tema.textoSecundario
            font { family: Tema.fonte; pixelSize: Tema.corpo; weight: Tema.pesoForte }
        }
    }

    Flickable {
        id: rolagem
        objectName: "rolagemDaPagina"
        anchors.fill: parent
        contentWidth: width
        contentHeight: Math.max(height, linha.height + 2 * linha.margem)
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        RolagemDaRoda { alvo: rolagem }
        ScrollBar.vertical: BarraDeRolagem {}

        GridLayout {
            id: linha
            readonly property real margem: raiz.compacta ? 12 : 24
            x: Math.max(margem, (rolagem.width - width) / 2)
            y: Math.max(margem, (rolagem.contentHeight - height) / 2)
            width: Math.min(implicitWidth, rolagem.width - 2 * margem)
            columns: raiz.compacta ? 1 : 2
            columnSpacing: 48
            rowSpacing: 0

            Item {
                id: coluna
                Layout.preferredWidth: raiz.larguraDaCapa
                Layout.preferredHeight: raiz.alturaDaCapa
                Layout.alignment: raiz.compacta ? Qt.AlignHCenter | Qt.AlignTop : Qt.AlignTop

                Sombra { camadas: Tema.sombraCartao; raio: 12 }
                Item {
                    id: mascara
                    anchors.fill: parent
                    visible: false
                    layer.enabled: true
                    Rectangle { anchors.fill: parent; radius: 12 }
                }
                Item {
                    anchors.fill: parent
                    opacity: detalhes.carregando ? 0 : 1
                    layer.enabled: true
                    layer.effect: MultiEffect {
                        maskEnabled: true
                        maskSource: mascara
                        maskThresholdMin: 0.5
                        maskSpreadAtMin: 1.0
                    }
                    Image {
                        objectName: "capaDaPagina"
                        // URL ilegível (arquivo quebrado): usa o placeholder. Uma capa nova muda a URL.
                        property string ilegivel: ""
                        anchors.fill: parent
                        source: detalhes.capa !== "" && detalhes.capa !== ilegivel ? detalhes.capa : raiz.placeholder
                        onStatusChanged: if (status === Image.Error && source.toString() === detalhes.capa) ilegivel = detalhes.capa
                        fillMode: Image.PreserveAspectFit
                        asynchronous: true
                        // Na resolução real da tela: a capa guardada tem mais pixels que a da grade.
                        sourceSize: Qt.size(raiz.larguraDaCapa * Screen.devicePixelRatio,
                                            raiz.alturaDaCapa * Screen.devicePixelRatio)
                    }
                    AnimatedImage {
                        objectName: "capaAnimadaDaPagina"
                        readonly property bool aVista: Window.visibility !== Window.Minimized
                            && Window.visibility !== Window.Hidden && !sessao.emAndamento
                        anchors.fill: parent
                        source: detalhes.capaAnimada !== "" && aVista ? detalhes.capaAnimada : ""
                        playing: aVista
                        visible: status === AnimatedImage.Ready
                        fillMode: Image.PreserveAspectFit
                        asynchronous: true
                        cache: false
                    }
                }
                Girador {
                    objectName: "carregandoDaPagina"
                    anchors.centerIn: parent
                    running: detalhes.carregando
                    visible: detalhes.carregando
                }
            }

            ColumnLayout {
                id: dados
                Layout.fillWidth: true
                Layout.maximumWidth: dados.implicitWidth
                Layout.alignment: raiz.compacta ? Qt.AlignHCenter | Qt.AlignTop : Qt.AlignVCenter
                spacing: 0

                Item {
                    Layout.fillWidth: true
                    Layout.preferredWidth: raiz.logoVisivel ? Math.min(detalhes.larguraDoLogo, raiz.tetoDoTexto) : Math.min(gemeoDoTitulo.implicitWidth, raiz.tetoDoTitulo)
                    Layout.topMargin: raiz.compacta ? 30 : 0
                    Layout.bottomMargin: 12
                    implicitHeight: raiz.logoVisivel ? 72 : titulo.implicitHeight

                    Image {
                        id: logo
                        objectName: "logoDoJogo"
                        visible: raiz.logoVisivel
                        anchors { left: raiz.compacta ? undefined : parent.left; horizontalCenter: raiz.compacta ? parent.horizontalCenter : undefined; bottom: parent.bottom }
                        width: Math.min(detalhes.larguraDoLogo, parent.width)
                        height: 72
                        source: detalhes.logo
                        fillMode: Image.PreserveAspectFit
                        horizontalAlignment: raiz.compacta ? Image.AlignHCenter : Image.AlignLeft
                        verticalAlignment: Image.AlignBottom
                        asynchronous: false
                        // Decodifica na escala da tela: o arquivo em cache pode ter 4096 px e o cabeçalho tem 72.
                        sourceSize.height: 72 * Screen.devicePixelRatio
                    }
                    Text {
                        id: titulo
                        objectName: "tituloDoJogo"
                        visible: !raiz.logoVisivel
                        width: parent.width
                        text: detalhes.nome
                        textFormat: Text.PlainText
                        wrapMode: Text.Wrap
                        horizontalAlignment: raiz.compacta ? Text.AlignHCenter : Text.AlignLeft
                        color: Tema.texto
                        font { family: Tema.fonte; pixelSize: Tema.titulo1; weight: Tema.pesoTitulo1 }
                    }
                    Text {
                        id: gemeoDoTitulo
                        visible: false
                        text: detalhes.nome
                        textFormat: Text.PlainText
                        font: titulo.font
                    }
                }

                Dado {
                    objectName: "desenvolvedora"
                    Layout.topMargin: 6
                    text: detalhes.desenvolvedora
                    color: Tema.texto
                    font.weight: Tema.pesoForte
                }
                Dado { objectName: "publicadora"; Layout.topMargin: 3; text: detalhes.publicadora }
                Dado { objectName: "dataDeLancamento"; Layout.topMargin: 3; text: detalhes.dataDeLancamento }
                Dado { objectName: "nota"; Layout.topMargin: 3; text: detalhes.nota }
                Dado { objectName: "metacritic"; Layout.topMargin: 3; text: detalhes.metacritic }
                Dado { objectName: "avaliacoes"; Layout.topMargin: 3; text: detalhes.avaliacoes }
                Dado { objectName: "genero"; Layout.topMargin: 3; text: detalhes.genero }
                Dado { objectName: "controle"; Layout.topMargin: 3; text: detalhes.controle }
                Dado {
                    objectName: "controleRecomendado"
                    Layout.topMargin: 3
                    visible: detalhes.controleRecomendado
                    text: "★ Os desenvolvedores recomendam o uso de um controle."
                }
                Dado {
                    objectName: "descricao"
                    Layout.topMargin: 12
                    text: detalhes.descricao
                }

                ColumnLayout {
                    id: blocoHltb
                    objectName: "blocoHltb"
                    Layout.topMargin: 18
                    Layout.alignment: raiz.compacta ? Qt.AlignHCenter : Qt.AlignLeft
                    visible: detalhes.hltb.celulas !== undefined
                        && (detalhes.hltb.celulas.length > 0 || detalhes.hltb.capitulos.length > 0)
                    spacing: 0

                    Text {
                        Layout.leftMargin: 3
                        Layout.bottomMargin: 6
                        text: "HowLongToBeat"
                        textFormat: Text.PlainText
                        color: Tema.textoSecundario
                        font { family: Tema.fonte; pixelSize: Tema.legenda; weight: Tema.pesoForte }
                    }
                    Rectangle {
                        objectName: "cartaoHltb"
                        visible: detalhes.hltb.celulas !== undefined && detalhes.hltb.celulas.length > 0
                        implicitWidth: celulas.implicitWidth
                        implicitHeight: celulas.implicitHeight
                        radius: 12
                        color: Tema.cartao
                        Sombra { camadas: Tema.sombraCartao; raio: 12 }
                        Row {
                            id: celulas
                            Repeater {
                                model: detalhes.hltb.celulas
                                delegate: Row {
                                    id: celula
                                    required property var modelData
                                    Rectangle {
                                        visible: celula.modelData.separador
                                        width: 1
                                        height: Math.max(0, celulaTexto.height - 20)
                                        y: 10
                                        color: Tema.borda
                                    }
                                    Item {
                                        id: celulaTexto
                                        width: Math.max(76, texto.implicitWidth) + 40  // min-width é do conteúdo: o padding vem por fora
                                        height: texto.implicitHeight + 20
                                        Column {
                                            id: texto
                                            anchors { horizontalCenter: parent.horizontalCenter; top: parent.top; topMargin: 10 }
                                            spacing: 2
                                            Text {
                                                anchors.horizontalCenter: parent.horizontalCenter
                                                text: celula.modelData.valor
                                                textFormat: Text.PlainText
                                                color: Tema.texto
                                                font {
                                                    family: Tema.fonte; pixelSize: Tema.titulo4; weight: Tema.pesoTitulo4
                                                    features: ({ "tnum": 1 })
                                                }
                                            }
                                            Text {
                                                anchors.horizontalCenter: parent.horizontalCenter
                                                text: celula.modelData.rotulo
                                                textFormat: Text.PlainText
                                                color: Tema.textoSecundario
                                                font { family: Tema.fonte; pixelSize: Tema.legenda }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                    Rectangle {
                        objectName: "capitulosHltb"
                        visible: detalhes.hltb.capitulos !== undefined && detalhes.hltb.capitulos.length > 0
                        implicitWidth: tabela.implicitWidth + 32
                        implicitHeight: tabela.implicitHeight + 24
                        radius: 12
                        color: Tema.cartao
                        Sombra { camadas: Tema.sombraCartao; raio: 12 }
                        GridLayout {
                            id: tabela
                            x: 16; y: 12
                            columns: 4
                            columnSpacing: 16
                            rowSpacing: 4
                            Item { width: 1; height: 1 }
                            Repeater {
                                model: detalhes.hltb.colunas
                                delegate: Text {
                                    required property string modelData
                                    Layout.minimumWidth: 68
                                    horizontalAlignment: Text.AlignHCenter
                                    text: modelData
                                    textFormat: Text.PlainText
                                    color: Tema.textoSecundario
                                    font { family: Tema.fonte; pixelSize: Tema.legenda }
                                }
                            }
                            Repeater {
                                model: (detalhes.hltb.capitulos || []).length * 4
                                delegate: Text {
                                    required property int index
                                    readonly property var capitulo: detalhes.hltb.capitulos[Math.floor(index / 4)]
                                    readonly property bool rotuloDaLinha: index % 4 === 0
                                    Layout.minimumWidth: rotuloDaLinha ? 0 : 68
                                    Layout.rightMargin: rotuloDaLinha ? 8 : 0
                                    horizontalAlignment: rotuloDaLinha ? Text.AlignLeft : Text.AlignHCenter
                                    text: rotuloDaLinha ? capitulo.rotulo : capitulo.valores[index % 4 - 1]
                                    textFormat: Text.PlainText
                                    color: Tema.texto
                                    font {
                                        family: Tema.fonte
                                        pixelSize: rotuloDaLinha ? Tema.legenda : Tema.corpo
                                        weight: rotuloDaLinha ? Tema.pesoForte : Tema.pesoCorpo
                                        features: ({ "tnum": rotuloDaLinha ? 0 : 1 })
                                    }
                                }
                            }
                        }
                    }
                }

                CartaoDeConquistas {
                    id: cartaoDeConquistas
                    Layout.topMargin: 18
                    Layout.alignment: raiz.compacta ? Qt.AlignHCenter : Qt.AlignLeft
                }

                RowLayout {
                    Layout.fillWidth: true
                    Layout.maximumWidth: implicitWidth
                    Layout.topMargin: 15
                    Layout.alignment: raiz.compacta ? Qt.AlignHCenter : Qt.AlignLeft
                    spacing: 12
                    Linha { text: detalhes.adicionado }
                    Linha { text: detalhes.jogadoPorUltimo }
                    // O total vira o histórico sem ser link nem botão (destoariam das duas linhas ao lado): sublinhado, cursor de mão e dica avisam.
                    // shortcut: o total não recebe o foco do teclado nem do controle, sai se pedirem.
                    Linha {
                        id: tempoDeJogo
                        objectName: "tempoDeJogo"
                        readonly property bool clicavel: detalhes.temSessoes
                        readonly property string dica: clicavel ? "Ver o histórico de sessões" : ""
                        text: detalhes.tempoDeJogo
                        font.underline: clicavel
                        Accessible.role: clicavel ? Accessible.Button : Accessible.StaticText
                        Accessible.name: text
                        Accessible.description: dica
                        Accessible.onPressAction: if (clicavel) raiz.abrirHistorico()
                        Dica { texto: tempoDeJogo.dica; ativa: areaDoTempo.containsMouse && tempoDeJogo.clicavel }
                        MouseArea {
                            id: areaDoTempo
                            objectName: "areaDoTempoDeJogo"
                            anchors.fill: parent
                            enabled: tempoDeJogo.clicavel
                            hoverEnabled: true
                            cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                            onClicked: raiz.abrirHistorico()
                        }
                    }
                    Linha { text: detalhes.tamanho }
                }

                Row {
                    Layout.topMargin: 12
                    Layout.alignment: raiz.compacta ? Qt.AlignHCenter : Qt.AlignLeft
                    spacing: 6
                    BotaoDeMenu {
                        id: botaoStatus
                        objectName: "botaoStatus"
                        text: detalhes.rotuloDoStatus
                        dica: "Status deste jogo na biblioteca"
                        onClicked: menuDeStatus.opened ? menuDeStatus.close() : menuDeStatus.open()
                        MenuDoTema {
                            id: menuDeStatus
                            objectName: "menuDeStatus"
                            // Apertar o botão não fecha: o clique dele fecha (abre e fecha no mesmo botão).
                            fechamento: Popup.CloseOnEscape | Popup.CloseOnPressOutsideParent
                            x: (parent.width - width) / 2
                            y: parent.height + 6
                            setaEm: width / 2
                            Repeater {
                                model: detalhes.statusOpcoes
                                delegate: ItemDoMenu {
                                    required property var modelData
                                    text: modelData[1]
                                    onTriggered: detalhes.definirStatus(modelData[0])
                                }
                            }
                            SeparadorDoMenu {}
                            ItemDoMenu {
                                objectName: "itemSemStatus"
                                text: "Sem status"
                                onTriggered: detalhes.definirStatus("")
                            }
                        }
                    }
                    BotaoDeMenu {
                        id: botaoAnotacao
                        objectName: "botaoAnotacao"
                        visible: detalhes.mostraAnotacao
                        text: "Onde eu parei"
                        dica: detalhes.dicaDaAnotacao
                        onClicked: balaoDaAnotacao.opened ? balaoDaAnotacao.close() : balaoDaAnotacao.open()
                        BalaoDaAnotacao {
                            id: balaoDaAnotacao
                            objectName: "balaoDaAnotacao"
                            texto: detalhes.anotacao
                            editavel: detalhes.anotacaoEditavel
                            onGravar: texto => detalhes.gravarAnotacao(texto)
                        }
                    }
                }

                Button {
                    id: avisoDeAtualizacao
                    objectName: "avisoDeAtualizacao"
                    Layout.topMargin: 15
                    Layout.alignment: raiz.compacta ? Qt.AlignHCenter : Qt.AlignLeft
                    visible: detalhes.temAtualizacao
                    focusPolicy: Qt.StrongFocus
                    hoverEnabled: true
                    text: "Atualização disponível"
                    topPadding: 8
                    bottomPadding: 8
                    leftPadding: 16
                    rightPadding: 16
                    Accessible.name: text
                    Keys.onReturnPressed: click()
                    Keys.onEnterPressed: click()
                    onClicked: {
                        detalhes.abrirAtualizacao()
                        dialogoAtualizacao.abrir()
                    }
                    contentItem: Row {
                        spacing: 8
                        Icone { anchors.verticalCenter: parent.verticalCenter; nome: "software-update-available"; cor: raiz.corDeAviso }
                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            text: avisoDeAtualizacao.text
                            textFormat: Text.PlainText
                            color: raiz.corDeAviso
                            font { family: Tema.fonte; pixelSize: Tema.corpo; weight: Tema.pesoForte }
                        }
                    }
                    background: Rectangle {
                        radius: 12
                        color: Qt.alpha(raiz.corDeAviso, avisoDeAtualizacao.hovered || avisoDeAtualizacao.down ? 0.25 : 0.15)
                        Behavior on color { ColorAnimation { duration: Tema.duracaoCurta } }
                        AnelDeFoco { ativo: avisoDeAtualizacao.visualFocus; raio: 12 }
                    }
                    Dica { texto: "Abrir a página da atualização"; ativa: avisoDeAtualizacao.hovered }
                }

                GridLayout {
                    Layout.topMargin: 24
                    Layout.alignment: raiz.compacta ? Qt.AlignHCenter : Qt.AlignLeft
                    columns: raiz.compacta ? 1 : 2
                    columnSpacing: 0
                    rowSpacing: 0

                    Button {
                        id: botaoJogar
                        objectName: "botaoJogarDaPagina"
                        Layout.alignment: raiz.compacta ? Qt.AlignHCenter : Qt.AlignVCenter
                        visible: !detalhes.zerado
                        focusPolicy: Qt.StrongFocus
                        hoverEnabled: true
                        text: "Jogar"
                        leftPadding: 32
                        rightPadding: 32
                        topPadding: 0
                        bottomPadding: 0
                        implicitHeight: 44
                        implicitWidth: contentItem.implicitWidth + 64
                        Accessible.name: "Jogar"
                        Keys.onReturnPressed: click()
                        Keys.onEnterPressed: click()
                        onClicked: raiz.jogar()
                        readonly property color corDoTexto: Tema.escuro ? Qt.rgba(0, 0, 0, 0.8) : "white"
                        contentItem: Text {
                            text: botaoJogar.text
                            textFormat: Text.PlainText
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                            color: botaoJogar.corDoTexto
                            font { family: Tema.fonte; pixelSize: Tema.corpo; weight: Tema.pesoForte }
                        }
                        background: Rectangle {
                            radius: height / 2
                            color: Tema.escuro ? "white" : Qt.rgba(0, 0, 0, 0.8)
                            Rectangle {
                                anchors.fill: parent
                                radius: parent.radius
                                visible: botaoJogar.hovered || botaoJogar.down
                                color: botaoJogar.down ? Qt.rgba(0, 0, 6 / 255, 0.2) : Qt.alpha(botaoJogar.corDoTexto, botaoJogar.corDoTexto.a * 0.1)
                            }
                            AnelDeFoco { ativo: botaoJogar.visualFocus; raio: parent.radius }
                        }
                    }
                    RowLayout {
                        Layout.leftMargin: raiz.compacta ? 0 : 15
                        Layout.topMargin: raiz.compacta ? 30 : 0
                        Layout.alignment: raiz.compacta ? Qt.AlignHCenter : Qt.AlignVCenter
                        spacing: 6
                        Botao {
                            id: botaoEditar
                            objectName: "botaoEditar"
                            circular: true
                            icone: "document-edit"
                            dica: "Editar"
                            onClicked: raiz.editar()
                        }
                        Botao {
                            id: botaoExcluir
                            objectName: "botaoExcluir"
                            visible: detalhes.zerado
                            circular: true
                            icone: "user-trash"
                            dica: "Excluir"
                            onClicked: dialogoExcluir.abrir()
                        }
                        Botao {
                            id: botaoRemover
                            objectName: "botaoRemover"
                            visible: !detalhes.zerado
                            circular: true
                            icone: "user-trash"
                            dica: "Remover"
                            onClicked: raiz.remover()
                        }
                        Botao {
                            id: botaoBuscar
                            objectName: "botaoBuscarDaPagina"
                            visible: !detalhes.zerado
                            circular: true
                            icone: "system-search"
                            dica: "Buscar"
                            dicaAtiva: hovered && !menuDeBuscas.opened
                            onClicked: menuDeBuscas.opened ? menuDeBuscas.close() : menuDeBuscas.open()
                            MenuDoTema {
                                id: menuDeBuscas
                                objectName: "menuDeBuscas"
                                fechamento: Popup.CloseOnEscape | Popup.CloseOnPressOutsideParent
                                x: (parent.width - width) / 2
                                y: parent.height + 6
                                setaEm: width / 2
                                TituloDeSecao { objectName: "tituloDoMenuDeBuscas"; texto: "Buscar em…" }
                                ItemDoMenu { text: "IGDB"; onTriggered: detalhes.buscarEm("igdb") }
                                ItemDoMenu { text: "SteamGridDB"; onTriggered: detalhes.buscarEm("sgdb") }
                                ItemDoMenu { text: "PCGamingWiki"; onTriggered: detalhes.buscarEm("pcgw") }
                                ItemDoMenu { text: "HowLongToBeat"; onTriggered: detalhes.buscarEm("hltb") }
                            }
                        }
                    }
                }
            }
        }
    }

    DialogoDeConfirmacao {
        id: dialogoExcluir
        objectName: "dialogoExcluir"
        titulo: "Excluir %1?".arg(detalhes.nome)
        corpo: "Tem certeza que deseja excluir este jogo? Esta ação é irreversível."
        rotuloConfirmar: "Excluir"
        rotuloCancelar: "Cancelar"
        destrutivo: true
        onConfirmado: raiz.excluir()
        onRetornoPerdido: raiz.forceActiveFocus()
    }
    DialogoDeConfirmacao {
        id: dialogoAtualizacao
        objectName: "dialogoAtualizacao"
        titulo: "Você instalou a atualização?"
        corpo: "A página da atualização foi aberta no navegador. Confirme após instalá-la para ocultar o aviso."
        rotuloConfirmar: "Já instalei"
        rotuloCancelar: "Ainda não"
        sugerido: true
        respostaInicial: "confirmar"
        onConfirmado: raiz.atualizacaoConfirmada()
        onRetornoPerdido: raiz.forceActiveFocus()
    }
}
