import QtQuick

LinhaDoGrupo {
    id: linha

    default property alias botoes: lado.data
    property Item ativavel

    reservaADireita: lado.width
    sobre: !!ativavel && passando.hovered
    pressionada: !!ativavel && areaDaLinha.pressed

    // O `HoverHandler` vê o ponteiro também sobre os botões do fim, que o `MouseArea` não via.
    HoverHandler { id: passando; enabled: !!linha.ativavel }
    MouseArea {
        id: areaDaLinha
        anchors.fill: parent
        enabled: !!linha.ativavel
        onClicked: if (linha.ativavel.enabled) linha.ativavel.click()
    }

    Row {
        id: lado
        anchors { right: parent.right; rightMargin: 14; verticalCenter: parent.verticalCenter }
        spacing: 6
    }
}
