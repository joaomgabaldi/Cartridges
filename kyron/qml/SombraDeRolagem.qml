import QtQuick

// A sombra que cai de uma barra sobre o conteúdo rolado, que corre por baixo dela. Fica abaixo do item pai; o pai
// precisa de `z` acima do conteúdo para que ela o cubra.
Rectangle {
    property bool ativa: false

    anchors { left: parent.left; right: parent.right; top: parent.bottom }
    height: 10
    enabled: false
    opacity: ativa ? 1 : 0
    visible: opacity > 0
    Behavior on opacity { enabled: Tema.animacoes; NumberAnimation { duration: 150 } }
    gradient: Gradient {
        GradientStop { position: 0; color: Tema.sombraDaBarra }
        GradientStop { position: 1; color: "transparent" }
    }
}
