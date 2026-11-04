import QtQuick

// O seletor de cor da fita de LED: um quadrado com o matiz na horizontal e a saturação na vertical
// (cheia em cima, branco embaixo), com o brilho fixo. A fita só usa matiz e saturação; o brilho é a linha
// "Brilho (%)". Cada movimento emite `escolhida`, para as fitas acenderem a cor na hora.
// Teclado: setas esquerda e direita mexem no matiz, para cima e para baixo na saturação; com Shift, passos maiores.
FocusScope {
    id: raiz

    // 0 a 360 (o mesmo matiz da fita, em graus) e 0 a 1000 (a saturação da fita).
    property real matiz: 0
    property int saturacao: 1000
    readonly property color cor: Qt.hsva(Math.min(matiz, 359.999) / 360, saturacao / 1000, 1, 1)

    // A pessoa mexeu: a cor cheia escolhida.
    signal escolhida(color cor)

    implicitWidth: 240
    implicitHeight: 160
    activeFocusOnTab: true
    Accessible.role: Accessible.Slider
    Accessible.name: "Cor da iluminação inteligente"

    function mover(novoMatiz, novaSaturacao) {
        matiz = Math.max(0, Math.min(360, novoMatiz))
        saturacao = Math.max(0, Math.min(1000, Math.round(novaSaturacao)))
        escolhida(raiz.cor)
    }
    // Do ponteiro (em pixels do quadrado) para o matiz e a saturação.
    function apontar(x, y) {
        mover(x / quadrado.width * 360, (1 - y / quadrado.height) * 1000)
    }

    Keys.onPressed: event => {
        var passo = (event.modifiers & Qt.ShiftModifier) ? 5 : 1
        if (event.key === Qt.Key_Left) mover(matiz - 5 * passo, saturacao)
        else if (event.key === Qt.Key_Right) mover(matiz + 5 * passo, saturacao)
        else if (event.key === Qt.Key_Up) mover(matiz, saturacao + 20 * passo)
        else if (event.key === Qt.Key_Down) mover(matiz, saturacao - 20 * passo)
        else return
        event.accepted = true
    }

    Rectangle {
        id: quadrado
        anchors.fill: parent
        radius: 6
        clip: true

        // O círculo de matizes de 0 a 360 graus, esticado na horizontal.
        gradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop { position: 0 / 6; color: "#ff0000" }
            GradientStop { position: 1 / 6; color: "#ffff00" }
            GradientStop { position: 2 / 6; color: "#00ff00" }
            GradientStop { position: 3 / 6; color: "#00ffff" }
            GradientStop { position: 4 / 6; color: "#0000ff" }
            GradientStop { position: 5 / 6; color: "#ff00ff" }
            GradientStop { position: 6 / 6; color: "#ff0000" }
        }
        // A saturação: de nenhuma (branco) embaixo a cheia (sem véu) em cima.
        Rectangle {
            anchors.fill: parent
            gradient: Gradient {
                GradientStop { position: 0; color: "#00ffffff" }
                GradientStop { position: 1; color: "#ffffffff" }
            }
        }
        // O ponto escolhido.
        Rectangle {
            id: marca
            objectName: "marcaDoSeletorDeCor"
            x: raiz.matiz / 360 * quadrado.width - width / 2
            y: (1 - raiz.saturacao / 1000) * quadrado.height - height / 2
            width: 16
            height: 16
            radius: 8
            color: raiz.cor
            border { width: 2; color: "white" }
            Rectangle { anchors.fill: parent; anchors.margins: -1; radius: width / 2; color: "transparent"; border { width: 1; color: "#80000000" } }
        }
    }

    // O contorno do foco do teclado, por fora do quadrado (sem borda de 1 px própria: o balão já o separa do fundo).
    AnelDeFoco { ativo: raiz.activeFocus; raio: 6; afastamento: 0 }

    MouseArea {
        anchors.fill: parent
        onPressed: mouse => { raiz.forceActiveFocus(Qt.MouseFocusReason); raiz.apontar(mouse.x, mouse.y) }
        onPositionChanged: mouse => { if (pressed) raiz.apontar(mouse.x, mouse.y) }
    }
}
