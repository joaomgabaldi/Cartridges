import QtQuick
import QtQuick.Effects
import QtQuick.Window

// O ícone de uma conquista, na página do jogo, no diálogo e na tela da sessão.
// A oculta é um ladrilho com uma interrogação; as outras mostram a estrela no ladrilho até a imagem chegar (`url`,
// um arquivo `file:`) e para sempre, se ela não chegar. A bloqueada que só tem o ícone colorido (`cinza`) vai em cinza.
// `semLadrilho` (a página do jogo): até a imagem chegar, e para sempre se ela falhar, fica só o espaço vazio, sem ladrilho.
Item {
    id: icone
    objectName: "iconeDaConquista"

    property int tamanho: 36
    property int interrogacao: 24
    property string url: ""
    property bool cinza: false
    property bool oculta: false
    property bool semLadrilho: false
    property color corDoLadrilho: Tema.texto
    property color corDaInterrogacao: Qt.alpha(corDoLadrilho, corDoLadrilho.a * 0.6)

    readonly property bool imagemPronta: !oculta && imagem.status === Image.Ready

    implicitWidth: tamanho
    implicitHeight: tamanho

    // O lugar do ícone que não há (oculta) ou que ainda não chegou: um quadrado do canto dos ícones de verdade.
    Rectangle {
        objectName: "ladrilhoDaConquista"
        anchors.fill: parent
        visible: !icone.imagemPronta && !icone.semLadrilho
        radius: 6
        // O fundo é o texto a 0,6 x 0,12 = 7,2% (5,8% no claro, onde o texto já tem 0,8).
        color: Qt.alpha(icone.corDoLadrilho, icone.corDoLadrilho.a * 0.072)

        Text {
            anchors.centerIn: parent
            visible: icone.oculta
            text: "?"
            textFormat: Text.PlainText
            color: icone.corDaInterrogacao
            font { family: Tema.fonte; pixelSize: icone.interrogacao; weight: Font.ExtraBold }
        }
        Icone {
            objectName: "estrelaDaConquista"
            anchors.centerIn: parent
            visible: !icone.oculta
            nome: "starred"
            tamanho: Math.floor(icone.tamanho / 2)
            cor: Qt.alpha(icone.corDoLadrilho, icone.corDoLadrilho.a * 0.6)
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
            maskThresholdMin: 0.5
            maskSpreadAtMin: 1.0
            saturation: icone.cinza ? -1 : 0
        }
    }
}
