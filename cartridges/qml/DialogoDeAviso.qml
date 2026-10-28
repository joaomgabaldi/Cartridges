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

    signal dispensado()

    function abrir(novoTitulo, novoCorpo, novosItens) {
        titulo = novoTitulo
        corpo = novoCorpo
        itens = novosItens
        visible = true
        forceActiveFocus()
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

            Rectangle {
                id: botao
                objectName: "botaoDoDialogo"
                anchors.right: parent.right
                width: rotulo.implicitWidth + 40
                height: 36
                radius: 6
                color: Tema.destaque
                Accessible.role: Accessible.Button
                Accessible.name: rotulo.text
                Text {
                    id: rotulo
                    anchors.centerIn: parent
                    text: dialogo.rotuloDoBotao
                    textFormat: Text.PlainText
                    color: "white"
                    font.family: Tema.fonte
                    font.pixelSize: 14
                }
                TapHandler { onTapped: dialogo.fechar() }
            }
        }
    }
}
