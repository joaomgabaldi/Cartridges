import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Window

// A base dos modais da continuação da restauração (D81): a cortina, o cartão com título e X, o foco e o Esc. Só
// desenha: o que cada um mostra e faz é o `restauracao` (cartridges/modelos/restauracao.py). Modal para o mouse, o
// teclado e o controle; o foco inicial vai ao `inicial` (depois de o `visible` assentar) e, ao fechar, volta a quem o
// tinha. Sem `fechavel`, nem o Esc nem o X saem (a pasta de atalhos é obrigatória).
Rectangle {
    id: modal

    property bool aberto: false
    property string titulo
    property real largura: 480
    property bool fechavel: true
    // Quem recebe o foco ao abrir.
    property Item inicial: null
    // Quem tinha o foco ao abrir: volta a tê-lo ao fechar.
    property Item retorno: null
    default property alias conteudo: coluna.data

    // Esc ou X.
    signal saiu()
    // Quem abriu sumiu (a lista foi relida): a janela decide para onde vai o foco.
    signal retornoPerdido()

    function focarInicial() {
        if (inicial) inicial.forceActiveFocus(Qt.TabFocusReason)
    }
    function devolverAoRetorno() {
        if (visible) return
        if (retorno && retorno.visible && retorno.enabled) retorno.forceActiveFocus(Qt.TabFocusReason)
        else retornoPerdido()
    }

    Accessible.role: Accessible.Dialog
    Accessible.name: titulo

    anchors.fill: parent
    visible: aberto
    color: "#80000000"
    Keys.onEscapePressed: if (fechavel) saiu()
    // Modal para o teclado e o controle: nenhuma tecla chega à página de trás. O Tab passa, para circular.
    Keys.onPressed: event => event.accepted = event.key !== Qt.Key_Tab && event.key !== Qt.Key_Backtab

    onVisibleChanged: {
        if (visible) {
            retorno = Window.window ? Window.window.activeFocusItem : null
            Qt.callLater(() => { if (visible) focarInicial() })
        } else {
            // Depois de a página de trás voltar a ficar habilitada.
            Qt.callLater(devolverAoRetorno)
        }
    }

    MouseArea { anchors.fill: parent } // o que está embaixo não recebe cliques

    Rectangle {
        anchors.centerIn: parent
        width: Math.min(modal.largura, parent.width - 48)
        height: Math.min(cabecalho.height + coluna.implicitHeight + 24, parent.height - 48)
        radius: 8
        color: Tema.fundo
        border.color: Tema.botaoSobre
        clip: true

        Item {
            id: cabecalho
            width: parent.width
            height: 56

            Text {
                objectName: "tituloDoModal"
                anchors {
                    left: parent.left; leftMargin: 24; right: modal.fechavel ? botaoFechar.left : parent.right
                    rightMargin: 12; verticalCenter: parent.verticalCenter
                }
                text: modal.titulo
                textFormat: Text.PlainText
                elide: Text.ElideRight
                color: Tema.texto
                font { family: Tema.fonte; pixelSize: 15; weight: Font.DemiBold }
                Accessible.role: Accessible.Heading
                Accessible.name: text
            }
            Button {
                id: botaoFechar
                objectName: "botaoFecharDoModal"
                visible: modal.fechavel
                anchors { right: parent.right; rightMargin: 12; verticalCenter: parent.verticalCenter }
                implicitWidth: 34
                implicitHeight: 34
                focusPolicy: Qt.StrongFocus
                Accessible.name: "Fechar"
                Keys.onReturnPressed: click()
                Keys.onEnterPressed: click()
                onClicked: modal.saiu()
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

        Column {
            id: coluna
            anchors { left: parent.left; right: parent.right; top: cabecalho.bottom; leftMargin: 24; rightMargin: 24 }
            spacing: 18
        }
    }
}
