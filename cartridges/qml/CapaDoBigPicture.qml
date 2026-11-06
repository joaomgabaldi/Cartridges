import QtQuick
import Qt5Compat.GraphicalEffects

// Uma capa e o seu reflexo, no espaço da capa; o reflexo é filho dela e herda a transformação 3D.
Item {
    id: capa
    objectName: "capaDoBigPicture"
    required property var jogo
    required property int indice
    required property Item mascara
    required property real largura
    required property real altura
    property real escala: 1
    property bool central: false
    property url placeholder
    property bool animar: false
    property real opacidadeDoReflexo: 0.22
    property real escurecer: 0  // o quanto a capa recua: a selecionada fica em destaque

    width: largura
    height: altura

    Item {
        id: face
        anchors.fill: parent
        Image {
            objectName: "placeholderDaCapa"
            anchors.fill: parent
            visible: imagem.status !== Image.Ready
            source: capa.placeholder
            fillMode: Image.Stretch
            sourceSize.height: Math.round(300 * capa.escala)
            mipmap: true
        }
        Image {
            id: imagem
            objectName: "capa"
            anchors.fill: parent
            source: capa.jogo.capa
            asynchronous: true
            fillMode: Image.Stretch
            sourceSize.height: Math.round(300 * capa.escala)
            mipmap: true
        }
        Image {
            id: emAlta
            objectName: "capaEmAlta"
            anchors.fill: parent
            source: capa.central && capa.jogo.capaAnimada === "" ? capa.jogo.capa : ""
            asynchronous: true
            fillMode: Image.Stretch
            sourceSize.height: Math.round(900 * capa.escala)
            mipmap: true
            visible: status === Image.Ready
        }
        AnimatedImage {
            id: animada
            objectName: "capaAnimada"
            anchors.fill: parent
            source: capa.central && capa.animar ? capa.jogo.capaAnimada : ""
            playing: source != ""
            visible: status === AnimatedImage.Ready
            fillMode: Image.Stretch
            asynchronous: true
            cache: false
        }
    }
    Rectangle {
        anchors.fill: parent
        color: "black"
        opacity: capa.escurecer
        visible: opacity > 0
    }

    OpacityMask {
        objectName: "reflexo"
        y: capa.altura + 4
        width: capa.largura
        height: capa.altura
        source: face
        maskSource: capa.mascara
        opacity: capa.opacidadeDoReflexo * (1 - capa.escurecer)
        layer.enabled: true
        layer.mipmap: true
        layer.smooth: true
        transform: Scale { origin.y: capa.altura / 2; yScale: -1 }
    }
}
