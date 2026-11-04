import QtQuick
import QtQuick.Controls.Basic

ProgressBar {
    id: barra

    from: 0
    to: 1
    property color corDaTrilha: Tema.botaoSobre

    implicitHeight: 8
    background: Rectangle { radius: height / 2; color: barra.corDaTrilha }
    contentItem: Item {
        Rectangle {
            width: barra.visualPosition * parent.width
            height: parent.height
            radius: height / 2
            color: Tema.destaque
        }
    }
}
