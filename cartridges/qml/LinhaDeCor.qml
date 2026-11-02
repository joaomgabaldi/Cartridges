import QtQuick

// Uma linha com título, subtítulo e, à direita, a amostra de cor que abre o `SeletorDeCor` num balão (como a linha da
// fita do editor). Cada movimento no seletor emite `escolhida`; quem usa grava e devolve a cor em `cor`. Fora do padrão
// (`padrao: false`) aparece o botão de voltar a ele. `aberta` e `fechada` contam do balão (o pulso das conquistas mostra a
// própria cor só enquanto ele está aberto). Desabilitada, apaga a 50% como as outras linhas.
LinhaDoGrupo {
    id: linha

    property color cor
    property bool padrao: true
    property string dicaDaAmostra

    signal escolhida(color cor)
    signal aberta()
    signal fechada()
    signal voltar()

    reservaADireita: lado.width
    sobre: areaDaLinha.containsMouse
    pressionada: areaDaLinha.pressed

    // A linha inteira abre o balão (`activatable-widget`).
    MouseArea {
        id: areaDaLinha
        anchors.fill: parent
        hoverEnabled: true
        onClicked: amostra.click()
    }

    Row {
        id: lado
        anchors { right: parent.right; rightMargin: 14; verticalCenter: parent.verticalCenter }
        spacing: 6

        Botao {
            objectName: linha.objectName + "Voltar"
            visible: !linha.padrao
            estilo: "plano"
            icone: "edit-undo"
            dica: "Voltar à cor padrão"
            onClicked: linha.voltar()
        }
        AmostraDeCor {
            id: amostra
            objectName: linha.objectName + "Amostra"
            cor: linha.cor
            dica: linha.dicaDaAmostra
            nomeDoBalao: linha.objectName + "Balao"
            nomeDoSeletor: linha.objectName + "Seletor"
            onEscolhida: cor => linha.escolhida(cor)
            onAberta: linha.aberta()
            onFechada: linha.fechada()
        }
    }
}
