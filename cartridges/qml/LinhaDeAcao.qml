import QtQuick
import QtQuick.Controls.Basic

// Uma linha com título, subtítulo e, à direita, um glifo ou o rótulo de um botão. A linha inteira aciona
// (como o `activatable-widget` do Adwaita). Os textos vão em PlainText: o subtítulo pode ser um caminho.
Item {
    id: linha

    property string titulo
    property string subtitulo
    property string glifo
    property string rotulo
    property string dica

    signal acionada()

    width: parent ? parent.width : implicitWidth
    implicitHeight: Math.max(textos.implicitHeight, 34) + 24

    Rectangle {
        width: parent.width
        height: 1
        color: Tema.borda
        visible: linha.y > 0
    }

    Button {
        id: botao
        objectName: linha.objectName + "Botao"
        anchors.fill: parent
        focusPolicy: Qt.StrongFocus
        Accessible.name: linha.dica !== "" ? linha.dica : linha.titulo
        Accessible.role: Accessible.Button
        ToolTip.visible: hovered && linha.dica !== ""
        ToolTip.text: linha.dica
        ToolTip.delay: 600
        Keys.onReturnPressed: click()
        Keys.onEnterPressed: click()
        onClicked: linha.acionada()
        contentItem: Item {}
        background: Rectangle {
            radius: 8
            color: botao.down ? Tema.pressionado : botao.hovered ? Tema.botaoSobre : "transparent"
            border { width: botao.visualFocus ? 2 : 0; color: Tema.destaque }
        }
    }

    Column {
        id: textos
        anchors { left: parent.left; leftMargin: 16; right: lado.left; rightMargin: 12; verticalCenter: parent.verticalCenter }
        spacing: 2
        Text {
            width: parent.width
            text: linha.titulo
            textFormat: Text.PlainText
            wrapMode: Text.Wrap
            color: Tema.texto
            font { family: Tema.fonte; pixelSize: 15 }
        }
        Text {
            objectName: linha.objectName + "Subtitulo"
            width: parent.width
            visible: text !== ""
            text: linha.subtitulo
            textFormat: Text.PlainText
            wrapMode: Text.WrapAnywhere
            color: Tema.textoSecundario
            font { family: Tema.fonte; pixelSize: 12 }
        }
    }

    Text {
        id: lado
        anchors { right: parent.right; rightMargin: 16; verticalCenter: parent.verticalCenter }
        text: linha.glifo !== "" ? linha.glifo : linha.rotulo
        textFormat: Text.PlainText
        color: Tema.texto
        font { family: linha.glifo !== "" ? Tema.fonteDeIcones : Tema.fonte; pixelSize: linha.glifo !== "" ? 16 : 14 }
    }
}
