import QtQuick
import QtQuick.Controls.Basic

// Uma linha que é só um botão com o título centralizado (o `Adw.ButtonRow`); `destrutivo` pinta de erro.
Item {
    id: linha

    property string titulo
    property bool destrutivo: false

    signal acionada()

    width: parent ? parent.width : implicitWidth
    implicitHeight: 48

    Rectangle {
        width: parent.width
        height: 1
        color: Tema.borda
        visible: linha.y > 0
    }

    Button {
        id: botao
        anchors.fill: parent
        focusPolicy: Qt.StrongFocus
        Accessible.name: linha.titulo
        Keys.onReturnPressed: click()
        Keys.onEnterPressed: click()
        onClicked: linha.acionada()
        contentItem: Text {
            text: linha.titulo
            textFormat: Text.PlainText
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            color: linha.destrutivo ? Tema.erro : Tema.texto
            font { family: Tema.fonte; pixelSize: 15 }
        }
        background: Rectangle {
            radius: 8
            color: botao.down ? Tema.pressionado : botao.hovered ? Tema.botaoSobre : "transparent"
            border { width: botao.visualFocus ? 2 : 0; color: Tema.destaque }
        }
    }
}
