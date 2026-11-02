import QtQuick
import QtQuick.Controls.Basic

// O balão do "Onde eu parei": carrega `texto` ao abrir e emite `gravar` ao fechar (só se `editavel`).
// Usado pela página de detalhes e pela tela da sessão.
Popup {
    id: raiz
    property string texto
    property bool editavel: true
    signal gravar(string texto)

    // O tamanho vale para as duas caixas e fica guardado (`caixaDaAnotacao`); sem ele, o de sempre.
    readonly property var caixa: typeof caixaDaAnotacao !== "undefined" ? caixaDaAnotacao : null
    readonly property real janelaLargura: Overlay.overlay ? Overlay.overlay.width : 0
    readonly property real janelaAltura: Overlay.overlay ? Overlay.overlay.height : 0
    // O balão fica centrado no botão (com seta) e a largura cresce para os dois lados. O espaço livre é, então, o dobro do
    // menor lado entre o centro do botão e a borda da janela; embaixo, o que sobra depois da seta e da faixa do puxador.
    function centroNaCena() { return parent ? parent.mapToItem(null, parent.width / 2, parent.height) : Qt.point(0, 0) }
    function livreLargura() { var c = centroNaCena(); return 2 * Math.min(c.x, janelaLargura - c.x) - 16 }
    function livreAltura() { return janelaAltura - centroNaCena().y - 6 - 16 - 8 }

    x: parent ? Math.round((parent.width - width) / 2) : 0
    y: parent ? parent.height + 6 : 0
    padding: 0
    bottomPadding: 16  // a faixa do puxador, abaixo do texto
    margins: 8
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
    function restaurar() { if (caixa) caixa.restaurar(janelaLargura, janelaAltura, livreLargura(), livreAltura()) }
    onAboutToShow: {
        campo.text = raiz.texto
        restaurar()
    }
    // De novo com o balão no lugar: o `y` ainda não vale em `aboutToShow`.
    onOpened: {
        restaurar()
        campo.forceActiveFocus()
    }
    onClosed: if (raiz.editavel) raiz.gravar(campo.text)
    enter: null
    exit: null
    // O popover: raio 15, sombra e a seta no centro do botão.
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
    contentItem: Item {
        implicitWidth: raiz.caixa ? raiz.caixa.largura : 320
        implicitHeight: raiz.caixa ? raiz.caixa.altura : 120
        // `textview`: o fundo da vista; só os cantos de cima são redondos (a faixa do puxador fica abaixo).
        Rectangle {
            anchors.fill: parent
            topLeftRadius: 15
            topRightRadius: 15
            color: Tema.vista
        }
        ScrollView {
            anchors.fill: parent
            TextArea {
                id: campo
                objectName: "campoDaAnotacao"
                readOnly: !raiz.editavel
                wrapMode: TextEdit.Wrap
                textFormat: TextEdit.PlainText
                // Margens de 4 em todos os lados.
                padding: 4
                color: Tema.texto
                selectionColor: Qt.alpha(Tema.destaque, 0.25)
                selectedTextColor: Tema.texto
                background: null
                font { family: Tema.fonte; pixelSize: Tema.corpo }
                Accessible.name: "Onde eu parei"
            }
        }

        // O puxador: uma faixa de 16 px abaixo do texto, à direita, com as listras a 35% (`.puxador-de-tamanho`, margem 2).
        Item {
            id: puxador
            objectName: "puxadorDaAnotacao"
            visible: !!raiz.caixa
            anchors { right: parent.right; top: parent.bottom }
            width: 16
            height: 16
            property int inicioLargura
            property int inicioAltura
            HoverHandler { id: sobrePuxador; cursorShape: Qt.SizeFDiagCursor }
            ToolTip.visible: sobrePuxador.hovered && !arrasto.active
            ToolTip.text: "Arraste para mudar o tamanho"
            ToolTip.delay: 500
            DragHandler {
                id: arrasto
                target: null
                cursorShape: Qt.SizeFDiagCursor
                onActiveChanged: {
                    if (active) {
                        puxador.inicioLargura = raiz.caixa.largura
                        puxador.inicioAltura = raiz.caixa.altura
                    } else {
                        raiz.caixa.gravar()
                    }
                }
                // `FATOR_DA_LARGURA = 2`: o balão cresce para os dois lados, e o canto anda metade; com o dobro do
                // deslocamento, o puxador acompanha o mouse.
                onActiveTranslationChanged: if (active)
                    raiz.caixa.arrastar(puxador.inicioLargura, puxador.inicioAltura, activeTranslation.x * 2, activeTranslation.y,
                                        raiz.janelaLargura, raiz.janelaAltura, raiz.livreLargura(), raiz.livreAltura())
            }
            Canvas {
                anchors { fill: parent; margins: 2 }
                property color cor: Qt.alpha(Tema.texto, 0.35)
                onCorChanged: requestPaint()
                onPaint: {
                    // `linear-gradient(135deg, ...)`: duas listras na diagonal do canto de baixo à direita.
                    var c = getContext("2d")
                    c.clearRect(0, 0, width, height)
                    c.fillStyle = cor
                    var w = width, h = height
                    // Faixas em 45-55% e 70-80% da diagonal (do canto de cima à esquerda ao de baixo à direita).
                    for (var faixa of [[0.45, 0.55], [0.70, 0.80]]) {
                        var a = faixa[0] * (w + h), b = faixa[1] * (w + h)
                        c.beginPath()
                        c.moveTo(Math.min(a, w), Math.max(0, a - w))
                        c.lineTo(Math.min(b, w), Math.max(0, b - w))
                        c.lineTo(Math.max(0, b - h), Math.min(b, h))
                        c.lineTo(Math.max(0, a - h), Math.min(a, h))
                        c.closePath()
                        c.fill()
                    }
                }
            }
        }
    }
}
