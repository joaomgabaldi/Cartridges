import QtQuick

// O aviso embaixo e os diálogos que o domínio pede. Os textos vão em PlainText: nome de jogo e comando não são marcação.
Item {
    id: camada

    property QtObject ponte
    property QtObject fila
    property QtObject app
    property QtObject atualizador
    property Item lugarDoAviso: null
    signal retornoPerdido()
    readonly property bool dialogoAberto: confirmacao.aberto || preparo.aberto || dialogoDeErros.aberto || confirmacaoDoApp.aberto || dialogoDaAtualizacao.aberto

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
        function onPreparoPedido(titulo, corpo) {
            preparo.titulo = titulo
            preparo.corpo = corpo
            camada.subir(preparo)
            preparo.aberto = true
            Qt.callLater(preparo.focarInicial)
        }
        // Fechar pelo `aberto`, e não pelo `responder`: a busca acabou e ninguém respondeu.
        function onPreparoTerminou() { preparo.aberto = false }
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

    // Barreira de segurança: Enter ou A logo ao abrir cancelam, nunca iniciam o comando; o foco começa em "Dispensar".
    DialogoDeAlerta {
        id: confirmacao
        objectName: "confirmacaoDoComando"
        respostas: [{ id: "dispensar", rotulo: "Dispensar", objeto: "botaoDispensarComando" },
                    { id: "iniciar", rotulo: "Iniciar", objeto: "botaoIniciarComando" }]
        respostaDeEscape: "dispensar"
        respostaInicial: "dispensar"
        onRespondido: resposta => resposta === "iniciar" ? camada.ponte.confirmar() : camada.ponte.cancelar()
    }

    DialogoDeAlerta {
        id: preparo
        objectName: "dialogoDoPreparo"
        respostas: [{ id: "cancelar", rotulo: "Cancelar", objeto: "botaoCancelarPreparo" },
                    { id: "jogar", rotulo: "Iniciar mesmo assim", objeto: "botaoJogarMesmoAssim" }]
        respostaDeEscape: "cancelar"
        respostaInicial: "cancelar"
        onRespondido: resposta => resposta === "jogar" ? camada.ponte.jogarMesmoAssim() : camada.ponte.cancelarPreparo()
    }

    DialogoDeAviso {
        id: dialogoDeErros
        objectName: "dialogoDeErros"
        naPilha: true
        onDispensado: camada.app.dialogoFechado(false)
        onSecundario: camada.app.dialogoFechado(true)
    }

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
