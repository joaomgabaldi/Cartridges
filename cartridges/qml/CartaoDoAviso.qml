import QtQuick
import QtQuick.Effects

// O cartão do aviso de conquista (o `montar_cartao` da `main`): ícone, rótulo, título e descrição.
// A janela por cima do jogo (`janela_do_aviso.py`) é só ele; o assistente e o "exemplo" das
// Preferências mostram o mesmo cartão. Os textos são de terceiros: sempre texto puro.
Item {
    id: cartao
    objectName: "cartaoDoAviso"

    property string rotulo: ""
    property string titulo: ""
    property string descricao: ""
    property string icone: ""  // URL `file:` do ícone já baixado; vazio = a estrela
    property bool opaco: false  // a reserva sem transparência: fundo cheio e cantos retos
    property real opacidade: 1
    // Mudar anima a opacidade até 1 (true) ou 0 (false); `terminou` no fim de cada animação.
    property bool mostrado: false
    signal terminou()

    readonly property int raio: opaco ? 0 : 12
    readonly property real larguraMaxima: medida.averageCharacterWidth * 36  // max-width-chars: 36

    opacity: opacidade
    implicitWidth: 3 + 12 + Math.max(280, conteudo.implicitWidth) + 16
    implicitHeight: 12 + conteudo.implicitHeight + 12

    onMostradoChanged: {
        animacao.to = mostrado ? 1 : 0
        animacao.restart()
    }

    NumberAnimation {
        id: animacao
        target: cartao
        property: "opacidade"
        duration: 250
        onFinished: cartao.terminou()
    }

    FontMetrics { id: medida; font: textoDoTitulo.font }

    Rectangle {
        anchors.fill: parent
        radius: cartao.raio
        color: cartao.opaco ? "#1c1b22" : Qt.rgba(28 / 255, 27 / 255, 34 / 255, 0.94)
    }

    // A borda esquerda de 3 px na cor de destaque, acompanhando o canto arredondado.
    Item {
        width: 3
        height: parent.height
        clip: true
        Rectangle {
            width: cartao.width
            height: cartao.height
            radius: cartao.raio
            color: Tema.destaque
        }
    }

    Row {
        id: conteudo
        x: 3 + 12
        y: 12
        spacing: 12

        Item {
            id: lugarDoIcone
            width: 48
            height: 48
            anchors.verticalCenter: parent.verticalCenter

            Item {
                id: mascara
                anchors.fill: parent
                visible: false
                layer.enabled: true
                Rectangle { anchors.fill: parent; radius: 6 }
            }

            Image {
                id: imagem
                objectName: "iconeDoAviso"
                anchors.fill: parent
                visible: cartao.icone !== ""
                source: cartao.icone
                fillMode: Image.PreserveAspectCrop
                sourceSize: Qt.size(48 * Screen.devicePixelRatio, 48 * Screen.devicePixelRatio)
                layer.enabled: true
                layer.effect: MultiEffect {
                    maskEnabled: true
                    maskSource: mascara
                    maskThresholdMin: 0.5  // borda suave nos cantos arredondados
                    maskSpreadAtMin: 1.0
                }
            }

            Text {
                objectName: "estrelaDoAviso"
                anchors.centerIn: parent
                visible: cartao.icone === ""
                text: ""  // a estrela cheia (o starred-symbolic da `main`)
                color: "#ffffff"
                font { family: Tema.fonteDeIcones; pixelSize: 48 }
            }
        }

        Column {
            anchors.verticalCenter: parent.verticalCenter

            Text {
                objectName: "rotuloDoAviso"
                visible: text !== ""
                width: Math.min(implicitWidth, cartao.larguraMaxima)
                text: cartao.rotulo
                textFormat: Text.PlainText
                wrapMode: Text.Wrap
                color: "#ffffff"
                opacity: 0.75
                font { family: Tema.fonte; pixelSize: 12 }
            }

            Text {
                id: textoDoTitulo
                objectName: "tituloDoAviso"
                visible: text !== ""
                width: Math.min(implicitWidth, cartao.larguraMaxima)
                text: cartao.titulo
                textFormat: Text.PlainText
                wrapMode: Text.Wrap
                color: "#ffffff"
                font { family: Tema.fonte; pixelSize: 15; weight: Font.Bold }
            }

            Text {
                objectName: "descricaoDoAviso"
                visible: text !== ""
                width: Math.min(implicitWidth, cartao.larguraMaxima)
                text: cartao.descricao
                textFormat: Text.PlainText
                wrapMode: Text.Wrap
                color: "#ffffff"
                opacity: 0.55
                font { family: Tema.fonte; pixelSize: 12 }
            }
        }
    }
}
