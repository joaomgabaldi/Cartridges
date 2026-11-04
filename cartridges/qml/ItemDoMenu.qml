import QtQuick
import QtQuick.Controls.Basic

// O item de menu (modelbutton): 32 de altura, raio 9, 10% ao passar e 19% pressionado, marca à esquerda e seta do
// submenu (`go-next`, a 30%) à direita. `radio`: a marca é a bolinha do `radio` do GTK, com aro também desligada.
MenuItem {
    id: item

    property bool radio: false

    implicitHeight: 32
    implicitWidth: contentItem.implicitWidth + leftPadding + rightPadding
    leftPadding: 12
    rightPadding: item.subMenu ? 34 : 12
    hoverEnabled: true

    contentItem: Text {
        leftPadding: item.checkable ? 22 : 0  // lugar da marca
        text: item.text
        textFormat: Text.PlainText
        color: Tema.texto
        opacity: item.enabled ? 1 : Tema.opacidadeDesabilitado
        verticalAlignment: Text.AlignVCenter
        font { family: Tema.fonte; pixelSize: Tema.corpo }
    }
    indicator: Item {
        x: 12
        anchors.verticalCenter: parent.verticalCenter
        width: 16
        height: 16
        visible: item.checkable
        Icone {
            anchors.centerIn: parent
            visible: !item.radio && item.checked
            nome: "object-select"
            tamanho: 14
        }
        Rectangle {
            anchors.centerIn: parent
            visible: item.radio
            width: 14
            height: 14
            radius: 7
            color: "transparent"
            border { width: 1; color: Tema.mistura(0.3) }
            Rectangle {
                anchors.centerIn: parent
                visible: item.checked
                width: 6
                height: 6
                radius: 3
                color: Tema.texto
            }
        }
    }
    arrow: Icone {
        visible: !!item.subMenu
        x: parent.width - width - 12
        anchors.verticalCenter: parent.verticalCenter
        nome: "go-next"
        opacity: 0.3
    }
    background: Rectangle {
        radius: 9
        color: item.down ? Tema.menuPressionado : item.highlighted ? Tema.menuSobre : "transparent"
    }
}
