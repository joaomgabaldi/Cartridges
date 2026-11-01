import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Window

// "Restaurar save": uma linha por versão guardada dos saves do jogo, da mais recente à mais antiga. Só desenha: o que
// mostra e faz é o `saves` (cartridges/modelos/saves.py); escolher uma linha pede a confirmação do app. Modal para o
// mouse, o teclado e o controle; Esc fecha e o foco volta ao cartão que abriu o menu.
Rectangle {
    id: dialogo
    objectName: "dialogoDeVersoes"

    // Quem tinha o foco ao abrir: volta a tê-lo ao fechar.
    property Item retorno: null

    Accessible.role: Accessible.Dialog
    Accessible.name: "Restaurar save"

    anchors.fill: parent
    visible: saves.aberto
    color: "#80000000"
    Keys.onEscapePressed: saves.fechar()
    // Modal para o teclado e o controle: nenhuma tecla chega à página de trás. O Tab passa, para circular.
    Keys.onPressed: event => event.accepted = event.key !== Qt.Key_Tab && event.key !== Qt.Key_Backtab

    function devolverAoRetorno() {
        if (visible) return
        // Quem abriu pode ter sumido (o menu do jogo fechou ao escolher "Restaurar save"): o foco vai à página à vista.
        if (retorno && retorno !== Window.contentItem && retorno.visible && retorno.enabled) retorno.forceActiveFocus(Qt.TabFocusReason)
        else dialogo.retornoPerdido()
    }
    signal retornoPerdido()
    onVisibleChanged: {
        if (visible) {
            retorno = Window.window ? Window.window.activeFocusItem : null
            lista.contentY = 0
            // Depois de o `visible` assentar, como no `DialogoDeConfirmacao`.
            Qt.callLater(() => { if (visible) botaoFechar.forceActiveFocus(Qt.TabFocusReason) })
        } else {
            // Depois de a página de trás voltar a ficar habilitada.
            Qt.callLater(devolverAoRetorno)
        }
    }

    MouseArea { anchors.fill: parent } // o que está embaixo não recebe cliques

    Rectangle {
        anchors.centerIn: parent
        width: Math.min(420, parent.width - 48)
        height: Math.min(cabecalho.height + lista.contentHeight + 24, 56 + 420 + 24, parent.height - 48)
        radius: 8
        color: Tema.fundo
        border.color: Tema.botaoSobre
        clip: true

        Item {
            id: cabecalho
            width: parent.width
            height: 56

            Text {
                anchors { left: parent.left; leftMargin: 24; verticalCenter: parent.verticalCenter }
                text: "Restaurar save"
                textFormat: Text.PlainText
                color: Tema.texto
                font { family: Tema.fonte; pixelSize: 15; weight: Font.DemiBold }
                Accessible.role: Accessible.Heading
                Accessible.name: text
            }
            Button {
                id: botaoFechar
                objectName: "botaoFecharDasVersoes"
                anchors { right: parent.right; rightMargin: 12; verticalCenter: parent.verticalCenter }
                implicitWidth: 34
                implicitHeight: 34
                focusPolicy: Qt.StrongFocus
                Accessible.name: "Fechar"
                Keys.onReturnPressed: click()
                Keys.onEnterPressed: click()
                onClicked: saves.fechar()
                contentItem: Text {
                    text: ""  // X
                    textFormat: Text.PlainText
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    color: Tema.texto
                    font { family: Tema.fonteDeIcones; pixelSize: 14 }
                }
                background: Rectangle {
                    radius: 6
                    color: botaoFechar.down ? Tema.pressionado : botaoFechar.hovered ? Tema.botaoSobre : "transparent"
                    border { width: botaoFechar.visualFocus ? 2 : 0; color: Tema.texto }
                }
            }
        }

        ListView {
            id: lista
            objectName: "listaDeVersoes"
            anchors {
                left: parent.left; right: parent.right; top: cabecalho.bottom; bottom: parent.bottom
                leftMargin: 24; rightMargin: 24; bottomMargin: 24
            }
            model: saves.versoes
            spacing: 4
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: BarraDeRolagem {}

            // Move o foco para a linha `indice + passo`, limitado às pontas; a rolagem acompanha.
            function irPara(indice, passo) {
                var alvo = Math.max(0, Math.min(count - 1, indice + passo))
                positionViewAtIndex(alvo, ListView.Contain)
                var item = itemAtIndex(alvo)
                if (item) item.forceActiveFocus(Qt.TabFocusReason)
            }

            delegate: Button {
                id: linha
                required property int index
                required property var modelData
                objectName: "versao-" + modelData.id
                width: ListView.view.width
                implicitHeight: 56
                focusPolicy: Qt.StrongFocus
                leftPadding: 16
                rightPadding: 16
                Accessible.name: modelData.titulo + (modelData.subtitulo !== "" ? ", " + modelData.subtitulo : "")
                Keys.onReturnPressed: click()
                Keys.onEnterPressed: click()
                Keys.onUpPressed: lista.irPara(index, -1)
                Keys.onDownPressed: lista.irPara(index, 1)
                Keys.onPressed: event => {
                    if (event.key === Qt.Key_PageUp) { lista.irPara(index, -5); event.accepted = true }
                    else if (event.key === Qt.Key_PageDown) { lista.irPara(index, 5); event.accepted = true }
                }
                onClicked: saves.escolher(modelData.id)

                contentItem: Item {
                    Column {
                        anchors { left: parent.left; right: seta.left; rightMargin: 8; verticalCenter: parent.verticalCenter }
                        spacing: 2
                        Text {
                            objectName: "tituloDaVersao"
                            width: parent.width
                            text: linha.modelData.titulo
                            textFormat: Text.PlainText
                            elide: Text.ElideRight
                            color: Tema.texto
                            font { family: Tema.fonte; pixelSize: 14 }
                        }
                        Text {
                            objectName: "subtituloDaVersao"
                            width: parent.width
                            visible: text !== ""
                            text: linha.modelData.subtitulo
                            textFormat: Text.PlainText
                            wrapMode: Text.Wrap
                            color: Tema.textoSecundario
                            font { family: Tema.fonte; pixelSize: 12 }
                        }
                    }
                    Text {
                        id: seta
                        anchors { right: parent.right; verticalCenter: parent.verticalCenter }
                        text: ""  // seta para a direita
                        textFormat: Text.PlainText
                        color: Tema.textoSecundario
                        font { family: Tema.fonteDeIcones; pixelSize: 12 }
                    }
                }
                background: Rectangle {
                    radius: 6
                    color: linha.down ? Tema.pressionado : linha.hovered ? Tema.botaoSobre : Tema.superficie
                    border { width: linha.visualFocus ? 2 : 1; color: linha.visualFocus ? Tema.texto : Tema.borda }
                }
            }
        }
    }
}
