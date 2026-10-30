import QtQuick
import QtQuick.Controls.Basic

// Barra de rolagem fina, que engrossa ao passar o mouse (D25).
ScrollBar {
    id: barra

    readonly property bool ativa: hovered || pressed
    property color cor: Tema.textoSecundario  // a da tela da sessão, sempre escura, não segue o tema
    implicitWidth: ativa ? 10 : 4
    implicitHeight: implicitWidth  // a de lado (`ScrollBar.horizontal`) engrossa para cima
    minimumSize: 0.08
    padding: 2
    Behavior on implicitWidth { NumberAnimation { duration: Tema.duracaoCurta } }

    contentItem: Rectangle {
        implicitWidth: 4
        implicitHeight: 4
        radius: Math.min(width, height) / 2
        color: barra.cor
        opacity: barra.size < 1 ? (barra.ativa || barra.active ? 0.8 : 0.45) : 0
        Behavior on opacity { NumberAnimation { duration: Tema.duracaoCurta } }
    }
    background: Item {}
}
