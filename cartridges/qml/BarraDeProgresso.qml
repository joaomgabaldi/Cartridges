import QtQuick
import QtQuick.Controls.Basic

// A barra de progresso das conquistas: a trilha apagada e o preenchimento na cor de destaque. `value` vai de 0 a 1.
ProgressBar {
    id: barra

    from: 0
    to: 1
    implicitHeight: 6
    background: Rectangle { radius: 3; color: Tema.botaoSobre }
    contentItem: Item {
        Rectangle {
            width: barra.visualPosition * parent.width
            height: parent.height
            radius: 3
            color: Tema.destaque
        }
    }
}
