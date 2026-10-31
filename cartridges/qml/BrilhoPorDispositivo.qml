import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Window

// "Brilho máximo por dispositivo", por cima das Preferências: uma linha de número por fita. Só desenha: o que ele
// mostra e grava é o `preferencias.brilhoPorDispositivo` (cartridges/modelos/preferencias.py), que existe só
// enquanto a janela está aberta. Cada mudança acende as fitas no número dela; só o Salvar grava. Esc cancela.
Rectangle {
    id: dialogo
    objectName: "dialogoDoBrilhoPorDispositivo"

    readonly property var modelo: preferencias.brilhoPorDispositivo
    // Quem tinha o foco ao abrir: volta a tê-lo ao fechar.
    property Item retorno: null

    Accessible.role: Accessible.Dialog
    Accessible.name: "Brilho máximo por dispositivo"

    anchors.fill: parent
    z: 10
    visible: !!modelo
    color: "#80000000"
    Keys.onEscapePressed: modelo.cancelar()
    // Modal para o teclado e o controle: nenhuma tecla chega às Preferências de trás (que ficam apagadas). O Tab passa,
    // para circular entre o Salvar, o Cancelar e as caixas.
    Keys.onPressed: event => event.accepted = event.key !== Qt.Key_Tab && event.key !== Qt.Key_Backtab

    function devolverAoRetorno() {
        if (!visible && retorno && retorno.visible && retorno.enabled) retorno.forceActiveFocus(Qt.TabFocusReason)
    }
    onVisibleChanged: {
        if (visible) {
            retorno = Window.window ? Window.window.activeFocusItem : null
            // Depois de o `visible` assentar, como no `DialogoDeConfirmacao`.
            Qt.callLater(() => { if (visible) botaoSalvar.forceActiveFocus(Qt.TabFocusReason) })
        } else {
            // Depois das Preferências de trás voltarem a ficar habilitadas.
            Qt.callLater(devolverAoRetorno)
        }
    }

    MouseArea { anchors.fill: parent } // o que está embaixo não recebe cliques

    component BotaoDoCabecalho: Button {
        id: botao
        property bool destaque: false
        focusPolicy: Qt.StrongFocus
        implicitHeight: 34
        leftPadding: 16
        rightPadding: 16
        Keys.onReturnPressed: click()
        Keys.onEnterPressed: click()
        contentItem: Text {
            text: botao.text
            textFormat: Text.PlainText
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            color: botao.destaque ? "white" : Tema.texto
            font { family: Tema.fonte; pixelSize: 14 }
        }
        background: Rectangle {
            radius: 6
            color: botao.destaque ? Tema.destaque : Tema.superficie
            opacity: botao.down ? 0.75 : botao.hovered ? 0.9 : 1
            border { width: botao.visualFocus ? 2 : 1; color: botao.visualFocus ? Tema.texto : Tema.borda }
        }
    }

    Rectangle {
        anchors.centerIn: parent
        width: Math.min(420, parent.width - 48)
        height: Math.min(coluna.implicitHeight + cabecalho.height + 32, parent.height - 48)
        radius: 8
        color: Tema.fundo
        border.color: Tema.botaoSobre
        clip: true

        Item {
            id: cabecalho
            width: parent.width
            height: 56

            BotaoDoCabecalho {
                objectName: "botaoCancelarDoBrilho"
                anchors { left: parent.left; leftMargin: 12; verticalCenter: parent.verticalCenter }
                text: "Cancelar"
                onClicked: dialogo.modelo.cancelar()
            }
            Text {
                anchors.centerIn: parent
                text: "Brilho máximo por dispositivo"
                textFormat: Text.PlainText
                color: Tema.texto
                font { family: Tema.fonte; pixelSize: 15; weight: Font.DemiBold }
                Accessible.role: Accessible.Heading
                Accessible.name: text
            }
            BotaoDoCabecalho {
                id: botaoSalvar
                objectName: "botaoSalvarDoBrilho"
                anchors { right: parent.right; rightMargin: 12; verticalCenter: parent.verticalCenter }
                text: "Salvar"
                destaque: true
                onClicked: dialogo.modelo.salvar()
            }
            Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Tema.borda }
        }

        Flickable {
            anchors { left: parent.left; right: parent.right; top: cabecalho.bottom; bottom: parent.bottom }
            contentWidth: width
            contentHeight: coluna.implicitHeight + 32
            boundsBehavior: Flickable.StopAtBounds
            clip: true
            ScrollBar.vertical: BarraDeRolagem {}

            Column {
                id: coluna
                x: 16
                y: 16
                width: parent.width - 32
                spacing: 8

                Text {
                    width: parent.width
                    text: "Brilho máximo de cada dispositivo, em porcentagem. O brilho definido nas Preferências e em cada jogo é aplicado proporcionalmente sobre estes valores."
                    textFormat: Text.PlainText
                    wrapMode: Text.Wrap
                    color: Tema.textoSecundario
                    font { family: Tema.fonte; pixelSize: 13 }
                }
                GrupoDeLinhas {
                    width: parent.width
                    Repeater {
                        model: dialogo.modelo ? dialogo.modelo.linhas : []
                        LinhaDeNumero {
                            required property var modelData
                            objectName: "brilhoDoDispositivo-" + modelData.id
                            // O nome é texto de fora (a conta da Tuya): a `LinhaDeNumero` o mostra em PlainText.
                            titulo: modelData.nome
                            de: 1
                            ate: 100
                            passo: 1
                            value: modelData.brilho
                            onAlterado: valor => {
                                value = valor
                                dialogo.modelo.mudar(modelData.id, valor)
                            }
                        }
                    }
                }
            }
        }
    }
}
