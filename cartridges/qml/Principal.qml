import QtQuick
import QtQuick.Window

// Janela principal sem moldura: o QWindowKit cuida de borda, sombra e snap; a barra é nossa.
Window {
    id: janela

    // Mica fica desligado até o usuário validar o visual no Windows dele.
    property bool usarMica: false
    // Os testes rodam sem a ponte do QWindowKit (qwk_ponte.dll): sem agente, a barra é só um desenho.
    property bool semAgente: false
    // O texto no centro da barra; por padrão, o título da janela.
    property string tituloDaBarra: title
    // O que for declarado dentro de Principal vai para a área abaixo da barra.
    default property alias conteudo: area.data
    // Botões da página na barra: `inicio` à esquerda, `fim` à direita (cada um chama
    // `agente.setHitTestVisible(item, true)`, senão o QWindowKit trata o clique como arrasto).
    property alias inicio: barra.inicio
    property alias fim: barra.fim
    readonly property int alturaDaBarra: barra.altura
    readonly property int larguraDoBotao: barra.larguraDoBotao
    readonly property QtObject agente: carga.item
    // Só depois do `setup`: o QWindowKit falha ao registrar itens antes dele.
    property bool agentePronto: false

    color: usarMica ? "transparent" : Tema.fundo
    title: "Cartridges"

    // Tamanho e limites só depois do setup: antes, o QWindowKit os sobrescreve (P11).
    Component.onCompleted: {
        if (agente) {
            agente.setup(janela)
            agente.setWindowAttribute("dark-mode", Tema.escuro)
            if (usarMica)
                agente.setWindowAttribute("mica", true)
            barra.ligarAgente()
            agentePronto = true
        }
        width = 1100
        height = 700
        minimumWidth = 640
        minimumHeight = 480
    }

    Connections {
        target: Tema
        function onEscuroChanged() { if (janela.agente) janela.agente.setWindowAttribute("dark-mode", Tema.escuro) }
    }

    Loader {
        id: carga
        active: !janela.semAgente
        source: "AgenteDaJanela.qml"
    }

    BarraDeTitulo {
        id: barra
        anchors { top: parent.top; left: parent.left; right: parent.right }
        janela: janela
        agente: janela.agente
        titulo: janela.tituloDaBarra
    }

    Item {
        id: area
        anchors { top: barra.bottom; left: parent.left; right: parent.right; bottom: parent.bottom }
    }
}
