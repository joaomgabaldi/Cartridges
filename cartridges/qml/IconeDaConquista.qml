import QtQuick
import QtQuick.Effects
import QtQuick.Window

// O ícone de uma conquista, na página do jogo, no diálogo e na tela da sessão.
// A oculta é um ladrilho com uma interrogação; as outras mostram a estrela no ladrilho até a imagem chegar (`url`,
// um arquivo `file:`) e para sempre, se ela não chegar. A bloqueada que só tem o ícone colorido (`cinza`) vai em cinza.
Item {
    id: icone
    objectName: "iconeDaConquista"

    property int tamanho: 36
    property int interrogacao: 24  // o tamanho da interrogação da oculta
    property string url: ""
    property bool cinza: false
    property bool oculta: false

    readonly property bool imagemPronta: !oculta && imagem.status === Image.Ready

    implicitWidth: tamanho
    implicitHeight: tamanho

    // O lugar do ícone que não há (oculta) ou que ainda não chegou: um quadrado do canto dos ícones de verdade.
    Rectangle {
        objectName: "ladrilhoDaConquista"
        anchors.fill: parent
        visible: !icone.imagemPronta
        radius: 6
        color: Qt.rgba(Tema.texto.r, Tema.texto.g, Tema.texto.b, 0.12)

        Text {
            anchors.centerIn: parent
            text: icone.oculta ? "?" : ""  // a estrela cheia (o starred-symbolic da `main`)
            textFormat: Text.PlainText
            color: Qt.rgba(Tema.texto.r, Tema.texto.g, Tema.texto.b, 0.6)
            font {
                family: icone.oculta ? Tema.fonte : Tema.fonteDeIcones
                pixelSize: icone.oculta ? icone.interrogacao : icone.tamanho / 2
                weight: icone.oculta ? Font.ExtraBold : Font.Normal
            }
        }
    }

    Item {
        id: mascara
        anchors.fill: parent
        visible: false
        layer.enabled: true
        Rectangle { anchors.fill: parent; radius: 6 }
    }

    Image {
        id: imagem
        objectName: "imagemDaConquista"
        anchors.fill: parent
        visible: icone.imagemPronta
        source: icone.oculta ? "" : icone.url
        // O quadrado central, qualquer que seja a proporção do arquivo.
        fillMode: Image.PreserveAspectCrop
        asynchronous: false
        sourceSize: Qt.size(icone.tamanho * Screen.devicePixelRatio, icone.tamanho * Screen.devicePixelRatio)
        layer.enabled: true
        layer.effect: MultiEffect {
            maskEnabled: true
            maskSource: mascara
            maskThresholdMin: 0.5  // borda suave nos cantos arredondados
            maskSpreadAtMin: 1.0
            saturation: icone.cinza ? -1 : 0  // o `filter: grayscale(1)` do CSS
        }
    }
}
