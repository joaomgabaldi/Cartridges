import QtQuick
import QtQuick.Controls.Basic

ScrollBar {
    id: barra

    readonly property bool ativa: hovered || pressed
    readonly property bool emPe: orientation === Qt.Vertical
    property color cor: Tema.corBase
    property bool acordada: false

    property real grossura: ativa ? 8 : 3
    property real margem: ativa ? 8 : 4

    implicitWidth: emPe ? grossura + 2 * margem : 0
    implicitHeight: emPe ? 0 : grossura + 2 * margem
    minimumSize: 0.08
    leftPadding: emPe ? margem : 9
    rightPadding: leftPadding
    topPadding: emPe ? 9 : margem
    bottomPadding: topPadding
    Behavior on grossura { NumberAnimation { duration: Tema.duracaoCurta } }
    Behavior on margem { NumberAnimation { duration: Tema.duracaoCurta } }

    onActiveChanged: if (active) { acordada = true; repouso.stop() } else repouso.restart()
    onPositionChanged: { acordada = true; if (!active) repouso.restart() }
    Timer { id: repouso; interval: 1000; onTriggered: barra.acordada = false }

    contentItem: Rectangle {
        implicitWidth: barra.grossura
        implicitHeight: barra.grossura
        radius: Math.min(width, height) / 2
        color: Qt.alpha(barra.cor, barra.cor.a * (barra.pressed ? 0.6 : barra.ativa ? 0.4 : 0.2))
        opacity: barra.size < 1 && barra.acordada ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: Tema.duracaoCurta } }
        Behavior on color { ColorAnimation { duration: Tema.duracaoCurta } }
    }
    background: Rectangle {
        x: barra.emPe ? barra.margem : 9
        y: barra.emPe ? 9 : barra.margem
        width: barra.emPe ? barra.grossura : barra.width - 18
        height: barra.emPe ? barra.height - 18 : barra.grossura
        radius: Math.min(width, height) / 2
        color: Qt.alpha(barra.cor, barra.cor.a * 0.1)
        opacity: barra.ativa && barra.size < 1 ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: Tema.duracaoCurta } }
    }
}
