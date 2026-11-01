import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Window

// A página Novidades (D83): os posts do feed, em linhas que expandem. Tudo vem de `novidades`
// (cartridges/modelos/novidades.py); o texto do feed é de terceiros e sempre em PlainText.
Item {
    id: raiz

    signal voltar()

    // O que o controle do Xbox e a janela esperam de qualquer página (ver Aplicativo.qml).
    readonly property bool menuDoJogoAberto: false
    readonly property bool comLista: novidades.estado === "lista"

    function focarInicial() {
        if (comLista) irPara(Math.max(0, lista.currentIndex))
        else if (novidades.estado === "vazio") vazio.forceActiveFocus(Qt.TabFocusReason)
    }
    function focarGrade() { focarInicial() }
    function focoNaLista() {
        var item = Window.window ? Window.window.activeFocusItem : null
        while (item) {
            if (item === lista) return true
            item = item.parent
        }
        return false
    }
    function mostrarSelecao() {}
    function abrirMenuDoAtual() {}
    function xDoAtual() { return raiz.mapToItem(null, raiz.width / 2, 0).x }
    // Só ↑ e ↓ andam pelas linhas; devolve se o foco mudou.
    function moverSelecao(dx, dy) {
        if (!comLista) return false
        if (dy === 0) return false
        var i = lista.currentIndex + dy
        if (i < 0 || i >= lista.count) return false
        irPara(i)
        return true
    }
    function irPara(i) {
        lista.currentIndex = i
        lista.positionViewAtIndex(i, ListView.Contain)
        var linha = lista.itemAtIndex(i)
        if (linha) linha.forceActiveFocus(Qt.TabFocusReason)
    }
    // O A do controle: expande a linha do foco (ou tenta de novo).
    function abrirDetalhesDoAtual() {
        var foco = Window.window ? Window.window.activeFocusItem : null
        if (foco && foco.alternar) foco.alternar()
        else if (foco && foco.click) foco.click()
    }

    focus: true
    Keys.onEscapePressed: voltar()

    // Aberta, a página reconhece os posts; fechada, deixa de reconhecê-los (D83).
    StackView.onStatusChanged: novidades.paginaVisivel(StackView.status === StackView.Active || StackView.status === StackView.Activating)
    // Depois do foco que a própria StackView dá à página ao ativá-la.
    StackView.onActivated: Qt.callLater(() => focarInicial())

    // Cobre a biblioteca por baixo durante a transição.
    Rectangle { anchors.fill: parent; color: Tema.fundo; z: -1 }

    Connections {
        target: novidades
        function onListaRefeita() {
            lista.positionViewAtBeginning()
            // Aberta em "carregando", o foco ficou na raiz: com a lista pronta ele vai à primeira linha.
            if (raiz.StackView.status === StackView.Active && !focoNaLista()) Qt.callLater(raiz.focarInicial)
        }
    }

    BusyIndicator {
        objectName: "carregandoNovidades"
        anchors.centerIn: parent
        visible: novidades.estado === "carregando"
        running: visible
        implicitWidth: 32
        implicitHeight: 32
        Accessible.name: "Carregando"
    }

    EstadoVazio {
        id: vazio
        objectName: "novidadesVazias"
        anchors.fill: parent
        visible: novidades.estado === "vazio"
        glifo: "\uE8A1"
        titulo: "Sem novidades"
        descricao: "Não foi possível carregar as novidades."
        rotuloDoBotao: "Tentar novamente"
        onBotaoClicado: novidades.atualizar()
    }

    ListView {
        id: lista
        objectName: "listaDasNovidades"
        // Coluna de até 800, como o `Adw.Clamp` da `main`.
        width: Math.min(800, parent.width - 24)
        height: parent.height
        anchors.horizontalCenter: parent.horizontalCenter
        visible: raiz.comLista
        model: novidades.posts
        spacing: 12
        topMargin: 18
        bottomMargin: 18
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: BarraDeRolagem {}

        delegate: Item {
            id: linha

            required property int index
            required property var modelData
            // Sem resumo nem link não há o que abrir: a linha é simples, sem seta.
            readonly property bool expansivel: modelData.resumo !== "" || modelData.url !== ""
            property bool aberta: false

            function alternar() { if (expansivel) aberta = !aberta }

            // Uma parada de Tab por linha; ↑ e ↓ andam entre elas, Enter e Espaço expandem.
            activeFocusOnTab: true
            Accessible.role: Accessible.Button
            Accessible.name: modelData.titulo
            onActiveFocusChanged: if (activeFocus) lista.currentIndex = index
            Keys.onUpPressed: raiz.moverSelecao(0, -1)
            Keys.onDownPressed: raiz.moverSelecao(0, 1)
            Keys.onRightPressed: if (expansivel) aberta = true
            Keys.onLeftPressed: aberta = false
            Keys.onReturnPressed: alternar()
            Keys.onEnterPressed: alternar()
            Keys.onSpacePressed: alternar()

            width: lista.width
            height: cartao.height

            Rectangle {
                id: cartao
                width: parent.width
                height: cabecalho.height + (linha.aberta ? corpo.height : 0)
                radius: 10
                color: Tema.superficie
                border.width: linha.activeFocus && linha.focusReason === Qt.TabFocusReason ? 2 : 1
                border.color: linha.activeFocus && linha.focusReason === Qt.TabFocusReason ? Tema.destaque : Tema.borda
                clip: true

                Item {
                    id: cabecalho
                    width: parent.width
                    height: textos.height + 24

                    Column {
                        id: textos
                        x: 16
                        y: 12
                        width: parent.width - 32 - (linha.expansivel ? 28 : 0)
                        spacing: 2
                        Text {
                            width: parent.width
                            text: linha.modelData.titulo
                            textFormat: Text.PlainText
                            wrapMode: Text.Wrap
                            color: Tema.texto
                            font { family: Tema.fonte; pixelSize: 15; weight: Font.DemiBold }
                        }
                        Text {
                            width: parent.width
                            visible: text !== ""
                            text: linha.modelData.subtitulo
                            textFormat: Text.PlainText
                            wrapMode: Text.Wrap
                            color: Tema.textoSecundario
                            font { family: Tema.fonte; pixelSize: 13 }
                        }
                    }
                    Text {
                        visible: linha.expansivel
                        anchors { right: parent.right; rightMargin: 16; verticalCenter: parent.verticalCenter }
                        text: linha.aberta ? "\uE70E" : "\uE70D"
                        font { family: Tema.fonteDeIcones; pixelSize: 12 }
                        color: Tema.textoSecundario
                    }
                    MouseArea {
                        anchors.fill: parent
                        cursorShape: linha.expansivel ? Qt.PointingHandCursor : Qt.ArrowCursor
                        onClicked: { linha.alternar(); linha.forceActiveFocus(Qt.MouseFocusReason) }
                    }
                }

                Column {
                    id: corpo
                    y: cabecalho.height
                    width: parent.width
                    visible: linha.aberta
                    leftPadding: 16
                    rightPadding: 16
                    bottomPadding: 12
                    spacing: 12
                    Text {
                        visible: linha.modelData.resumo !== ""
                        width: parent.width - 32
                        text: linha.modelData.resumo
                        textFormat: Text.PlainText
                        wrapMode: Text.Wrap
                        color: Tema.texto
                        font { family: Tema.fonte; pixelSize: 14 }
                    }
                    Button {
                        id: abrir
                        objectName: "abrirNoNavegador"
                        visible: linha.modelData.url !== ""
                        text: "Abrir no navegador"
                        onClicked: novidades.abrirNoNavegador(linha.modelData.url)
                        implicitHeight: 34
                        leftPadding: 16
                        rightPadding: 16
                        Accessible.name: text
                        contentItem: Row {
                            spacing: 8
                            Text {
                                anchors.verticalCenter: parent.verticalCenter
                                text: abrir.text
                                textFormat: Text.PlainText
                                color: Tema.texto
                                font { family: Tema.fonte; pixelSize: 14 }
                            }
                            Text {
                                anchors.verticalCenter: parent.verticalCenter
                                text: "\uE8A7"
                                color: Tema.textoSecundario
                                font { family: Tema.fonteDeIcones; pixelSize: 12 }
                            }
                        }
                        background: Rectangle {
                            radius: 6
                            color: abrir.down ? Tema.pressionado : abrir.hovered ? Tema.botaoSobre : "transparent"
                            border.width: abrir.visualFocus ? 2 : 1
                            border.color: abrir.visualFocus ? Tema.destaque : Tema.borda
                        }
                    }
                }
            }
        }
    }
}
