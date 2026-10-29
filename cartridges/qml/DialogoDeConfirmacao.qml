import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Window

// Uma pergunta com dois botões. O texto vai sempre em PlainText (nome de jogo e URL não são marcação).
// Esc e fechar valem como cancelar; o foco inicial vai ao botão de confirmar, salvo se a ação é destrutiva.
Rectangle {
    id: dialogo

    property string titulo
    property string corpo
    property string rotuloConfirmar: "Confirmar"
    property string rotuloCancelar: "Cancelar"
    property bool destrutivo: false

    signal confirmado()
    signal cancelado()

    // Quem tinha o foco ao abrir: volta a tê-lo ao fechar.
    property Item retorno: null

    function abrir() {
        retorno = Window.window ? Window.window.activeFocusItem : null
        visible = true;
        (destrutivo ? botaoCancelar : botaoConfirmar).forceActiveFocus(Qt.TabFocusReason)
    }
    function resolver(confirmou) {
        if (!visible) return
        visible = false
        if (retorno) retorno.forceActiveFocus(Qt.TabFocusReason)
        if (confirmou) confirmado()
        else cancelado()
    }

    anchors.fill: parent
    z: 10
    visible: false
    color: "#80000000"
    focus: visible
    Keys.onEscapePressed: resolver(false)
    // Modal para o teclado e o controle: nenhuma tecla chega à página de trás.
    Keys.onPressed: event => event.accepted = true

    MouseArea { anchors.fill: parent } // o que está embaixo não recebe cliques

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
                font { family: Tema.fonte; pixelSize: 18; weight: Font.DemiBold }
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
                font { family: Tema.fonte; pixelSize: 14 }
            }
            Row {
                anchors.right: parent.right
                spacing: 8

                component BotaoDoDialogo: Button {
                    id: botao
                    property color cor: Tema.superficie
                    property color corDoTexto: Tema.texto
                    focusPolicy: Qt.StrongFocus
                    implicitHeight: 36
                    leftPadding: 20
                    rightPadding: 20
                    // Esquerda, direita e Tab ficam entre os dois botões.
                    property Item outro
                    Keys.onLeftPressed: outro.forceActiveFocus(Qt.TabFocusReason)
                    Keys.onRightPressed: outro.forceActiveFocus(Qt.TabFocusReason)
                    Keys.onTabPressed: outro.forceActiveFocus(Qt.TabFocusReason)
                    Keys.onBacktabPressed: outro.forceActiveFocus(Qt.BacktabFocusReason)
                    Keys.onReturnPressed: click()
                    Keys.onEnterPressed: click()
                    contentItem: Text {
                        text: botao.text
                        textFormat: Text.PlainText
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                        color: botao.corDoTexto
                        font { family: Tema.fonte; pixelSize: 14 }
                    }
                    background: Rectangle {
                        radius: 6
                        color: botao.cor
                        opacity: botao.down ? 0.75 : botao.hovered ? 0.9 : 1
                        border { width: botao.visualFocus ? 2 : 1; color: botao.visualFocus ? Tema.texto : Tema.borda }
                    }
                }

                BotaoDoDialogo {
                    id: botaoCancelar
                    outro: botaoConfirmar
                    objectName: "botaoCancelarDoDialogo"
                    text: dialogo.rotuloCancelar
                    onClicked: dialogo.resolver(false)
                }
                BotaoDoDialogo {
                    id: botaoConfirmar
                    outro: botaoCancelar
                    objectName: "botaoConfirmarDoDialogo"
                    text: dialogo.rotuloConfirmar
                    cor: dialogo.destrutivo ? "#c01c28" : Tema.destaque
                    corDoTexto: "white"
                    onClicked: dialogo.resolver(true)
                }
            }
        }
    }
}
