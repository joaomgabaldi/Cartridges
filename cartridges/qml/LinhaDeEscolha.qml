import QtQuick
import QtQuick.Controls.Basic

// O `Adw.ComboRow`: o valor e a seta soltos no fim da linha; a linha inteira abre o popover, com a marca no item escolhido.
LinhaDoGrupo {
    id: linha

    property alias model: caixa.model
    property alias currentIndex: caixa.currentIndex
    // A largura mínima do popover; quem tem opções longas a alarga.
    property int larguraDaCaixa: 180

    readonly property real larguraDoPopover: caixa.popup.width

    // A pessoa escolheu uma opção (o índice).
    signal escolhido(int indice)

    reservaADireita: Math.min(valor.implicitWidth, width * 0.6) + 22
    sobre: caixa.hovered || caixa.popup.visible
    pressionada: caixa.down
    foco: caixa.visualFocus

    ComboBox {
        id: caixa
        objectName: linha.objectName + "Caixa"
        anchors.fill: parent
        focusPolicy: Qt.StrongFocus
        hoverEnabled: true
        Accessible.name: linha.titulo
        onActivated: indice => linha.escolhido(indice)
        // O A do controle (e o Enter) abre a lista, como o `activate` da `Adw.ComboRow`; fechada, o Qt não a abre com essa tecla.
        // O soltar da mesma tecla é engolido: o `ComboBox` o leria como "escolher o realçado" e fecharia a lista que acabou de abrir.
        property bool _abertaPelaTecla: false
        readonly property var _teclasDeAbrir: [Qt.Key_Return, Qt.Key_Enter]
        Keys.onPressed: event => {
            if (_teclasDeAbrir.includes(event.key) && !popup.visible) { popup.open(); _abertaPelaTecla = true; event.accepted = true }
        }
        Keys.onReleased: event => {
            if (_abertaPelaTecla && _teclasDeAbrir.includes(event.key)) { _abertaPelaTecla = false; event.accepted = true }
        }

        // A seta e o valor ficam no fim da linha; o título, à esquerda, é da base.
        leftPadding: linha.width - linha.reservaADireita - 14
        rightPadding: 36
        contentItem: Text {
            id: valor
            text: caixa.displayText
            textFormat: Text.PlainText
            elide: Text.ElideRight
            horizontalAlignment: Text.AlignRight
            verticalAlignment: Text.AlignVCenter
            color: Tema.texto
            font { family: Tema.fonte; pixelSize: Tema.corpo }
        }
        indicator: Icone {
            x: caixa.width - width - 14
            y: (caixa.height - height) / 2
            nome: "pan-down"
        }
        background: Item {}
        delegate: ItemDelegate {
            id: opcao
            required property var modelData
            required property int index
            width: caixa.popup.width - 2 * caixa.popup.padding
            implicitWidth: textoDaOpcao.implicitWidth + 12 + 12 + 22
            implicitHeight: 32
            hoverEnabled: true
            highlighted: caixa.highlightedIndex === index
            contentItem: Text {
                id: textoDaOpcao
                text: opcao.modelData
                textFormat: Text.PlainText
                elide: Text.ElideRight
                verticalAlignment: Text.AlignVCenter
                color: Tema.texto
                font { family: Tema.fonte; pixelSize: Tema.corpo }
            }
            leftPadding: 12
            rightPadding: 34
            Icone {
                anchors { right: parent.right; rightMargin: 12; verticalCenter: parent.verticalCenter }
                visible: caixa.currentIndex === opcao.index
                nome: "object-select"
            }
            background: Rectangle {
                radius: 9
                color: opcao.down ? Tema.menuPressionado : opcao.highlighted ? Tema.menuSobre : "transparent"
            }
        }
        // O popover cresce até o maior texto, como o GtkPopover; medido a cada abertura (os delegados só existem aberto).
        property real larguraDoMaior: 0
        function medirOpcoes() {
            let maior = 0
            for (let i = 0; i < count; ++i) {
                medida.text = textAt(i)
                maior = Math.max(maior, medida.advanceWidth)
            }
            larguraDoMaior = maior + 12 + 12 + 22
        }
        TextMetrics { id: medida; font { family: Tema.fonte; pixelSize: Tema.corpo } }
        popup: Popup {
            onAboutToShow: caixa.medirOpcoes()
            width: Math.max(linha.larguraDaCaixa, Math.min(caixa.larguraDoMaior + 2 * padding, linha.width))
            x: caixa.width - width - 6
            y: caixa.height + 2
            implicitHeight: contentItem.implicitHeight + 2 * padding
            padding: 6
            // Dentro da janela, como os menus do Tema.
            popupType: Popup.Item
            contentItem: ListView {
                id: lista
                clip: true
                implicitHeight: contentHeight
                model: caixa.popup.visible ? caixa.delegateModel : null
                currentIndex: caixa.highlightedIndex
            }
            background: Rectangle {
                radius: 15
                color: Tema.popover
                Sombra { camadas: Tema.sombraPopover; raio: 15 }
            }
        }
    }
}
