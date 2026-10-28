import QtQuick
import QtQuick.Window

// Um jogo da grade: capa 200x300 lógicos, nome embaixo e, ao passar o mouse, o botão de jogar.
Item {
    id: cartao

    required property string jogoId
    required property string nome
    required property string capa
    required property bool zerado
    // O modelo da biblioteca: só `iniciar` é chamado nele; o QML nunca vê um Jogo.
    property QtObject modelo

    readonly property int larguraDaCapa: 200
    readonly property int alturaDaCapa: 300

    width: larguraDaCapa
    height: alturaDaCapa + legenda.height + 8

    HoverHandler { id: passagem }

    Rectangle {
        id: moldura
        width: cartao.larguraDaCapa
        height: cartao.alturaDaCapa
        radius: 8
        color: Tema.botaoSobre
        clip: true

        Image {
            anchors.fill: parent
            source: cartao.capa !== "" ? cartao.capa : (cartao.modelo ? cartao.modelo.placeholder : "")
            fillMode: Image.PreserveAspectCrop
            asynchronous: true
            // Na resolução real da tela, para a capa não ficar borrada em DPI alto.
            sourceSize: Qt.size(cartao.larguraDaCapa * Screen.devicePixelRatio,
                                cartao.alturaDaCapa * Screen.devicePixelRatio)
        }

        Rectangle {
            id: botao
            anchors.centerIn: parent
            width: rotulo.implicitWidth + 40
            height: 40
            radius: height / 2
            color: Tema.destaque
            opacity: passagem.hovered ? 1 : 0
            visible: opacity > 0
            Behavior on opacity { NumberAnimation { duration: Tema.duracaoCurta } }

            Row {
                anchors.centerIn: parent
                spacing: 8
                Text {
                    text: "▶"
                    color: "white"
                    font.family: "Segoe UI Symbol"
                    font.pixelSize: 14
                    anchors.verticalCenter: parent.verticalCenter
                }
                Text {
                    id: rotulo
                    text: "Jogar"
                    color: "white"
                    font.family: Tema.fonte
                    font.pixelSize: 14
                    font.weight: Font.DemiBold
                }
            }

            TapHandler {
                onTapped: if (cartao.modelo) cartao.modelo.iniciar(cartao.jogoId)
            }
        }
    }

    Text {
        id: legenda
        anchors { top: moldura.bottom; topMargin: 8; left: moldura.left; right: moldura.right }
        text: cartao.nome
        color: Tema.texto
        font.family: Tema.fonte
        font.pixelSize: 14
        elide: Text.ElideRight
        horizontalAlignment: Text.AlignHCenter
    }
}
