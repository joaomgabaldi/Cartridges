import QtQuick
import QtQuick.Controls.Basic

// A página "Baixando…" dos seletores: 280 de largura, espaços de 12, o título, a barra e o
// tamanho esmaecido, com algarismos de largura fixa. Sem total conhecido (`progresso` negativo ou sem texto), a barra só pulsa.
Column {
    id: tela

    // De 0 a 1, ou -1 quando o servidor não informa o tamanho.
    property real progresso: -1
    property string texto
    property string nomeDaBarra
    readonly property alias barra: barra

    width: 280
    spacing: 12

    Text {
        width: parent.width
        text: "Baixando…"
        textFormat: Text.PlainText
        horizontalAlignment: Text.AlignHCenter
        color: Tema.texto
        font { family: Tema.fonte; pixelSize: Tema.titulo3; weight: Tema.pesoTitulo3 }
    }
    ProgressBar {
        id: barra
        objectName: tela.nomeDaBarra
        width: parent.width
        from: 0
        to: 1
        indeterminate: tela.progresso < 0 || tela.texto === ""
        value: Math.max(0, tela.progresso)
        implicitHeight: 8
        background: Rectangle { radius: 4; color: Tema.mistura(0.15) }
        contentItem: Item {
            clip: true
            Rectangle {
                visible: !barra.indeterminate
                width: barra.visualPosition * parent.width
                height: parent.height
                radius: 4
                color: Tema.destaque
            }
            // Sem total: um trecho que vai e volta.
            Rectangle {
                id: pulso
                visible: barra.indeterminate
                width: parent.width * 0.3
                height: parent.height
                radius: 4
                color: Tema.destaque
                SequentialAnimation on x {
                    running: pulso.visible && Tema.animacoes
                    loops: Animation.Infinite
                    NumberAnimation { from: 0; to: pulso.parent.width * 0.7; duration: 700; easing.type: Easing.InOutSine }
                    NumberAnimation { from: pulso.parent.width * 0.7; to: 0; duration: 700; easing.type: Easing.InOutSine }
                }
            }
        }
    }
    Text {
        width: parent.width
        text: tela.texto
        textFormat: Text.PlainText
        horizontalAlignment: Text.AlignHCenter
        color: Tema.textoSecundario
        font { family: Tema.fonte; pixelSize: Tema.corpo; features: ({ "tnum": 1 }) }
    }
}
