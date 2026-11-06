import QtQuick
import QtQuick.Controls.Basic

LinhaDoGrupo {
    id: linha

    property int de: 0
    property int ate: 100
    property int passo: 1
    property int pagina: 10
    property int value: 0

    signal alterado(int valor)

    reservaADireita: caixa.width
    foco: caixa.activeFocus

    SpinBox {
        id: caixa
        objectName: linha.objectName + "Caixa"
        anchors { right: parent.right; rightMargin: 14; verticalCenter: parent.verticalCenter }
        // Apagada e abaixo do mínimo (0 sem dispositivo): o `SpinBox` não o prende ao mínimo.
        from: linha.enabled ? linha.de : Math.min(linha.de, linha.value)
        to: linha.ate
        stepSize: linha.passo
        editable: true
        focusPolicy: Qt.StrongFocus
        hoverEnabled: true
        Accessible.name: linha.titulo
        onValueModified: linha.alterado(value)
        Keys.onPressed: event => {
            var delta = event.key === Qt.Key_PageUp ? linha.pagina : event.key === Qt.Key_PageDown ? -linha.pagina : 0
            if (delta === 0) return
            event.accepted = true
            linha.alterado(Math.max(linha.de, Math.min(linha.ate, value + delta)))
        }
        padding: 0
        leftPadding: 0
        rightPadding: 12 + 2 * 34 + 6
        implicitHeight: 34
        implicitWidth: Math.max(valor.contentWidth, 16) + rightPadding
        contentItem: TextInput {
            id: valor
            // Uma parada de Tab só: o SpinBox liga o `activeFocusOnTab` do item ao assumi-lo.
            Component.onCompleted: activeFocusOnTab = false
            text: caixa.displayText
            readOnly: !caixa.editable
            validator: caixa.validator
            inputMethodHints: Qt.ImhDigitsOnly
            selectByMouse: true
            horizontalAlignment: Qt.AlignRight
            verticalAlignment: Qt.AlignVCenter
            color: Tema.texto
            selectionColor: Qt.alpha(Tema.destaque, 0.25)
            selectedTextColor: Tema.texto
            font { family: Tema.fonte; pixelSize: Tema.corpo }
        }
        down.indicator: Rectangle {
            x: caixa.width - 2 * 34 - 6 + 2
            y: 2
            width: 30
            height: 30
            radius: 15
            color: !caixa.enabled || caixa.value <= caixa.from ? Tema.botao
                : caixa.down.pressed ? Tema.pressionado : caixa.down.hovered ? Tema.botaoSobre : Tema.botao
            opacity: caixa.value <= caixa.from ? Tema.opacidadeDesabilitado : 1
            Behavior on color { ColorAnimation { duration: Tema.duracaoCurta } }
            Icone { anchors.centerIn: parent; nome: "list-remove" }
        }
        up.indicator: Rectangle {
            x: caixa.width - 34 + 2
            y: 2
            width: 30
            height: 30
            radius: 15
            color: !caixa.enabled || caixa.value >= caixa.to ? Tema.botao
                : caixa.up.pressed ? Tema.pressionado : caixa.up.hovered ? Tema.botaoSobre : Tema.botao
            opacity: caixa.value >= caixa.to ? Tema.opacidadeDesabilitado : 1
            Behavior on color { ColorAnimation { duration: Tema.duracaoCurta } }
            Icone { anchors.centerIn: parent; nome: "list-add" }
        }
        background: null
    }

    Binding { target: caixa; property: "value"; value: linha.value }
}
