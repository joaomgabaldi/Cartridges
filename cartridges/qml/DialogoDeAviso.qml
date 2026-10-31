import QtQuick

// A confirmação de um aviso com título, corpo e, se houver, uma lista de itens (título e subtítulo).
// Os textos vão sempre em PlainText: caminhos e mensagens de erro não são marcação.
Rectangle {
    id: dialogo

    property string titulo
    property string corpo
    // [{ titulo, subtitulo }]
    property var itens: []
    property string rotuloDoBotao: "Dispensar"
    // O segundo botão (o padrão, como o `set_default_response` da `main`); vazio = escondido.
    property string rotuloSecundario: ""

    signal dispensado()
    signal secundario()

    function abrir(novoTitulo, novoCorpo, novosItens, novoRotuloSecundario) {
        titulo = novoTitulo
        corpo = novoCorpo
        itens = novosItens
        rotuloSecundario = novoRotuloSecundario || ""
        visible = true
        // Adiado: o item acabou de ficar visível e só então aceita o foco.
        Qt.callLater(() => {
            if (dialogo.visible) (dialogo.rotuloSecundario !== "" ? botaoSecundario : botao).forceActiveFocus(Qt.TabFocusReason)
        })
    }

    function acionarSecundario() {
        if (!visible) return
        visible = false
        secundario()
    }

    function fechar() {
        if (!visible) return
        visible = false
        dispensado()
    }

    anchors.fill: parent
    visible: false
    color: "#80000000"
    focus: visible
    Keys.onEscapePressed: fechar()
    Keys.onReturnPressed: fechar()
    Keys.onEnterPressed: fechar()
    // Modal: nenhuma tecla chega à página de trás.
    Keys.onPressed: event => event.accepted = true

    MouseArea { anchors.fill: parent } // a grade embaixo não recebe cliques

    Rectangle {
        anchors.centerIn: parent
        width: Math.min(460, parent.width - 48)
        height: coluna.implicitHeight + 48
        radius: 8
        color: Tema.fundo
        border.color: Tema.botaoSobre

        Column {
            id: coluna
            anchors { left: parent.left; right: parent.right; top: parent.top; margins: 24 }
            spacing: 16

            Text {
                objectName: "tituloDoDialogo"
                width: parent.width
                text: dialogo.titulo
                textFormat: Text.PlainText
                wrapMode: Text.Wrap
                color: Tema.texto
                font.family: Tema.fonte
                font.pixelSize: 18
                font.weight: Font.DemiBold
                Accessible.role: Accessible.Heading
                Accessible.name: text
            }
            Text {
                objectName: "corpoDoDialogo"
                width: parent.width
                visible: text !== ""
                text: dialogo.corpo
                textFormat: Text.PlainText
                wrapMode: Text.Wrap
                color: Tema.texto
                font.family: Tema.fonte
                font.pixelSize: 14
            }

            Flickable {
                id: rolagem
                visible: dialogo.itens.length > 0
                width: parent.width
                height: Math.min(contentHeight, 240)
                contentHeight: lista.implicitHeight
                clip: true
                interactive: contentHeight > height

                Column {
                    id: lista
                    objectName: "listaDoDialogo"
                    width: rolagem.width
                    spacing: 8

                    Repeater {
                        model: dialogo.itens
                        delegate: Rectangle {
                            id: linha
                            required property var modelData
                            width: lista.width
                            height: textos.implicitHeight + 20
                            radius: 6
                            color: Tema.superficie
                            border.color: Tema.borda

                            Column {
                                id: textos
                                anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; margins: 12 }
                                spacing: 2
                                Text {
                                    objectName: "itemTitulo"
                                    width: parent.width
                                    text: linha.modelData.titulo
                                    textFormat: Text.PlainText
                                    wrapMode: Text.Wrap
                                    color: Tema.texto
                                    font.family: Tema.fonte
                                    font.pixelSize: 14
                                    font.weight: Font.DemiBold
                                }
                                Text {
                                    objectName: "itemSubtitulo"
                                    width: parent.width
                                    visible: text !== ""
                                    text: linha.modelData.subtitulo
                                    textFormat: Text.PlainText
                                    wrapMode: Text.Wrap
                                    color: Tema.textoSecundario
                                    font.family: Tema.fonte
                                    font.pixelSize: 13
                                }
                            }
                        }
                    }
                }
            }

            Row {
                anchors.right: parent.right
                spacing: 8

                Rectangle {
                    id: botao
                    objectName: "botaoDoDialogo"
                    width: rotulo.implicitWidth + 40
                    height: 36
                    radius: 6
                    color: dialogo.rotuloSecundario !== "" ? Tema.botaoSobre : Tema.destaque
                    border { width: 2; color: activeFocus ? Tema.texto : "transparent" }
                    activeFocusOnTab: true
                    Accessible.role: Accessible.Button
                    Accessible.name: rotulo.text
                    Keys.onTabPressed: (botaoSecundario.visible ? botaoSecundario : botao).forceActiveFocus(Qt.TabFocusReason)
                    Keys.onBacktabPressed: (botaoSecundario.visible ? botaoSecundario : botao).forceActiveFocus(Qt.BacktabFocusReason)
                    Keys.onReturnPressed: dialogo.fechar()
                    Keys.onEnterPressed: dialogo.fechar()
                    Text {
                        id: rotulo
                        anchors.centerIn: parent
                        text: dialogo.rotuloDoBotao
                        textFormat: Text.PlainText
                        color: dialogo.rotuloSecundario !== "" ? Tema.texto : "white"
                        font.family: Tema.fonte
                        font.pixelSize: 14
                    }
                    TapHandler { onTapped: dialogo.fechar() }
                }

                Rectangle {
                    id: botaoSecundario
                    objectName: "botaoSecundarioDoDialogo"
                    visible: dialogo.rotuloSecundario !== ""
                    width: rotuloDoSecundario.implicitWidth + 40
                    height: 36
                    radius: 6
                    color: Tema.botaoSobre
                    border { width: 2; color: activeFocus ? Tema.texto : "transparent" }
                    activeFocusOnTab: true
                    Accessible.role: Accessible.Button
                    Accessible.name: rotuloDoSecundario.text
                    Keys.onTabPressed: botao.forceActiveFocus(Qt.TabFocusReason)
                    Keys.onBacktabPressed: botao.forceActiveFocus(Qt.BacktabFocusReason)
                    Keys.onReturnPressed: dialogo.acionarSecundario()
                    Keys.onEnterPressed: dialogo.acionarSecundario()
                    Text {
                        id: rotuloDoSecundario
                        anchors.centerIn: parent
                        text: dialogo.rotuloSecundario
                        textFormat: Text.PlainText
                        color: Tema.texto
                        font.family: Tema.fonte
                        font.pixelSize: 14
                    }
                    TapHandler { onTapped: dialogo.acionarSecundario() }
                }
            }
        }
    }
}
