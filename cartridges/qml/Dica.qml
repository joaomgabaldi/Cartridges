import QtQuick
import QtQuick.Controls.Basic

// A dica (tooltip): fundo escuro translúcido, contorno branco a 10%, texto branco, raio 9, embaixo do item, centrada.
// Filho do item: `Dica { texto: "Buscar"; ativa: botao.hovered }`.
ToolTip {
    id: dica

    property string texto
    property bool ativa: false

    objectName: "dica"
    text: texto
    delay: 500
    // Para o botão que abre um diálogo: o Qt só vê o ponteiro sair quando ele anda, então o clique esconde a dica. Quem
    // abre balão não liga: a dica fica.
    property bool someAoClicar: false
    property bool _clicada: false
    onAtivaChanged: if (!ativa) _clicada = false
    Connections {
        target: dica.parent
        ignoreUnknownSignals: true
        function onPressedChanged() { if (dica.someAoClicar && dica.parent.pressed && dica.ativa) dica._clicada = true }
    }
    visible: ativa && !_clicada && texto !== ""
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
