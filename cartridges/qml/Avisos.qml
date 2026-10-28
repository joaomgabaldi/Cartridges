import QtQuick

// O aviso (um por vez, com botão opcional) na parte de baixo e a confirmação do comando de um jogo restaurado.
// Os textos vão sempre em PlainText: nome de jogo e comando não são marcação.
Item {
    id: camada

    // Ponte, FilaDeAvisos e Aplicativo (cartridges/app.py)
    property QtObject ponte
    property QtObject fila
    property QtObject app
    // Com uma confirmação na tela, a janela não aceita atalhos arrastados.
    readonly property bool dialogoAberto: confirmacao.visible || dialogoDeErros.visible

    Connections {
        target: camada.ponte
        function onConfirmacaoPedida(titulo, corpo) {
            tituloDaConfirmacao.text = titulo
            corpoDaConfirmacao.text = corpo
            confirmacao.visible = true
        }
    }

    Connections {
        target: camada.app
        function onDialogoPedido(titulo, corpo, itens) { dialogoDeErros.abrir(titulo, corpo, itens) }
    }

    Rectangle {
        id: aviso
        anchors { bottom: parent.bottom; bottomMargin: 24; horizontalCenter: parent.horizontalCenter }
        objectName: "aviso"
        width: Math.min(textoDoAviso.implicitWidth + 40 + (botaoDoAviso.visible ? botaoDoAviso.width + 8 : 0), parent.width - 48)
        height: 44
        radius: height / 2
        color: Tema.barra
        border.color: Tema.botaoSobre
        opacity: camada.fila && camada.fila.visivel ? 1 : 0
        visible: opacity > 0
        Behavior on opacity { NumberAnimation { duration: Tema.duracaoCurta } }

        // O corpo do aviso não deixa o clique passar para a grade por baixo.
        MouseArea { anchors.fill: parent; enabled: aviso.visible }

        Text {
            id: textoDoAviso
            objectName: "textoDoAviso"
            anchors {
                left: parent.left; leftMargin: 20; top: parent.top; bottom: parent.bottom
                right: botaoDoAviso.visible ? botaoDoAviso.left : parent.right
                rightMargin: botaoDoAviso.visible ? 8 : 20
            }
            text: camada.fila ? camada.fila.texto : ""
            verticalAlignment: Text.AlignVCenter
            horizontalAlignment: botaoDoAviso.visible ? Text.AlignLeft : Text.AlignHCenter
            textFormat: Text.PlainText
            elide: Text.ElideRight
            color: Tema.texto
            font.family: Tema.fonte
            font.pixelSize: 14
        }

        Text {
            id: botaoDoAviso
            objectName: "botaoDoAviso"
            anchors { right: parent.right; rightMargin: 16; verticalCenter: parent.verticalCenter }
            visible: camada.fila && camada.fila.botao !== ""
            text: camada.fila ? camada.fila.botao : ""
            textFormat: Text.PlainText
            color: Tema.destaque
            font { family: Tema.fonte; pixelSize: 14; weight: Font.DemiBold }
            padding: 6
            Accessible.role: Accessible.Button
            Accessible.name: text
            // Só o botão recebe o toque; o resto do aviso não esconde a grade por baixo.
            TapHandler { onTapped: camada.fila.clicar() }
        }
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

    DialogoDeAviso {
        id: dialogoDeErros
        objectName: "dialogoDeErros"
        onDispensado: camada.app.dialogoFechado()
    }
}
