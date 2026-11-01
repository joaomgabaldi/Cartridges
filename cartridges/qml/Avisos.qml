import QtQuick

// O aviso (um por vez, com botão opcional) na parte de baixo e a confirmação do comando de um jogo restaurado.
// Os textos vão sempre em PlainText: nome de jogo e comando não são marcação.
Item {
    id: camada

    // Ponte, FilaDeAvisos e Aplicativo (cartridges/app.py)
    property QtObject ponte
    property QtObject fila
    property QtObject app
    // O AppUpdater (D82): a pergunta da versão nova e o download; null onde não há atualizador (testes).
    property QtObject atualizador
    // Com uma confirmação na tela, a janela não aceita atalhos arrastados.
    readonly property bool dialogoAberto: confirmacao.visible || dialogoDeErros.visible || confirmacaoDoApp.visible || dialogoDaAtualizacao.visible

    Connections {
        target: camada.ponte
        function onConfirmacaoPedida(titulo, corpo) {
            tituloDaConfirmacao.text = titulo
            corpoDaConfirmacao.text = corpo
            confirmacao.abrir()
        }
    }

    Connections {
        target: camada.app
        function onConfirmacaoPedida(titulo, corpo, rotulo, rotuloCancelar, destrutivo) {
            confirmacaoDoApp.titulo = titulo
            confirmacaoDoApp.corpo = corpo
            confirmacaoDoApp.rotuloConfirmar = rotulo
            confirmacaoDoApp.rotuloCancelar = rotuloCancelar
            confirmacaoDoApp.destrutivo = destrutivo
            confirmacaoDoApp.abrir()
        }
        function onDialogoPedido(titulo, corpo, itens) {
            dialogoDeErros.abrir(titulo, corpo, itens, camada.app.dialogoComPreferencias ? "Preferências" : "")
        }
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

        // 0 = Dispensar (o padrão), 1 = Iniciar. Teclado e controle acionam o botão em foco; Esc cancela.
        property int foco: 0
        property Item focoAnterior: null

        function abrir() {
            // Reaberto com o diálogo já à vista, o foco atual é o dele: o anterior continua valendo.
            if (!visible) focoAnterior = Window.window ? Window.window.activeFocusItem : null
            foco = 0  // barreira de segurança: Enter ou A logo ao abrir cancelam, nunca iniciam
            visible = true
            forceActiveFocus()
        }
        function acionar(indice) {
            visible = false
            // O que tinha o foco antes (a camada do Big Picture, um cartão) o retoma.
            if (focoAnterior && focoAnterior.visible && focoAnterior.enabled) focoAnterior.forceActiveFocus()
            focoAnterior = null
            if (indice === 1) camada.ponte.confirmar()
            else camada.ponte.cancelar()
        }

        focus: visible
        Keys.onLeftPressed: foco = 0
        Keys.onRightPressed: foco = 1
        Keys.onReturnPressed: acionar(foco)
        Keys.onEnterPressed: acionar(foco)
        Keys.onSpacePressed: acionar(foco)
        Keys.onEscapePressed: acionar(0)
        Keys.onPressed: event => event.accepted = true  // modal: nenhuma tecla chega à página de trás

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
                        model: [{ rotulo: "Dispensar", principal: false }, { rotulo: "Iniciar", principal: true }]
                        delegate: Rectangle {
                            id: botao
                            required property var modelData
                            required property int index
                            width: rotulo.implicitWidth + 40
                            height: 36
                            radius: 6
                            color: modelData.principal ? Tema.destaque : Tema.botaoSobre
                            border { width: 2; color: confirmacao.foco === botao.index ? Tema.texto : "transparent" }
                            Accessible.role: Accessible.Button
                            Accessible.name: modelData.rotulo
                            Text {
                                id: rotulo
                                anchors.centerIn: parent
                                text: botao.modelData.rotulo
                                color: botao.modelData.principal ? "white" : Tema.texto
                                font.family: Tema.fonte
                                font.pixelSize: 14
                            }
                            TapHandler { onTapped: confirmacao.acionar(botao.index) }
                        }
                    }
                }
            }
        }
    }

    DialogoDeAviso {
        id: dialogoDeErros
        objectName: "dialogoDeErros"
        onDispensado: camada.app.dialogoFechado(false)
        onSecundario: camada.app.dialogoFechado(true)
    }

    // A pergunta que o domínio faz (D72): restaurar um save, "Saves sem backup". Esc e o X valem "não".
    DialogoDeConfirmacao {
        id: confirmacaoDoApp
        objectName: "confirmacaoDoApp"
        onConfirmado: camada.app.confirmacaoRespondida(true)
        onCancelado: camada.app.confirmacaoRespondida(false)
    }

    // A versão nova (D82): fica por cima das Preferências, como as outras perguntas desta camada.
    DialogoDaAtualizacao {
        id: dialogoDaAtualizacao
        objectName: "dialogoDaAtualizacao"
        atualizador: camada.atualizador
        outroAberto: confirmacao.visible || dialogoDeErros.visible || confirmacaoDoApp.visible
    }
}
