import QtQuick

// O aviso simples na parte de baixo e a confirmação do comando de um jogo restaurado.
// Os textos vão sempre em PlainText: nome de jogo e comando não são marcação.
Item {
    id: camada

    // Ponte (cartridges/app.py)
    property QtObject ponte

    Connections {
        target: camada.ponte
        function onAvisoRecebido(texto) {
            textoDoAviso.text = texto
            aviso.opacity = 1
            relogio.restart()
        }
        function onConfirmacaoPedida(titulo, corpo) {
            tituloDaConfirmacao.text = titulo
            corpoDaConfirmacao.text = corpo
            confirmacao.visible = true
        }
    }

    Rectangle {
        id: aviso
        anchors { bottom: parent.bottom; bottomMargin: 24; horizontalCenter: parent.horizontalCenter }
        width: Math.min(textoDoAviso.implicitWidth + 40, parent.width - 48)
        height: 44
        radius: height / 2
        color: Tema.barra
        border.color: Tema.botaoSobre
        opacity: 0
        visible: opacity > 0
        Behavior on opacity { NumberAnimation { duration: Tema.duracaoCurta } }

        Text {
            id: textoDoAviso
            anchors { fill: parent; leftMargin: 20; rightMargin: 20 }
            verticalAlignment: Text.AlignVCenter
            horizontalAlignment: Text.AlignHCenter
            textFormat: Text.PlainText
            elide: Text.ElideRight
            color: Tema.texto
            font.family: Tema.fonte
            font.pixelSize: 14
        }

        Timer { id: relogio; interval: 4000; onTriggered: aviso.opacity = 0 }
    }

    Rectangle {
        id: confirmacao
        anchors.fill: parent
        visible: false
        color: "#80000000"

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
                    id: tituloDaConfirmacao
                    width: parent.width
                    textFormat: Text.PlainText
                    wrapMode: Text.Wrap
                    color: Tema.texto
                    font.family: Tema.fonte
                    font.pixelSize: 18
                    font.weight: Font.DemiBold
                }
                Text {
                    id: corpoDaConfirmacao
                    width: parent.width
                    textFormat: Text.PlainText
                    wrapMode: Text.Wrap
                    color: Tema.texto
                    font.family: Tema.fonte
                    font.pixelSize: 14
                }
                Row {
                    spacing: 8
                    anchors.right: parent.right

                    Repeater {
                        model: [{ rotulo: "Cancelar", principal: false }, { rotulo: "Iniciar", principal: true }]
                        delegate: Rectangle {
                            id: botao
                            required property var modelData
                            width: rotulo.implicitWidth + 40
                            height: 36
                            radius: 6
                            color: modelData.principal ? Tema.destaque : Tema.botaoSobre
                            Text {
                                id: rotulo
                                anchors.centerIn: parent
                                text: botao.modelData.rotulo
                                color: botao.modelData.principal ? "white" : Tema.texto
                                font.family: Tema.fonte
                                font.pixelSize: 14
                            }
                            TapHandler {
                                onTapped: {
                                    confirmacao.visible = false
                                    if (botao.modelData.principal) camada.ponte.confirmar()
                                    else camada.ponte.cancelar()
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
