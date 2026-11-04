import QtQuick

// A `Adw.ActionRow` com botões no fim (os `[suffix]` da `main`). Sem `ativavel`, a linha não aciona nada: só os botões
// respondem (a "Pasta dos saves" e o "Buscar atualizações"). Com ele, clicar na linha aciona esse botão
// (`activatable-widget`), com hover de 4% e 8%; é o caso dos botões planos de ícone das fitas.
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
