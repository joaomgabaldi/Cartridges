import QtQuick

// O botão do controle (A, B, X ou Y) em círculo, nas cores do Xbox.
Rectangle {
    id: glifo
    objectName: "glifoDoBotao"

    property string letra: "A"
    property real tamanho: 22

    width: tamanho
    height: tamanho
    radius: tamanho / 2
    color: ({ "A": "#5fbf3f", "B": "#e0453a", "X": "#3a7be0", "Y": "#f2c21b" })[letra] ?? "#808080"

    Text {
        anchors.centerIn: parent
        text: glifo.letra
        textFormat: Text.PlainText
        color: "#111111"
        font { family: Tema.fonte; pixelSize: Math.round(glifo.tamanho * 0.6); weight: Font.Bold }
    }
}
