import QtQuick
import QtQuick.Controls.Basic

// Uma linha com título, explicação e uma caixa de número (o `Adw.SpinRow`). `alterado` leva o número que a
// pessoa pediu; quem usa grava e devolve o valor em `value` (a caixa só mostra o que a linha recebe).
Item {
    id: linha

    property string titulo
    property string subtitulo
    property int de: 0
    property int ate: 100
    property int passo: 1
    // Quanto PageUp e PageDown andam.
    property int pagina: 10
    property int value: 0

    signal alterado(int valor)

    width: parent ? parent.width : implicitWidth
    implicitHeight: Math.max(textos.implicitHeight, 34) + 24

    Rectangle {
        width: parent.width
        height: 1
        color: Tema.borda
        visible: linha.y > 0
    }

    Column {
        id: textos
        anchors { left: parent.left; leftMargin: 16; right: caixa.left; rightMargin: 12; verticalCenter: parent.verticalCenter }
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
            width: parent.width
            visible: text !== ""
            text: linha.subtitulo
            textFormat: Text.PlainText
            wrapMode: Text.Wrap
            color: Tema.textoSecundario
            font { family: Tema.fonte; pixelSize: 12 }
        }
    }

    SpinBox {
        id: caixa
        objectName: linha.objectName + "Caixa"
        anchors { right: parent.right; rightMargin: 16; verticalCenter: parent.verticalCenter }
        from: linha.de
        to: linha.ate
        stepSize: linha.passo
        focusPolicy: Qt.StrongFocus
        Accessible.name: linha.titulo
        onValueModified: linha.alterado(value)
        Keys.onPressed: event => {
            var delta = event.key === Qt.Key_PageUp ? linha.pagina : event.key === Qt.Key_PageDown ? -linha.pagina : 0
            if (delta === 0) return
            event.accepted = true
            linha.alterado(Math.max(linha.de, Math.min(linha.ate, value + delta)))
        }
        contentItem: Text {
            text: caixa.value
            textFormat: Text.PlainText
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            color: Tema.texto
            font { family: Tema.fonte; pixelSize: 15 }
        }
        up.indicator: Text {
            x: caixa.width - width - 8
            anchors.verticalCenter: parent.verticalCenter
            text: "+"
            textFormat: Text.PlainText
            color: caixa.up.pressed ? Tema.destaque : Tema.texto
            opacity: caixa.enabled ? 1 : 0.4
            font { family: Tema.fonte; pixelSize: 18 }
        }
        down.indicator: Text {
            x: 8
            anchors.verticalCenter: parent.verticalCenter
            text: "−"
            textFormat: Text.PlainText
            color: caixa.down.pressed ? Tema.destaque : Tema.texto
            opacity: caixa.enabled ? 1 : 0.4
            font { family: Tema.fonte; pixelSize: 18 }
        }
        background: Rectangle {
            implicitWidth: 104
            implicitHeight: 34
            radius: 6
            color: "transparent"
            border { width: caixa.visualFocus ? 2 : 1; color: caixa.visualFocus ? Tema.destaque : Tema.borda }
        }
    }

    // O valor da linha manda na caixa, mesmo depois de a pessoa mexer nela.
    Binding { target: caixa; property: "value"; value: linha.value }
}
