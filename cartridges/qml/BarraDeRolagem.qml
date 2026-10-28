import QtQuick
import QtQuick.Controls.Basic

// Barra de rolagem fina, que engrossa ao passar o mouse (D25).
ScrollBar {
    id: barra

    readonly property bool ativa: hovered || pressed
    implicitWidth: ativa ? 10 : 4
    minimumSize: 0.08
    padding: 2
    Behavior on implicitWidth { NumberAnimation { duration: Tema.duracaoCurta } }

    contentItem: Rectangle {
        implicitWidth: 4
        radius: width / 2
        color: Tema.textoSecundario
        opacity: barra.size < 1 ? (barra.ativa || barra.active ? 0.8 : 0.45) : 0
        Behavior on opacity { NumberAnimation { duration: Tema.duracaoCurta } }
    }
    background: Item {}
}
