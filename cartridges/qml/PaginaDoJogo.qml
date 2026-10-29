import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Effects
import QtQuick.Layouts
import QtQuick.Window

// A página de detalhes de um jogo: a capa à esquerda, os dados à direita e, embaixo, as ações.
// Tudo o que ela mostra vem de `detalhes` (cartridges/modelos/detalhes.py), exposto pelo contexto;
// nenhum botão age sozinho, só emite o sinal (Aplicativo.qml os liga).
Item {
    id: raiz

    // A capa de reserva, para o jogo sem capa (a mesma da grade).
    property string placeholder: ""

    signal voltar()
    signal jogar()
    signal editar()
    signal remover()
    signal excluir()

    // O que o controle do Xbox e a janela esperam de qualquer página (ver Aplicativo.qml).
    readonly property bool menuDoJogoAberto: false
    readonly property bool compacta: width < 1000
    readonly property int larguraDaCapa: compacta ? 280 : 420
    readonly property int alturaDaCapa: larguraDaCapa * 3 / 2
    readonly property int larguraDoTexto: Math.max(240, Math.min(600, width - larguraDaCapa - 48 * 2))
    // O logo só vale enquanto o arquivo decodifica: um PNG truncado passa pela leitura do cabeçalho.
    readonly property bool logoVisivel: detalhes.logo !== "" && logo.status !== Image.Error

    function focarInicial() {
        (detalhes.zerado ? botaoStatus : botaoJogar).forceActiveFocus(Qt.TabFocusReason)
    }
    // Os nomes que a janela chama em qualquer página.
    function focarGrade() { focarInicial() }
    function mostrarSelecao() {}
    function abrirMenuDoAtual() {}
    function xDoAtual() { return raiz.mapToItem(null, raiz.width / 2, 0).x }

    // Os botões por linha, de cima para baixo; só os que aparecem.
    function linhasDeBotoes() {
        var linhas = [[botaoStatus, botaoAnotacao], [avisoDeAtualizacao],
                      [botaoJogar, botaoEditar, botaoExcluir, botaoRemover, botaoBuscar]]
        return linhas.map(l => l.filter(b => b.visible && b.enabled)).filter(l => l.length > 0)
    }
    // O controle e as setas: movem o foco entre os botões. Devolve se o foco mudou.
    function moverSelecao(dx, dy) {
        var linhas = linhasDeBotoes()
        var foco = Window.window ? Window.window.activeFocusItem : null
        var r = -1, c = -1
        for (var i = 0; i < linhas.length; ++i) {
            var j = linhas[i].indexOf(foco)
            if (j >= 0) { r = i; c = j }
        }
        if (r < 0) { focarInicial(); return true }
        if (dx !== 0) {
            if (c + dx < 0 || c + dx >= linhas[r].length) return false
            linhas[r][c + dx].forceActiveFocus(Qt.TabFocusReason)
        } else {
            if (r + dy < 0 || r + dy >= linhas.length) return false
            var alvo = linhas[r + dy]
            alvo[Math.min(c, alvo.length - 1)].forceActiveFocus(Qt.TabFocusReason)
        }
        return true
    }
    // O A do controle e o Enter: ativa o botão focado.
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

    // Depois do foco que a própria StackView dá à página ao ativá-la.
    StackView.onActivated: Qt.callLater(focarInicial)

    // Cobre a biblioteca por baixo durante a transição.
    Rectangle { anchors.fill: parent; color: Tema.fundo; z: -2 }

    // A capa desfocada, esticada; sem capa, o fundo liso (nada a desenhar).
    Image {
        id: fundo
        objectName: "fundoDesfocado"
        anchors.fill: parent
        z: -1
        source: detalhes.fundo
        fillMode: Image.Stretch
        asynchronous: true
        opacity: detalhes.opacidadeDoFundo
        visible: detalhes.fundo !== ""
    }

    component Dado: Text {
        Layout.fillWidth: true
        visible: text !== ""
        textFormat: Text.PlainText
        wrapMode: Text.Wrap
        color: Tema.textoSecundario
        font { family: Tema.fonte; pixelSize: 14 }
    }

    component BotaoRedondo: Button {
        id: botao
        property string glifo
        property string dica
        implicitWidth: 40
        implicitHeight: 40
        focusPolicy: Qt.StrongFocus
        Accessible.name: dica
        ToolTip.visible: hovered && dica !== ""
        ToolTip.text: dica
        ToolTip.delay: 600
        contentItem: Text {
            text: botao.glifo
            textFormat: Text.PlainText
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            color: Tema.texto
            font { family: Tema.fonteDeIcones; pixelSize: 16 }
        }
        background: Rectangle {
            radius: width / 2
            color: botao.down ? Tema.pressionado : botao.hovered ? Tema.botaoSobre : Tema.superficie
            border { width: botao.visualFocus ? 2 : 1; color: botao.visualFocus ? Tema.destaque : Tema.borda }
        }
    }

    component BotaoDeTexto: Button {
        id: botao
        property string dica
        focusPolicy: Qt.StrongFocus
        implicitHeight: 34
        leftPadding: 12
        rightPadding: 12
        ToolTip.visible: hovered && dica !== ""
        ToolTip.text: dica
        ToolTip.delay: 600
        contentItem: Text {
            text: botao.text
            textFormat: Text.PlainText
            verticalAlignment: Text.AlignVCenter
            color: Tema.texto
            font { family: Tema.fonte; pixelSize: 14 }
        }
        background: Rectangle {
            radius: 6
            color: botao.down ? Tema.pressionado : botao.hovered ? Tema.botaoSobre : "transparent"
            border { width: botao.visualFocus ? 2 : 0; color: Tema.destaque }
        }
    }

    Flickable {
        id: rolagem
        anchors.fill: parent
        contentWidth: width
        contentHeight: Math.max(height, linha.height + 48)
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: BarraDeRolagem {}

        RowLayout {
            id: linha
            x: Math.max(24, (rolagem.width - width) / 2)
            y: Math.max(24, (rolagem.contentHeight - height) / 2)
            spacing: 48

            // --- A capa ---------------------------------------------------------------------------
            Item {
                id: coluna
                Layout.preferredWidth: raiz.larguraDaCapa
                Layout.preferredHeight: raiz.alturaDaCapa
                Layout.alignment: Qt.AlignTop

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
                        anchors.fill: parent
                        source: detalhes.capa !== "" ? detalhes.capa : raiz.placeholder
                        fillMode: Image.PreserveAspectCrop
                        asynchronous: true
                        // Na resolução real da tela: a capa guardada tem mais pixels que a da grade.
                        sourceSize: Qt.size(raiz.larguraDaCapa * Screen.devicePixelRatio,
                                            raiz.alturaDaCapa * Screen.devicePixelRatio)
                    }
                    // Sempre toca aqui, a menos que a janela não esteja à vista.
                    AnimatedImage {
                        objectName: "capaAnimadaDaPagina"
                        readonly property bool aVista: Window.visibility !== Window.Minimized
                            && Window.visibility !== Window.Hidden
                        anchors.fill: parent
                        source: detalhes.capaAnimada !== "" && aVista ? detalhes.capaAnimada : ""
                        playing: aVista
                        visible: status === AnimatedImage.Ready
                        fillMode: Image.PreserveAspectCrop
                        asynchronous: true
                        cache: false
                    }
                }
                BusyIndicator {
                    objectName: "carregandoDaPagina"
                    anchors.centerIn: parent
                    running: detalhes.carregando
                    visible: detalhes.carregando
                    palette.dark: Tema.destaque
                }
            }

            // --- Os dados -------------------------------------------------------------------------
            ColumnLayout {
                Layout.preferredWidth: raiz.larguraDoTexto
                Layout.alignment: Qt.AlignVCenter
                spacing: 3

                // O logo (altura reservada só com ele) ou o título, nunca os dois.
                Item {
                    Layout.fillWidth: true
                    Layout.bottomMargin: 9
                    implicitHeight: raiz.logoVisivel ? 72 : titulo.implicitHeight

                    Image {
                        id: logo
                        objectName: "logoDoJogo"
                        visible: raiz.logoVisivel
                        anchors { left: parent.left; bottom: parent.bottom }
                        width: Math.min(detalhes.larguraDoLogo, parent.width)
                        height: 72
                        source: detalhes.logo
                        fillMode: Image.PreserveAspectFit
                        horizontalAlignment: Image.AlignLeft
                        verticalAlignment: Image.AlignBottom
                        asynchronous: false
                    }
                    Text {
                        id: titulo
                        objectName: "tituloDoJogo"
                        visible: !raiz.logoVisivel
                        width: parent.width
                        text: detalhes.nome
                        textFormat: Text.PlainText
                        wrapMode: Text.Wrap
                        color: Tema.texto
                        font { family: Tema.fonte; pixelSize: 28; weight: Font.Bold }
                    }
                }

                Dado {
                    objectName: "desenvolvedora"
                    Layout.topMargin: 3
                    text: detalhes.desenvolvedora
                    color: Tema.texto
                    font.weight: Font.DemiBold
                    font.pixelSize: 15
                }
                Dado { objectName: "publicadora"; text: detalhes.publicadora }
                Dado { objectName: "dataDeLancamento"; text: detalhes.dataDeLancamento }
                Dado { objectName: "nota"; text: detalhes.nota }
                Dado { objectName: "metacritic"; text: detalhes.metacritic }
                Dado { objectName: "avaliacoes"; text: detalhes.avaliacoes }
                Dado { objectName: "genero"; text: detalhes.genero }
                Dado { objectName: "controle"; text: detalhes.controle }
                Dado {
                    objectName: "controleRecomendado"
                    visible: detalhes.controleRecomendado
                    text: "★ Os desenvolvedores recomendam o uso de um controle."
                }
                Dado {
                    objectName: "descricao"
                    Layout.topMargin: 9
                    text: detalhes.descricao
                }

                // HowLongToBeat: um cartão de células ou a tabela de capítulos, nunca os dois.
                ColumnLayout {
                    id: blocoHltb
                    objectName: "blocoHltb"
                    Layout.topMargin: 15
                    visible: detalhes.hltb.celulas !== undefined
                        && (detalhes.hltb.celulas.length > 0 || detalhes.hltb.capitulos.length > 0)
                    spacing: 6

                    Text {
                        Layout.leftMargin: 3
                        text: "HowLongToBeat"
                        textFormat: Text.PlainText
                        color: Tema.textoSecundario
                        font { family: Tema.fonte; pixelSize: 12; weight: Font.DemiBold }
                    }
                    Rectangle {
                        objectName: "cartaoHltb"
                        visible: detalhes.hltb.celulas !== undefined && detalhes.hltb.celulas.length > 0
                        implicitWidth: celulas.implicitWidth
                        implicitHeight: celulas.implicitHeight
                        radius: 12
                        color: Tema.superficie
                        border { width: 1; color: Tema.borda }
                        Row {
                            id: celulas
                            Repeater {
                                model: detalhes.hltb.celulas
                                delegate: Row {
                                    required property var modelData
                                    Rectangle {
                                        visible: modelData.separador
                                        width: 1; height: 32; y: 10
                                        color: Tema.borda
                                    }
                                    Column {
                                        topPadding: 10; bottomPadding: 10; leftPadding: 18; rightPadding: 18
                                        spacing: 2
                                        Text {
                                            anchors.horizontalCenter: parent.horizontalCenter
                                            text: modelData.valor
                                            textFormat: Text.PlainText
                                            color: Tema.texto
                                            font { family: Tema.fonte; pixelSize: 17; weight: Font.Bold }
                                        }
                                        Text {
                                            anchors.horizontalCenter: parent.horizontalCenter
                                            text: modelData.rotulo
                                            textFormat: Text.PlainText
                                            color: Tema.textoSecundario
                                            font { family: Tema.fonte; pixelSize: 12 }
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
                        implicitHeight: tabela.implicitHeight + 20
                        radius: 12
                        color: Tema.superficie
                        border { width: 1; color: Tema.borda }
                        GridLayout {
                            id: tabela
                            x: 16; y: 10
                            columns: 4
                            columnSpacing: 20
                            rowSpacing: 4
                            Item { width: 1; height: 1 }
                            Repeater {
                                model: detalhes.hltb.colunas
                                delegate: Text {
                                    required property string modelData
                                    text: modelData
                                    textFormat: Text.PlainText
                                    color: Tema.textoSecundario
                                    font { family: Tema.fonte; pixelSize: 12 }
                                }
                            }
                            Repeater {
                                model: (detalhes.hltb.capitulos || []).length * 4
                                delegate: Text {
                                    required property int index
                                    readonly property var capitulo: detalhes.hltb.capitulos[Math.floor(index / 4)]
                                    text: index % 4 === 0 ? capitulo.rotulo : capitulo.valores[index % 4 - 1]
                                    textFormat: Text.PlainText
                                    color: index % 4 === 0 ? Tema.textoSecundario : Tema.texto
                                    font { family: Tema.fonte; pixelSize: 14 }
                                }
                            }
                        }
                    }
                }

                // As datas, o tempo de jogo e o tamanho.
                Flow {
                    Layout.fillWidth: true
                    Layout.topMargin: 12
                    spacing: 12
                    Repeater {
                        model: [detalhes.adicionado, detalhes.jogadoPorUltimo, detalhes.tempoDeJogo, detalhes.tamanho]
                        delegate: Text {
                            required property string modelData
                            visible: modelData !== ""
                            text: modelData
                            textFormat: Text.PlainText
                            color: Tema.texto
                            font { family: Tema.fonte; pixelSize: 14 }
                        }
                    }
                }

                Row {
                    Layout.topMargin: 9
                    spacing: 6
                    // shortcut: só o rótulo e a dica; o menu de status entra com o plano 3 (tarefa 3).
                    BotaoDeTexto {
                        id: botaoStatus
                        objectName: "botaoStatus"
                        text: detalhes.rotuloDoStatus
                        dica: "Status deste jogo na biblioteca"
                    }
                    // shortcut: sem a caixa de anotação, ela entra com a tarefa 3.
                    BotaoDeTexto {
                        id: botaoAnotacao
                        objectName: "botaoAnotacao"
                        visible: detalhes.mostraAnotacao
                        text: "Onde eu parei"
                        dica: detalhes.dicaDaAnotacao
                    }
                }

                // shortcut: sem ação ainda; abre a página da atualização na tarefa 3.
                BotaoDeTexto {
                    id: avisoDeAtualizacao
                    objectName: "avisoDeAtualizacao"
                    Layout.topMargin: 9
                    visible: detalhes.temAtualizacao
                    text: "Atualização disponível"
                    dica: "Abrir a página da atualização"
                    font.weight: Font.DemiBold
                }

                RowLayout {
                    Layout.topMargin: 18
                    spacing: 9

                    Button {
                        id: botaoJogar
                        objectName: "botaoJogarDaPagina"
                        visible: !detalhes.zerado
                        focusPolicy: Qt.StrongFocus
                        implicitWidth: 96
                        implicitHeight: 40
                        text: "Jogar"
                        Accessible.name: "Jogar"
                        onClicked: raiz.jogar()
                        contentItem: Text {
                            text: botaoJogar.text
                            textFormat: Text.PlainText
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                            color: "white"
                            font { family: Tema.fonte; pixelSize: 15; weight: Font.DemiBold }
                        }
                        background: Rectangle {
                            radius: 20
                            color: Tema.destaque
                            opacity: botaoJogar.down ? 0.75 : botaoJogar.hovered ? 0.9 : 1
                            border { width: botaoJogar.visualFocus ? 2 : 0; color: Tema.texto }
                        }
                    }
                    BotaoRedondo {
                        id: botaoEditar
                        objectName: "botaoEditar"
                        glifo: ""
                        dica: "Editar"
                        onClicked: raiz.editar()
                    }
                    BotaoRedondo {
                        id: botaoExcluir
                        objectName: "botaoExcluir"
                        visible: detalhes.zerado
                        glifo: ""
                        dica: "Excluir"
                        onClicked: raiz.excluir()
                    }
                    BotaoRedondo {
                        id: botaoRemover
                        objectName: "botaoRemover"
                        visible: !detalhes.zerado
                        glifo: ""
                        dica: "Remover"
                        onClicked: raiz.remover()
                    }
                    // shortcut: sem o menu de buscas, ele entra com a tarefa 3.
                    BotaoRedondo {
                        id: botaoBuscar
                        objectName: "botaoBuscarDaPagina"
                        visible: !detalhes.zerado
                        glifo: ""
                        dica: "Buscar"
                    }
                }
            }
        }
    }
}
