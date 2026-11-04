import QtQuick

// A placa do "Identificar monitores": o número da tela, grande, num quadrado.
Rectangle {
    id: placa
    objectName: "placaDoMonitor"

    property string numero: ""

    implicitWidth: 200
    implicitHeight: 200
    color: Tema.fundo  // fundo e texto do tema, sem borda
    border.width: 0

    Text {
        anchors.centerIn: parent
        text: placa.numero
        textFormat: Text.PlainText
        color: Tema.texto
        font { family: Tema.fonte; pixelSize: 128; weight: Font.Bold }  // 96 pt
    }
}
