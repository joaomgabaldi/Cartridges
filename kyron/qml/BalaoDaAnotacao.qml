import QtQuick
import QtQuick.Controls.Basic

// O balão do "Onde eu parei": carrega `texto` ao abrir e emite `gravar` ao fechar (só se `editavel`).
Popup {
    id: raiz
    property string texto
    property bool editavel: true
    signal gravar(string texto)

    readonly property var caixa: typeof caixaDaAnotacao !== "undefined" ? caixaDaAnotacao : null
    readonly property real janelaLargura: Overlay.overlay ? Overlay.overlay.width : 0
    readonly property real janelaAltura: Overlay.overlay ? Overlay.overlay.height : 0
    function centroNaCena() { return parent ? parent.mapToItem(null, parent.width / 2, parent.height) : Qt.point(0, 0) }
    function livreLargura() { var c = centroNaCena(); return 2 * Math.min(c.x, janelaLargura - c.x) - 32 }
    function livreAltura() { return janelaAltura - centroNaCena().y - 6 - 32 - 8 }

    x: parent ? Math.round((parent.width - width) / 2) : 0
    y: parent ? parent.height + 6 : 0
    padding: 8
    bottomPadding: 24
    margins: 8
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutsideParent
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
        Rectangle {
            anchors.fill: parent
            color: Tema.vista
        }
        ScrollView {
            anchors.fill: parent
            TextArea {
                id: campo
                objectName: "campoDaAnotacao"
                readOnly: !raiz.editavel
                ContextMenu.menu: MenuDeTexto { campo: campo }
                wrapMode: TextEdit.Wrap
                textFormat: TextEdit.PlainText
                padding: 4
                color: Tema.texto
                selectionColor: Qt.alpha(Tema.destaque, 0.25)
                selectedTextColor: Tema.texto
                background: null
                font { family: Tema.fonte; pixelSize: Tema.corpo }
                Accessible.name: "Onde eu parei"
            }
        }

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
                onActiveTranslationChanged: if (active)
                    raiz.caixa.arrastar(puxador.inicioLargura, puxador.inicioAltura, activeTranslation.x * 2, activeTranslation.y,
                                        raiz.janelaLargura, raiz.janelaAltura, raiz.livreLargura(), raiz.livreAltura())
            }
            Canvas {
                anchors { fill: parent; margins: 2 }
                property color cor: Qt.alpha(Tema.texto, 0.35)
                onCorChanged: requestPaint()
                onPaint: {
                    var c = getContext("2d")
                    c.clearRect(0, 0, width, height)
                    c.fillStyle = cor
                    var w = width, h = height
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
