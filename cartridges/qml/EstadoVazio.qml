import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Shapes

// O aviso de página sem jogos, como o Adw.StatusPage da versão anterior.
Item {
    id: estado

    // Glifo da Segoe Fluent Icons: E721 buscar, E73E marca de seleção.
    property string glifo
    // O ícone simbólico do app (o da `main` em "Nenhum jogo").
    property bool iconeDoApp: false
    property string titulo
    property string descricao
    // Sem texto, não há botão.
    property string rotuloDoBotao
    property bool botaoHabilitado: true
    signal botaoClicado()

    Column {
        anchors.centerIn: parent
        width: Math.min(parent.width - 48, 420)
        spacing: 12

        Item {
            visible: estado.iconeDoApp
            anchors.horizontalCenter: parent.horizontalCenter
            width: 64
            height: 64
          Shape {
            width: 16
            height: 16
            scale: 4
            transformOrigin: Item.TopLeft
            ShapePath {
                fillColor: Tema.textoSecundario
                strokeColor: "transparent"
                fillRule: ShapePath.OddEvenFill
                PathSvg { path: "M3 3C1.89543 3 1 3.89543 1 5V11C1 12.1046 1.89543 13 3 13H13C14.1046 13 15 12.1046 15 11V5C15 3.89543 14.1046 3 13 3H3ZM6 5C5.44772 5 5 5.44772 5 6V10C5 10.5523 5.44772 11 6 11H10C10.5523 11 11 10.5523 11 10V6C11 5.44772 10.5523 5 10 5H6ZM12 8C12 7.44772 12.4477 7 13 7C13.5523 7 14 7.44772 14 8C14 8.55228 13.5523 9 13 9C12.4477 9 12 8.55228 12 8ZM3 7C2.44772 7 2 7.44772 2 8C2 8.55228 2.44772 9 3 9C3.55228 9 4 8.55228 4 8C4 7.44772 3.55228 7 3 7Z" }
            }
          }
        }
        Text {
            visible: estado.glifo !== "" && !estado.iconeDoApp
            anchors.horizontalCenter: parent.horizontalCenter
            text: estado.glifo
            font.family: Tema.fonteDeIcones
            font.pixelSize: 64
            color: Tema.textoSecundario
        }
        Text {
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
            textFormat: Text.PlainText
            text: estado.titulo
            color: Tema.texto
            font { family: Tema.fonte; pixelSize: 26; weight: Font.Bold }
        }
        Text {
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
            textFormat: Text.PlainText
            text: estado.descricao
            color: Tema.textoSecundario
            font { family: Tema.fonte; pixelSize: 15 }
        }
        Button {
            id: botao
            visible: estado.rotuloDoBotao !== ""
            anchors.horizontalCenter: parent.horizontalCenter
            enabled: estado.botaoHabilitado
            text: estado.rotuloDoBotao
            onClicked: estado.botaoClicado()
            implicitHeight: 40
            leftPadding: 28
            rightPadding: 28
            contentItem: Text {
                text: botao.text
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
                color: "white"
                font { family: Tema.fonte; pixelSize: 15; weight: Font.DemiBold }
            }
            background: Rectangle {
                radius: height / 2
                color: Tema.destaque
                opacity: !botao.enabled ? 0.4 : botao.down ? 0.75 : botao.hovered ? 0.9 : 1
            }
        }
    }
}
