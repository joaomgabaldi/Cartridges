import QtQuick

// O aviso embaixo (um por vez, com botão opcional) e os diálogos que o domínio pede. Os textos vão sempre em PlainText:
// nome de jogo e comando não são marcação.
Item {
    id: camada

    property QtObject ponte
    property QtObject fila
    property QtObject app
    // O AppUpdater (pergunta da versão nova e download); null onde não há atualizador (testes).
    property QtObject atualizador
    // O aviso fica abaixo dos diálogos; as Preferências têm o delas.
    property Item lugarDoAviso: null
    signal retornoPerdido()
    readonly property bool dialogoAberto: confirmacao.aberto || dialogoDeErros.aberto || confirmacaoDoApp.aberto || dialogoDaAtualizacao.aberto

    // A pilha dos diálogos: o último a abrir fica por cima.
    property int ordem: 10
    function subir(dialogo) { dialogo.z = ++ordem }

    Connections {
        target: camada.ponte
        function onConfirmacaoPedida(titulo, corpo) {
            confirmacao.titulo = titulo
            confirmacao.corpo = corpo
            camada.subir(confirmacao)
            confirmacao.aberto = true
            Qt.callLater(confirmacao.focarInicial)
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
            camada.subir(confirmacaoDoApp)
            confirmacaoDoApp.abrir()
        }
        function onDialogoPedido(titulo, corpo, itens) {
            camada.subir(dialogoDeErros)
            dialogoDeErros.abrir(titulo, corpo, itens, camada.app.dialogoComPreferencias ? "Preferências" : "")
        }
    }

    Rectangle {
        id: aviso
        parent: camada.lugarDoAviso ? camada.lugarDoAviso : camada
        z: 100
        anchors { bottom: parent.bottom; bottomMargin: 24; horizontalCenter: parent.horizontalCenter }
        objectName: "aviso"
        readonly property real _botoes: fecharDoAviso.width + 6 + (botaoDoAviso.visible ? botaoDoAviso.width + 6 : 0)
        width: Math.min(textoDoAviso.implicitWidth + _botoes + 18, parent.width - 24)
        height: 46
        radius: height / 2
        color: Tema.aviso
        opacity: camada.fila && camada.fila.visivel ? 1 : 0
        visible: opacity > 0
        Behavior on opacity { NumberAnimation { duration: Tema.duracaoCurta; easing { type: Easing.Bezier; bezierCurve: Tema.curva } } }

        Sombra { camadas: Tema.sombraAviso; raio: aviso.radius }

        // O corpo do aviso não deixa o clique passar para a grade por baixo; com o mouse em cima, o tempo para.
        MouseArea { anchors.fill: parent; enabled: aviso.visible }
        HoverHandler {
            enabled: aviso.visible
            onHoveredChanged: {
                if (!camada.fila) return
                if (hovered) camada.fila.pausar()
                else camada.fila.retomar()
            }
        }

        Row {
            id: linhaDoAviso
            anchors { left: parent.left; leftMargin: 12; verticalCenter: parent.verticalCenter }
            spacing: 6

            Text {
                id: textoDoAviso
                objectName: "textoDoAviso"
                anchors.verticalCenter: parent.verticalCenter
                leftPadding: 6
                rightPadding: 6
                width: aviso.width - aviso._botoes - 18
                text: camada.fila ? camada.fila.texto : ""
                textFormat: Text.PlainText
                elide: Text.ElideRight
                color: "white"
                font { family: Tema.fonte; pixelSize: Tema.corpo }
            }
            Botao {
                id: botaoDoAviso
                objectName: "botaoDoAviso"
                anchors.verticalCenter: parent.verticalCenter
                estilo: "plano"
                corDoTexto: "white"
                afastamentoDoAnel: 1
                visible: camada.fila && camada.fila.botao !== ""
                text: camada.fila ? camada.fila.botao : ""
                focusPolicy: Qt.NoFocus
                onClicked: camada.fila.clicar()
            }
            Botao {
                id: fecharDoAviso
                objectName: "fecharDoAviso"
                anchors.verticalCenter: parent.verticalCenter
                estilo: "plano"
                circular: true
                corDoTexto: "white"
                afastamentoDoAnel: 1
                icone: "window-close"
                focusPolicy: Qt.NoFocus
                Accessible.name: "Fechar"
                onClicked: camada.fila.fechar()
            }
        }
    }

    // Barreira de segurança: Enter ou A logo ao abrir cancelam, nunca iniciam o comando; o foco começa em "Dispensar". O
    // que tinha o foco antes (a camada do Big Picture, um cartão) o retoma.
    DialogoDeAlerta {
        id: confirmacao
        objectName: "confirmacaoDoComando"
        respostas: [{ id: "dispensar", rotulo: "Dispensar", objeto: "botaoDispensarComando" },
                    { id: "iniciar", rotulo: "Iniciar", objeto: "botaoIniciarComando" }]
        respostaDeEscape: "dispensar"
        respostaInicial: "dispensar"
        onRespondido: resposta => resposta === "iniciar" ? camada.ponte.confirmar() : camada.ponte.cancelar()
    }

    DialogoDeAviso {
        id: dialogoDeErros
        objectName: "dialogoDeErros"
        naPilha: true
        onDispensado: camada.app.dialogoFechado(false)
        onSecundario: camada.app.dialogoFechado(true)
    }

    // Esc e o X valem "não".
    DialogoDeConfirmacao {
        id: confirmacaoDoApp
        objectName: "confirmacaoDoApp"
        naPilha: true
        onConfirmado: camada.app.confirmacaoRespondida(true)
        onCancelado: camada.app.confirmacaoRespondida(false)
    }

    DialogoDaAtualizacao {
        id: dialogoDaAtualizacao
        objectName: "dialogoDaAtualizacao"
        atualizador: camada.atualizador
        onAbertoChanged: if (aberto) camada.subir(dialogoDaAtualizacao)
        onRetornoPerdido: camada.retornoPerdido()
    }
}
