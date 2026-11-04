import QtQuick

// Uma página da pilha de um seletor (`Gtk.Stack` em `crossfade`): ocupa a área toda, aparece e some em 200 ms.
// Fora de vista não é `visible`, então não recebe foco nem clique.
Item {
    id: pagina

    property bool ativa: false

    anchors.fill: parent
    opacity: ativa ? 1 : 0
    visible: opacity > 0
    Behavior on opacity {
        enabled: Tema.animacoes
        NumberAnimation { duration: Tema.duracaoCurta; easing { type: Easing.Bezier; bezierCurve: Tema.curva } }
    }
}
