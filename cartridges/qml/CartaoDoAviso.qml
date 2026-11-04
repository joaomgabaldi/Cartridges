import QtQuick
import QtQuick.Effects
import QtQuick.Shapes

// O cartão do aviso de conquista; a janela por cima do jogo (`janela_do_aviso.py`) é só ele. Textos de terceiros: texto
// puro.
Item {
    id: cartao
    objectName: "cartaoDoAviso"

    property string rotulo: ""
    property string titulo: ""
    property string descricao: ""
    property string icone: ""
    property bool semIcone: true
    property bool opaco: false
    property bool embutido: false
    property bool animar: Tema.animacoes
    property real opacidade: 1
    property bool mostrado: false
    signal terminou()

    readonly property int raio: opaco ? 0 : 12
    // Até 36 caracteres por linha, com a largura do Pango (0,617 do corpo): o `averageCharacterWidth` do Qt é menor e
    // quebrava o texto em duas linhas.
    readonly property real larguraMaxima: 36 * 0.617 * Tema.corpo
    readonly property real larguraDaLegenda: 36 * 0.617 * Tema.legenda

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
        duration: cartao.animar ? 250 : 0
        easing.type: Easing.OutCubic
        onFinished: cartao.terminou()
    }

    Rectangle {
        anchors.fill: parent
        radius: cartao.raio
        color: cartao.opaco ? "#1c1b22" : Qt.rgba(28 / 255, 27 / 255, 34 / 255, 0.94)
        Sombra { objectName: "sombraDoAviso"; visible: cartao.embutido; camadas: [[0, 0, 1, 1, 1, 1, 0.14], [2, 8, 0, 0, 0, 0, 0.35]]; raio: cartao.raio }
    }

    Shape {
        objectName: "bordaDoAviso"
        anchors.fill: parent
        visible: !cartao.opaco
        preferredRendererType: Shape.CurveRenderer
        ShapePath {
            fillColor: Tema.destaque
            strokeWidth: -1
            startX: 12; startY: 0
            PathArc { x: 0; y: 12; radiusX: 12; radiusY: 12; direction: PathArc.Counterclockwise }
            PathLine { x: 0; y: cartao.height - 12 }
            PathArc { x: 12; y: cartao.height; radiusX: 12; radiusY: 12; direction: PathArc.Counterclockwise }
            PathArc { x: 3; y: cartao.height - 12; radiusX: 9; radiusY: 12; direction: PathArc.Clockwise }
            PathLine { x: 3; y: 12 }
            PathArc { x: 12; y: 0; radiusX: 9; radiusY: 12; direction: PathArc.Clockwise }
        }
    }
    Rectangle { objectName: "bordaRetaDoAviso"; visible: cartao.opaco; width: 3; height: parent.height; color: Tema.destaque }

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
                    maskThresholdMin: 0.5
                    maskSpreadAtMin: 1.0
                }
            }

            Icone {
                objectName: "estrelaDoAviso"
                anchors.centerIn: parent
                visible: cartao.semIcone && cartao.icone === ""
                nome: "starred"
                tamanho: 48
                cor: "#ffffff"
            }
        }

        Column {
            anchors.verticalCenter: parent.verticalCenter

            Text {
                id: textoDoRotulo
                objectName: "rotuloDoAviso"
                visible: text !== ""
                width: Math.min(implicitWidth, cartao.larguraDaLegenda)
                text: cartao.rotulo
                textFormat: Text.PlainText
                wrapMode: Text.Wrap
                color: "#ffffff"
                opacity: 0.75
                lineHeight: 1.4
                font { family: Tema.fonte; pixelSize: Tema.legenda }
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
                font { family: Tema.fonte; pixelSize: Tema.corpo; weight: Tema.pesoForte }
            }

            Text {
                id: textoDaDescricao
                objectName: "descricaoDoAviso"
                visible: text !== ""
                width: Math.min(implicitWidth, cartao.larguraDaLegenda)
                text: cartao.descricao
                textFormat: Text.PlainText
                wrapMode: Text.Wrap
                color: "#ffffff"
                opacity: 0.55
                lineHeight: 1.4
                font { family: Tema.fonte; pixelSize: Tema.legenda }
            }
        }
    }
}
