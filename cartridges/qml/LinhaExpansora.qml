import QtQuick
import QtQuick.Controls.Basic

// Linha expansora com interruptor: as filhas (`linhas`) só aparecem com o interruptor ligado e ficam fora da busca. Nasce
// recolhida.
LinhaDoGrupo {
    id: linha

    property string icone
    property bool expandida: false
    property alias checked: chave.checked
    default property alias linhas: filhas.data

    signal alternado()

    readonly property bool aberta: expandida && checked
    readonly property real _cabecalho: alturaMinima + 4
    readonly property real _topo: _separador

    comTextos: false
    implicitHeight: _cabecalho + _separador + (aberta ? filhas.implicitHeight : 0)
    // As filhas ficam escondidas, e não só com altura zero, para não receberem o Tab fechadas.
    Behavior on implicitHeight { enabled: Tema.animacoes; NumberAnimation { duration: Tema.duracaoCurta; easing { type: Easing.Bezier; bezierCurve: Tema.curva } } }

    Rectangle {
        anchors { left: parent.left; right: parent.right; top: parent.top; topMargin: linha._topo }
        height: linha._cabecalho
        topLeftRadius: linha.primeira || linha.separada ? 12 : 0
        topRightRadius: topLeftRadius
        bottomLeftRadius: linha.aberta ? 0 : linha.raioDaLinha
        bottomRightRadius: bottomLeftRadius
        color: area.pressed ? Tema.linhaPressionada : area.containsMouse && !chave.hovered ? Tema.linhaSobre : "transparent"
    }
    MouseArea {
        id: area
        anchors { left: parent.left; right: parent.right; top: parent.top; topMargin: linha._topo }
        height: linha._cabecalho
        hoverEnabled: true
        enabled: linha.checked
        onClicked: linha.expandida = !linha.expandida
    }
    Item {
        anchors { left: parent.left; right: parent.right; top: parent.top; topMargin: linha._topo }
        height: linha._cabecalho
        AnelDeFoco { ativo: chave.visualFocus || seta.visualFocus; raio: 12; afastamento: -2 }
    }

    Text {
        objectName: linha.objectName + "Rotulo"
        anchors {
            left: parent.left; leftMargin: linha.icone !== "" ? 14 + 16 + 12 : 14
            right: lado.left; rightMargin: 12
            top: parent.top; topMargin: linha._topo + (linha._cabecalho - height) / 2
        }
        text: linha.titulo
        textFormat: Text.PlainText
        elide: Text.ElideRight
        lineHeightMode: Text.FixedHeight
        lineHeight: Tema.alturaDoCorpo
        color: Tema.texto
        font { family: Tema.fonte; pixelSize: Tema.corpo }
    }
    Icone {
        x: 14
        y: linha._topo + (linha._cabecalho - height) / 2
        visible: linha.icone !== ""
        nome: linha.icone
    }

    Row {
        id: lado
        anchors { right: parent.right; rightMargin: 14; top: parent.top; topMargin: linha._topo + (linha._cabecalho - height) / 2 }
        spacing: 12
        Switch {
            id: chave
            objectName: linha.objectName + "Chave"
            focusPolicy: Qt.StrongFocus
            hoverEnabled: true
            padding: 0
            Keys.onReturnPressed: click()
            Keys.onEnterPressed: click()
            Accessible.name: linha.titulo
            onToggled: { linha.expandida = checked; linha.alternado() }
            indicator: Rectangle {
                implicitWidth: 46
                implicitHeight: 26
                radius: 14
                color: chave.checked ? Tema.destaque : Tema.mistura(chave.pressed ? 0.25 : chave.hovered ? 0.20 : 0.15)
                Behavior on color { ColorAnimation { duration: Tema.duracaoCurta } }
                Rectangle {
                    x: chave.checked ? parent.width - width - 3 : 3
                    y: 3
                    width: 20
                    height: 20
                    radius: 10
                    color: chave.checked || chave.hovered || chave.pressed ? "white"
                        : Qt.rgba(0.8 + 0.2 * Tema.vista.r, 0.8 + 0.2 * Tema.vista.g, 0.8 + 0.2 * Tema.vista.b, 1)
                    Behavior on x { NumberAnimation { duration: Tema.duracaoCurta; easing { type: Easing.Bezier; bezierCurve: Tema.curva } } }
                }
            }
        }
        FocusScope {
            id: seta
            objectName: linha.objectName + "Seta"
            property bool visualFocus: false
            width: 16
            height: 26
            opacity: linha.checked ? 1 : Tema.opacidadeDesabilitado
            enabled: linha.checked
            activeFocusOnTab: true
            Accessible.role: Accessible.Button
            Accessible.name: linha.aberta ? "Recolher" : "Expandir"
            onActiveFocusChanged: if (!activeFocus) visualFocus = false
            Keys.onPressed: event => {
                visualFocus = true
                if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter || event.key === Qt.Key_Space) {
                    linha.expandida = !linha.expandida
                    event.accepted = true
                }
            }
            Icone {
                anchors.centerIn: parent
                nome: "pan-down"
                cor: linha.aberta ? Tema.destaqueTexto : Tema.texto
                rotation: linha.aberta ? 180 : 0
                Behavior on rotation { enabled: Tema.animacoes; NumberAnimation { duration: Tema.duracaoCurta; easing { type: Easing.Bezier; bezierCurve: Tema.curva } } }
            }
        }
    }

    // O vão de 0,01 no início tira a primeira filha de `y <= 0`: ela desenha o separador de cima.
    Column {
        id: filhas
        readonly property bool separada: false
        anchors { left: parent.left; right: parent.right; top: parent.top; topMargin: linha._topo + linha._cabecalho }
        height: Math.max(0, linha.implicitHeight - linha._topo - linha._cabecalho)
        clip: true
        visible: linha.aberta || height > 0
        Item { width: 1; height: 0.01 }
    }
}
