import QtQuick
import QtQuick.Controls.Basic

// O item de menu do Tema: marca de seleção à esquerda e seta de submenu à direita.
MenuItem {
    id: item

    implicitHeight: 34
    implicitWidth: contentItem.implicitWidth + leftPadding + rightPadding
    leftPadding: 12
    rightPadding: 28

    contentItem: Text {
        leftPadding: item.checkable ? 22 : 0  // lugar da marca
        text: item.text
        color: Tema.texto
        opacity: item.enabled ? 1 : 0.5
        verticalAlignment: Text.AlignVCenter
        font { family: Tema.fonte; pixelSize: 14 }
    }
    indicator: Text {
        visible: item.checked
        x: 8
        anchors.verticalCenter: parent.verticalCenter
        text: ""  // marca de seleção
        font { family: Tema.fonteDeIcones; pixelSize: 12 }
        color: Tema.texto
    }
    arrow: Text {
        visible: item.subMenu
        x: parent.width - width - 10
        anchors.verticalCenter: parent.verticalCenter
        text: ""  // seta para a direita
        font { family: Tema.fonteDeIcones; pixelSize: 10 }
        color: Tema.textoSecundario
    }
    background: Rectangle {
        radius: 4
        color: item.highlighted ? Tema.botaoSobre : "transparent"
    }
}
