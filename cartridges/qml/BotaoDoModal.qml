import QtQuick
import QtQuick.Controls.Basic

// O botão dos modais da restauração: em cápsula (os da `main` eram "pill"), com `destaque` na cor do sistema e
// `perigo` em vermelho (Excluir).
Button {
    id: botao

    property bool destaque: false
    property bool perigo: false

    focusPolicy: Qt.StrongFocus
    implicitHeight: 36
    leftPadding: 20
    rightPadding: 20
    Keys.onReturnPressed: click()
    Keys.onEnterPressed: click()
    contentItem: Text {
        text: botao.text
        textFormat: Text.PlainText
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        color: botao.destaque || botao.perigo ? "white" : Tema.texto
        font { family: Tema.fonte; pixelSize: 14 }
    }
    background: Rectangle {
        radius: height / 2
        color: botao.perigo ? "#c01c28" : botao.destaque ? Tema.destaque : Tema.superficie
        opacity: !botao.enabled ? 0.5 : botao.down ? 0.75 : botao.hovered ? 0.9 : 1
        border { width: botao.visualFocus ? 2 : 1; color: botao.visualFocus ? Tema.texto : Tema.borda }
    }
}
