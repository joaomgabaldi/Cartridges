import QtQuick

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

    MouseArea {
        id: areaDaLinha
        anchors.fill: parent
        hoverEnabled: true
        onPressed: amostra.apertou()
        onClicked: amostra.alternar()
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
