import QtQuick
import QtQuick.Window
import QWindowKit

// Janela principal sem moldura: o QWindowKit cuida de borda, sombra e snap; a barra é nossa.
Window {
    id: janela

    // Mica fica desligado até o usuário validar o visual no Windows dele.
    property bool usarMica: false
    // O que for declarado dentro de Principal vai para a área abaixo da barra.
    default property alias conteudo: area.data
    readonly property int alturaDaBarra: barra.altura
    readonly property int larguraDoBotao: barra.larguraDoBotao

    color: usarMica ? "transparent" : Tema.fundo
    title: "Cartridges"

    // Tamanho e limites só depois do setup: antes, o QWindowKit os sobrescreve (P11).
    Component.onCompleted: {
        agente.setup(janela)
        agente.setWindowAttribute("dark-mode", Tema.escuro)
        if (usarMica)
            agente.setWindowAttribute("mica", true)
        width = 1100
        height = 700
        minimumWidth = 640
        minimumHeight = 480
    }

    Connections {
        target: Tema
        function onEscuroChanged() { agente.setWindowAttribute("dark-mode", Tema.escuro) }
    }

    WindowAgent { id: agente }

    BarraDeTitulo {
        id: barra
        anchors { top: parent.top; left: parent.left; right: parent.right }
        janela: janela
        agente: agente
        titulo: janela.title
    }

    Item {
        id: area
        anchors { top: barra.bottom; left: parent.left; right: parent.right; bottom: parent.bottom }
    }
}
