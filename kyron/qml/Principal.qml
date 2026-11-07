import QtQuick
import QtQuick.Window

// Janela principal sem moldura: o QWindowKit cuida de borda, sombra e snap; a barra é nossa.
Window {
    id: janela

    // Mica fica desligado até o usuário validar o visual no Windows dele.
    property bool usarMica: false
    // Os testes rodam sem a ponte do QWindowKit (qwk_ponte.dll): sem agente, a barra é só um desenho.
    property bool semAgente: false
    property string tituloDaBarra: title
    // O que for declarado dentro de Principal vai para a área, por cima da barra: um modal cobre a barra; as páginas descem `alturaDoTopo`.
    default property alias conteudo: area.data
    // Botões da página na barra: `inicio` à esquerda, `fim` à direita (cada um chama
    // `agente.setHitTestVisible(item, true)`, senão o QWindowKit trata o clique como arrasto).
    property alias inicio: barra.inicio
    property alias fim: barra.fim
    readonly property int alturaDaBarra: barra.altura
    readonly property int larguraDoBotao: barra.larguraDoBotao
    readonly property int alturaDoTopo: telaCheia ? 0 : barra.altura
    readonly property QtObject agente: carga.item
    // Só depois do `setup`: o QWindowKit falha ao registrar itens antes dele.
    property bool agentePronto: false
    property bool telaCheia: false
    // Com um modal na frente a barra não arrasta nem aciona nada (nem o Snap Layouts do maximizar).
    property bool barraTrancada: false
    // A saída do modal leva ~127 ms: a barra só sobe de novo depois, para não pular sobre o escurecimento.
    property bool _saindo: false
    onBarraTrancadaChanged: {
        _saindo = !barraTrancada && Tema.animacoes
        if (_saindo) fimDaSaida.restart()
    }
    Timer { id: fimDaSaida; interval: 140; onTriggered: janela._saindo = false }
    property alias sombraDaBarra: barra.sombra
    property alias barraTransparente: barra.transparente
    // O que passa por baixo da barra transparente: fica sob ela mesmo quando um modal a põe abaixo da área.
    property alias fundoDaBarra: fundoSobABarra.data
    property real deslocamentoDaBarra: 0
    readonly property Item barraDeTitulo: barra

    color: usarMica ? "transparent" : Tema.fundo
    title: "Kyron"

    // Tamanho e limites só depois do setup: antes, o QWindowKit os sobrescreve.
    Component.onCompleted: {
        if (agente) {
            agente.setup(janela)
            agente.setWindowAttribute("dark-mode", true)
            if (usarMica)
                agente.setWindowAttribute("mica", true)
            barra.ligarAgente()
            agentePronto = true
        }
        // Antes de mostrar: a janela só aparece desenhada, com as capas; opcional nos testes.
        if (typeof cortinaDaAbertura !== "undefined") cortinaDaAbertura.cobrir(janela)
        width = 1170
        height = 795
        minimumWidth = 360
        minimumHeight = 100
        // Opcional nos testes: o lugar e o tamanho gravados ao fechar valem depois do inicial.
        const servico = typeof geometria === "undefined" ? null : geometria
        if (servico) servico.restaurar(janela)
    }

    Loader {
        id: carga
        active: !janela.semAgente
        source: "AgenteDaJanela.qml"
    }

    Item {
        id: fundoSobABarra
        visible: !janela.telaCheia
        anchors { top: parent.top; left: parent.left; right: parent.right }
        height: barra.altura
        clip: true
    }

    BarraDeTitulo {
        id: barra
        objectName: "barraDeTitulo"
        visible: !janela.telaCheia
        enabled: !janela.barraTrancada
        z: janela.barraTrancada || janela._saindo ? 0 : 1
        anchors { top: parent.top; left: parent.left; right: parent.right }
        transform: Translate { x: janela.deslocamentoDaBarra }
        janela: janela
        agente: janela.agente
        titulo: janela.tituloDaBarra
    }

    Item {
        id: area
        objectName: "areaDaJanela"
        anchors.fill: parent
    }

    Rectangle {
        objectName: "contornoDaJanela"
        anchors.fill: parent
        z: 1000
        enabled: false
        visible: janela.visibility === Window.Windowed && !janela.telaCheia
        radius: 8
        color: "transparent"
        border { width: 1; color: Tema.contorno }
    }
}
