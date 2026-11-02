import QtQuick
import QtQuick.Controls.Basic

// O `Adw.SwitchRow`: título, explicação e o interruptor; a linha inteira aciona, com hover de 4% e 8% pressionada.
LinhaDoGrupo {
    id: linha

    property alias checked: chave.checked

    // A pessoa ligou ou desligou a chave.
    signal alternado()

    reservaADireita: chave.width
    sobre: areaDaLinha.containsMouse && !chave.hovered
    pressionada: areaDaLinha.pressed

    MouseArea {
        id: areaDaLinha
        anchors.fill: parent
        hoverEnabled: true
        onClicked: { chave.forceActiveFocus(Qt.MouseFocusReason); chave.click() }
    }

    Switch {
        id: chave
        objectName: linha.objectName + "Chave"
        anchors { right: parent.right; rightMargin: 14; verticalCenter: parent.verticalCenter }
        focusPolicy: Qt.StrongFocus
        hoverEnabled: true
        padding: 0
        Keys.onReturnPressed: click()
        Keys.onEnterPressed: click()
        Accessible.name: linha.titulo
        onToggled: linha.alternado()
        // switch: padding 3, botão de 20, raio 14; fundo 15% (20% sobre, 25% pressionado); ligado, o destaque.
        indicator: Rectangle {
            implicitWidth: 46
            implicitHeight: 26
            radius: 14
            color: chave.checked ? Tema.destaque
                : Qt.alpha(Tema.corBase, chave.pressed ? 0.25 : chave.hovered || areaDaLinha.containsMouse ? 0.20 : 0.15)
            Behavior on color { ColorAnimation { duration: Tema.duracaoCurta } }
            Rectangle {
                anchors.fill: parent
                radius: parent.radius
                visible: chave.checked && (chave.hovered || chave.pressed)
                color: chave.pressed ? Qt.rgba(0, 0, 6 / 255, 0.2) : Qt.rgba(1, 1, 1, 0.1)
            }
            Rectangle {
                x: chave.checked ? parent.width - width - 3 : 3
                y: 3
                width: 20
                height: 20
                radius: 10
                // color-mix(white 80%, view_bg), branco sobre e ligado.
                color: chave.checked || chave.hovered || chave.pressed ? "white"
                    : Qt.rgba(0.8 + 0.2 * Tema.vista.r, 0.8 + 0.2 * Tema.vista.g, 0.8 + 0.2 * Tema.vista.b, 1)
                Sombra { camadas: chave.enabled ? [[2, 4, 0, 0, 0, 6 / 255, 0.2]] : []; raio: 10 }
                Behavior on x { NumberAnimation { duration: Tema.duracaoCurta; easing { type: Easing.Bezier; bezierCurve: Tema.curva } } }
            }
            AnelDeFoco { ativo: chave.visualFocus; raio: 14 }
        }
    }
}
