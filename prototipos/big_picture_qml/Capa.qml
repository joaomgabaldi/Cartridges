import QtQuick
import QtQuick.Window
import Qt5Compat.GraphicalEffects

// Uma capa e o seu reflexo, no espaço da capa (0,0 a largura,altura). O reflexo
// é filho da capa: herda a mesma transformação 3D, como no app.
Item {
    id: capa
    required property var jogo
    required property int indice
    required property Item mascara
    required property real largura
    required property real altura

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
                color: "#c0c0c0"
                wrapMode: Text.Wrap
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
                font.pixelSize: 18
            }
        }
        Image {
            id: imagem
            anchors.fill: parent
            source: capa.jogo.capa
            asynchronous: true
            fillMode: Image.PreserveAspectCrop
            sourceSize.height: Math.round(capa.altura * Screen.devicePixelRatio)
            mipmap: true
        }
    }

    OpacityMask {
        y: capa.altura + 4
        width: capa.largura
        height: capa.altura
        source: face
        maskSource: capa.mascara
        opacity: 0.35
        transform: Scale { origin.y: capa.altura / 2; yScale: -1 }
    }
}
