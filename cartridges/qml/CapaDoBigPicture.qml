import QtQuick
import Qt5Compat.GraphicalEffects

// Uma capa e o seu reflexo, no espaço da capa (0,0 a largura,altura). O reflexo
// é filho da capa: herda a mesma transformação 3D, como no app.
Item {
    id: capa
    objectName: "capaDoBigPicture"
    required property var jogo
    required property int indice
    required property Item mascara
    required property real largura
    required property real altura
    property real escala: 1  // pixels reais por pixel lógico
    property bool central: false
    property bool animar: false  // `bigPicture.animarCentral`
    property real escalaDaCentral: 1.6  // ESCALA_NA_ABERTURA: a central cresce até aqui
    property real opacidadeDoReflexo: 0.35  // REFLEXO_OPACIDADE

    width: largura
    height: altura

    Item {
        id: face
        anchors.fill: parent
        Rectangle {
            anchors.fill: parent
            visible: imagem.status !== Image.Ready
            color: "#2e2e32"
            Text {
                anchors.fill: parent
                anchors.margins: 12
                text: capa.jogo.nome
                textFormat: Text.PlainText
                color: "#c0c0c0"
                wrapMode: Text.Wrap
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
                font { family: Tema.fonte; pixelSize: 18 }
            }
        }
        Image {
            id: imagem
            objectName: "capa"
            anchors.fill: parent
            source: capa.jogo.capa
            asynchronous: true
            fillMode: Image.PreserveAspectCrop
            sourceSize.height: Math.round(capa.altura * capa.escala)
            mipmap: true
        }
        // A central, na resolução da abertura (ela cresce 1,6x); só quando pronta, sem piscar.
        // Capa animada não ganha: toca a cópia da grade.
        Image {
            id: emAlta
            objectName: "capaEmAlta"
            anchors.fill: parent
            source: capa.central && capa.jogo.capaAnimada === "" ? capa.jogo.capa : ""
            asynchronous: true
            fillMode: Image.PreserveAspectCrop
            sourceSize.height: Math.round(capa.altura * capa.escalaDaCentral * capa.escala)
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
            fillMode: Image.PreserveAspectCrop
            asynchronous: true
            cache: false
        }
    }

    // O mipmap e a suavização da camada dão amostragem trilinear sob o giro (D46).
    OpacityMask {
        objectName: "reflexo"
        y: capa.altura + 4
        width: capa.largura
        height: capa.altura
        source: face
        maskSource: capa.mascara
        opacity: capa.opacidadeDoReflexo
        layer.enabled: true
        layer.mipmap: true
        layer.smooth: true
        transform: Scale { origin.y: capa.altura / 2; yScale: -1 }
    }
}
