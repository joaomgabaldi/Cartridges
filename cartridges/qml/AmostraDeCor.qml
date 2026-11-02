import QtQuick
import QtQuick.Controls.Basic

// O botão da cor (o `MenuButton` com a `DrawingArea` de 22x22 da `main`): a amostra em círculo, sem borda, e o balão com o
// `SeletorDeCor`, centrado no botão e com seta. No automático (`roda`), a amostra é uma roda de cores com o furo
// transparente, do matiz 0 no topo. Cada movimento no seletor emite `escolhida`; quem usa grava e devolve a cor em `cor`.
Botao {
    id: amostra

    property color cor
    property bool roda: false
    // Os `objectName` do balão, do seletor e da amostra (os testes de cada tela).
    property string nomeDoBalao: objectName + "Balao"
    property string nomeDoSeletor: objectName + "Seletor"
    property string nomeDaAmostra: objectName + "Cor"
    property string nomeDaRoda: objectName + "Roda"
    readonly property alias balao: balao

    signal escolhida(color cor)
    signal aberta()
    signal fechada()

    estilo: "plano"
    implicitWidth: 34
    implicitHeight: 34
    leftPadding: 0
    rightPadding: 0
    dicaAtiva: hovered && !balao.opened
    onClicked: balao.opened ? balao.close() : balao.open()

    contentItem: Item {
        Rectangle {
            objectName: amostra.nomeDaAmostra
            anchors.centerIn: parent
            width: 22
            height: 22
            radius: 11
            visible: !amostra.roda
            color: amostra.cor
        }
        Canvas {
            objectName: amostra.nomeDaRoda
            anchors.centerIn: parent
            width: 22
            height: 22
            visible: amostra.roda
            onVisibleChanged: if (visible) requestPaint()
            onPaint: {
                // 36 fatias a partir do topo (-90 graus), uma sobra de 0,02 rad contra a fresta entre elas; o furo é 35% do raio.
                var c = getContext("2d")
                c.reset()
                var r = width / 2
                for (var i = 0; i < 36; ++i) {
                    var inicio = 2 * Math.PI * i / 36 - Math.PI / 2
                    c.fillStyle = Qt.hsva(i / 36, 1, 1, 1)
                    c.beginPath()
                    c.moveTo(r, r)
                    c.arc(r, r, r, inicio, inicio + 2 * Math.PI / 36 + 0.02, false)
                    c.closePath()
                    c.fill()
                }
                c.globalCompositeOperation = "destination-out"
                c.beginPath()
                c.arc(r, r, r * 0.35, 0, 2 * Math.PI, false)
                c.fill()
            }
        }
    }

    Popup {
        id: balao
        objectName: amostra.nomeDoBalao
        x: (amostra.width - width) / 2
        y: amostra.height + 6
        padding: 12
        margins: 8  // o balão não sai da janela, mesmo com a linha no pé da rolagem
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
        enter: null
        exit: null
        // O seletor parte da cor que a linha mostra agora; depois disso quem manda nele é a mão.
        onAboutToShow: {
            seletor.matiz = Math.max(0, amostra.cor.hsvHue) * 360
            seletor.saturacao = Math.round(amostra.cor.hsvSaturation * 1000)
        }
        onOpened: {
            seletor.forceActiveFocus(Qt.TabFocusReason)
            amostra.aberta()
        }
        onClosed: {
            amostra.forceActiveFocus(Qt.TabFocusReason)
            amostra.fechada()
        }
        background: Rectangle {
            color: Tema.popover
            radius: 15
            Sombra { camadas: Tema.sombraPopover; raio: 15 }
            Rectangle {
                x: parent.width / 2 - width / 2
                y: -width / 2 + 1
                width: 14
                height: 14
                rotation: 45
                color: Tema.popover
            }
        }
        contentItem: SeletorDeCor {
            id: seletor
            objectName: amostra.nomeDoSeletor
            onEscolhida: cor => amostra.escolhida(cor)
        }
    }
}
