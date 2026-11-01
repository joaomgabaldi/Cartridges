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
    // O espaço livre da área do texto à direita e abaixo (o balão não é empurrado para dentro da janela).
    function livreLargura() { return janelaLargura - cantoNaCena().x - 8 }
    function livreAltura() { return janelaAltura - cantoNaCena().y - 8 }
    function cantoNaCena() { return parent ? parent.mapToItem(null, x + padding, y + padding) : Qt.point(0, 0) }

    padding: 8
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
    background: Rectangle {
        color: Tema.superficie
        border.color: Tema.borda
        radius: 8
    }
    contentItem: Item {
        implicitWidth: raiz.caixa ? raiz.caixa.largura : 320
        implicitHeight: raiz.caixa ? raiz.caixa.altura : 120
        ScrollView {
            anchors.fill: parent
            TextArea {
                id: campo
                objectName: "campoDaAnotacao"
                readOnly: !raiz.editavel
                wrapMode: TextEdit.Wrap
                textFormat: TextEdit.PlainText
                color: Tema.texto
                selectionColor: Tema.destaque
                font { family: Tema.fonte; pixelSize: 14 }
                Accessible.name: "Onde eu parei"
            }
        }

        // O puxador do canto de baixo, à direita: só o mouse o alcança.
        Item {
            id: puxador
            objectName: "puxadorDaAnotacao"
            visible: !!raiz.caixa
            anchors { right: parent.right; bottom: parent.bottom; rightMargin: -4; bottomMargin: -4 }
            width: 16
            height: 16
            property int inicioLargura
            property int inicioAltura
            HoverHandler { id: sobrePuxador; cursorShape: Qt.SizeFDiagCursor }
        ToolTip.visible: sobrePuxador.hovered && !arrasto.active
        ToolTip.text: "Arraste para mudar o tamanho"
        ToolTip.delay: 600
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
                    raiz.caixa.arrastar(puxador.inicioLargura, puxador.inicioAltura, activeTranslation.x, activeTranslation.y,
                                        raiz.janelaLargura, raiz.janelaAltura, raiz.livreLargura(), raiz.livreAltura())
            }
            Canvas {
                anchors.fill: parent
                property color cor: Tema.textoSecundario
                onCorChanged: requestPaint()
                onPaint: {
                    var c = getContext("2d")
                    c.clearRect(0, 0, width, height)
                    c.strokeStyle = cor
                    c.lineWidth = 1
                    c.beginPath()
                    c.moveTo(width - 3, height - 11); c.lineTo(width - 11, height - 3)
                    c.moveTo(width - 3, height - 6); c.lineTo(width - 6, height - 3)
                    c.stroke()
                }
            }
        }
    }
}
