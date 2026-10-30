import QtQuick

// A placa do "Identificar monitores": o número da tela, grande, num quadrado (a janela é do `window_geometry`, D68).
Rectangle {
    id: placa
    objectName: "placaDoMonitor"

    property string numero: ""

    implicitWidth: 200
    implicitHeight: 200
    color: "#1c1b22"
    border { width: 3; color: Tema.destaque }

    Text {
        anchors.centerIn: parent
        text: placa.numero
        textFormat: Text.PlainText
        color: "white"
        font { family: Tema.fonte; pixelSize: placa.height * 0.55; weight: Font.Bold }
    }
}
