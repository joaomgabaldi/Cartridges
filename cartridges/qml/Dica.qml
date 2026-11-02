import QtQuick
import QtQuick.Controls.Basic

// A dica (tooltip) da libadwaita: fundo rgba(0,0,6,.8), contorno branco a 10%, texto branco, raio 9, padding 6/10,
// embaixo do item, centrada. Filho do item: `Dica { texto: "Buscar"; ativa: botao.hovered }`.
ToolTip {
    id: dica

    property string texto
    property bool ativa: false

    objectName: "dica"
    text: texto
    delay: 500
    visible: ativa && texto !== ""
    popupType: Popup.Item
    margins: 6
    x: parent ? Math.round((parent.width - width) / 2) : 0
    y: parent ? parent.height + 6 : 0
    leftPadding: 10
    rightPadding: 10
    topPadding: 6
    bottomPadding: 6
    closePolicy: Popup.NoAutoClose
    contentItem: Text {
        text: dica.text
        textFormat: Text.PlainText
        wrapMode: Text.Wrap
        color: "white"
        font { family: Tema.fonte; pixelSize: Tema.corpo }
    }
    background: Rectangle {
        radius: 9
        color: Qt.rgba(0, 0, 6 / 255, 0.8)
        border { width: 1; color: Qt.rgba(1, 1, 1, 0.1) }
    }
    enter: null
    exit: null
}
