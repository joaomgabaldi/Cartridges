import QtQuick
import QtQuick.Controls.Basic

// O `Adw.ButtonRow`: o título em negrito, centralizado, em 40 de altura + 2 em cima e embaixo; `destrutivo` pinta de vermelho.
LinhaDoGrupo {
    id: linha

    property bool destrutivo: false

    signal acionada()

    alturaMinima: 40
    comTextos: false
    sobre: botao.hovered
    pressionada: botao.down
    foco: botao.visualFocus

    Button {
        id: botao
        objectName: linha.objectName + "Botao"
        anchors.fill: parent
        focusPolicy: Qt.StrongFocus
        hoverEnabled: true
        Accessible.name: linha.titulo
        Keys.onReturnPressed: click()
        Keys.onEnterPressed: click()
        onClicked: linha.acionada()
        contentItem: Text {
            text: linha.titulo
            textFormat: Text.PlainText
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            color: linha.destrutivo ? Tema.destrutivoTexto : Tema.texto
            font { family: Tema.fonte; pixelSize: Tema.corpo; weight: Tema.pesoForte }
        }
        background: Item {}
    }
}
