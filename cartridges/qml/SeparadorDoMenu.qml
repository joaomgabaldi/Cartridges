import QtQuick
import QtQuick.Controls.Basic

// `popover.menu separator`: 1 px na cor da borda, com 6 acima e abaixo.
MenuSeparator {
    padding: 0
    topPadding: 6
    bottomPadding: 6
    contentItem: Rectangle {
        implicitHeight: 1
        color: Tema.borda
    }
}
