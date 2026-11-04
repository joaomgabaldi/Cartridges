import QtQuick
import QtQuick.Effects
import QtQuick.Window

// O ícone de uma conquista. `semLadrilho`: até a imagem chegar (ou se falhar) fica só o espaço vazio.
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

    Rectangle {
        objectName: "ladrilhoDaConquista"
        anchors.fill: parent
        visible: !icone.imagemPronta && !icone.semLadrilho
        radius: 6
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
