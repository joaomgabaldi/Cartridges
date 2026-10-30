import QtQuick
import QtQuick.Controls.Basic

// Uma linha com título e uma lista de opções (ComboBox), do diálogo de edição.
Item {
    id: linha

    property string titulo
    property alias model: caixa.model
    property alias currentIndex: caixa.currentIndex
    // A largura da caixa; quem tem opções mais longas que o padrão a alarga.
    property int larguraDaCaixa: 180

    // A pessoa escolheu uma opção (o índice).
    signal escolhido(int indice)

    width: parent ? parent.width : implicitWidth
    implicitHeight: 58

    Rectangle {
        width: parent.width
        height: 1
        color: Tema.borda
        visible: linha.y > 0
    }

    Text {
        anchors { left: parent.left; leftMargin: 16; right: caixa.left; rightMargin: 12; verticalCenter: parent.verticalCenter }
        text: linha.titulo
        textFormat: Text.PlainText
        wrapMode: Text.Wrap
        color: Tema.texto
        font { family: Tema.fonte; pixelSize: 15 }
    }

    ComboBox {
        id: caixa
        objectName: linha.objectName + "Caixa"
        anchors { right: parent.right; rightMargin: 12; verticalCenter: parent.verticalCenter }
        implicitWidth: linha.larguraDaCaixa
        implicitHeight: 34
        focusPolicy: Qt.StrongFocus
        Accessible.name: linha.titulo
        onActivated: indice => linha.escolhido(indice)

        contentItem: Text {
            leftPadding: 12
            rightPadding: 30
            text: caixa.displayText
            textFormat: Text.PlainText
            elide: Text.ElideRight
            verticalAlignment: Text.AlignVCenter
            color: Tema.texto
            font { family: Tema.fonte; pixelSize: 14 }
        }
        indicator: Text {
            x: caixa.width - width - 10
            y: (caixa.height - height) / 2
            text: ""  // seta para baixo
            textFormat: Text.PlainText
            color: Tema.textoSecundario
            font { family: Tema.fonteDeIcones; pixelSize: 10 }
        }
        background: Rectangle {
            radius: 6
            color: caixa.hovered ? Tema.botaoSobre : Tema.fundo
            border { width: caixa.visualFocus ? 2 : 1; color: caixa.visualFocus ? Tema.destaque : Tema.borda }
        }
        delegate: ItemDelegate {
            id: opcao
            required property var modelData
            required property int index
            width: caixa.width
            implicitHeight: 34
            highlighted: caixa.highlightedIndex === index
            contentItem: Text {
                text: opcao.modelData
                textFormat: Text.PlainText
                elide: Text.ElideRight
                verticalAlignment: Text.AlignVCenter
                color: Tema.texto
                font { family: Tema.fonte; pixelSize: 14; weight: caixa.currentIndex === opcao.index ? Font.DemiBold : Font.Normal }
            }
            background: Rectangle { radius: 4; color: opcao.highlighted ? Tema.botaoSobre : "transparent" }
        }
        popup: Popup {
            y: caixa.height + 2
            width: caixa.width
            implicitHeight: contentItem.implicitHeight + 2 * padding
            padding: 4
            // Dentro da janela, como os menus do Tema.
            popupType: Popup.Item
            contentItem: ListView {
                clip: true
                implicitHeight: contentHeight
                model: caixa.popup.visible ? caixa.delegateModel : null
                currentIndex: caixa.highlightedIndex
            }
            background: Rectangle {
                radius: 8
                color: Tema.superficie
                border.color: Tema.borda
            }
        }
    }
}
