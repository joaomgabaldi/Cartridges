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
    property url placeholder  // a imagem da capa que falta: a da grade
    property bool animar: false  // `bigPicture.animarCentral`
    property real opacidadeDoReflexo: 0.35  // REFLEXO_OPACIDADE

    width: largura
    height: altura

    Item {
        id: face
        anchors.fill: parent
        // Sem capa, ou com a capa ilegível ou ainda carregando: o placeholder da biblioteca (`capa.get_texture() or
        // GameCover.placeholder`), que o reflexo copia junto.
        Image {
            objectName: "placeholderDaCapa"
            anchors.fill: parent
            visible: imagem.status !== Image.Ready
            source: capa.placeholder
            fillMode: Image.Stretch
            sourceSize.height: Math.round(300 * capa.escala)
        }
        Image {
            id: imagem
            objectName: "capa"
            anchors.fill: parent
            source: capa.jogo.capa
            asynchronous: true
            fillMode: Image.Stretch  // esticada para 2:3, sem corte (`big_picture.py:451-453`)
            sourceSize.height: Math.round(300 * capa.escala)  // a textura da grade: 300 de altura
            mipmap: true
        }
        // A central, na resolução dos detalhes (630 de altura); só quando pronta, sem piscar.
        // Capa animada não ganha: toca a cópia da grade.
        Image {
            id: emAlta
            objectName: "capaEmAlta"
            anchors.fill: parent
            source: capa.central && capa.jogo.capaAnimada === "" ? capa.jogo.capa : ""
            asynchronous: true
            fillMode: Image.Stretch
            sourceSize.height: Math.round(630 * capa.escala)
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
