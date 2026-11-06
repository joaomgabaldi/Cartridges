import QtQuick
import QtQuick.Effects
import QtQuick.Controls.Basic
import QtQuick.Layouts

// A base dos modais da continuação da restauração. Sem `fechavel`, nem o Esc nem o X saem (a pasta de atalhos é obrigatória).
MolduraDoDialogo {
    id: modal

    property string titulo
    property Item inicial: null
    default property alias corpo: coluna.data
    readonly property alias botaoFechar: cabecalho.botaoFechar

    signal saiu()

    // Capa com raio 12: `clip` só corta em retângulo, então a imagem passa por uma máscara.
    component Capa: Item {
        id: capa
        property url fonte
        width: 32
        height: 48
        Rectangle { anchors.fill: parent; radius: 12; color: Tema.botaoSobre }
        Item {
            id: mascara
            anchors.fill: parent
            visible: false
            layer.enabled: true
            Rectangle { anchors.fill: parent; radius: 12 }
        }
        Image {
            anchors.fill: parent
            source: capa.fonte
            fillMode: Image.PreserveAspectCrop
            asynchronous: true
            sourceSize: Qt.size(capa.width * 2, capa.height * 2)
            layer.enabled: true
            layer.effect: MultiEffect {
                maskEnabled: true
                maskSource: mascara
                maskThresholdMin: 0.5
                maskSpreadAtMin: 1.0
            }
        }
    }

    // Lista rolável com o cartão atrás, para a sombra não ser cortada pela rolagem.
    component Cartela: Item {
        id: cartela
        property alias model: vista.model
        property alias delegate: vista.delegate
        property alias vista: vista
        property string objetoDaLista
        property real alturaMaxima: 420
        height: Math.min(vista.contentHeight, alturaMaxima)
        visible: vista.count > 0
        Rectangle {
            anchors.fill: parent
            radius: 12
            color: Tema.cartao
            Sombra { camadas: Tema.sombraCartao; raio: 12 }
        }
        ListView {
            id: vista
            objectName: cartela.objetoDaLista
            anchors.fill: parent
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: BarraDeRolagem {}
            // O Tab leva o foco a uma linha fora da vista: a lista rola até ela.
            Connections {
                target: cartela.Window.window
                function onActiveFocusItemChanged() {
                    for (var p = cartela.Window.window.activeFocusItem; p && p !== vista; p = p.parent)
                        if (p.parent === vista.contentItem && typeof p.index === "number") {
                            vista.positionViewAtIndex(p.index, ListView.Contain)
                            return
                        }
                }
            }
        }
    }

    focoInicial: inicial
    setasMovemOFoco: true
    nomeAcessivel: titulo
    onFecharPedido: saiu()

    CabecalhoDoDialogo {
        id: cabecalho
        titulo: modal.titulo
        comFechar: modal.fechavel
        objetoDoTitulo: "tituloDoModal"
        onFechar: modal.saiu()
    }
    Column {
        id: coluna
        Layout.fillWidth: true
        Layout.leftMargin: 24
        Layout.rightMargin: 24
        Layout.topMargin: 12
        Layout.bottomMargin: 24
        spacing: 18
    }
}
