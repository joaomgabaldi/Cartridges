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
    // O que for declarado dentro de Principal vai para a área, que ocupa a janela inteira, por cima da barra: um modal
    // cobre a barra (J05); as páginas descem `alturaDoTopo`.
    default property alias conteudo: area.data
    // Botões da página na barra: `inicio` à esquerda, `fim` à direita (cada um chama
    // `agente.setHitTestVisible(item, true)`, senão o QWindowKit trata o clique como arrasto).
    property alias inicio: barra.inicio
    property alias fim: barra.fim
    readonly property int alturaDaBarra: barra.altura
    readonly property int larguraDoBotao: barra.larguraDoBotao
    // Onde as páginas começam: abaixo da barra, ou no topo em tela cheia.
    readonly property int alturaDoTopo: telaCheia ? 0 : barra.altura
    readonly property QtObject agente: carga.item
    // Só depois do `setup`: o QWindowKit falha ao registrar itens antes dele.
    property bool agentePronto: false
    // Tela cheia (Big Picture): a barra some e a área começa no topo.
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
    // A linha de baixo da barra, com o conteúdo rolado.
    property alias sombraDaBarra: barra.sombra
    // A barra sem fundo, com a página dos detalhes por baixo.
    property alias barraTransparente: barra.transparente
    // O que passa por baixo da barra transparente: fica sob ela mesmo quando um modal a põe abaixo da área (J05).
    property alias fundoDaBarra: fundoSobABarra.data

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
        // gschema da `main`: 1170x795; window.blp: mínimo 360x100.
        width = 1170
        height = 795
        minimumWidth = 360
        minimumHeight = 100
        // Depois do tamanho de hoje: o lugar e o tamanho gravados ao fechar (D87); sem nada gravado, fica este.
        // Opcional: os arneses dos testes não põem `geometria` no contexto.
        const servico = typeof geometria === "undefined" ? null : geometria
        if (servico) servico.restaurar(janela)
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
        // Livre, fica acima da área e recebe o mouse direto; com modal, a área (e o modal nela) a cobre.
        z: janela.barraTrancada || janela._saindo ? 0 : 1
        anchors { top: parent.top; left: parent.left; right: parent.right }
        janela: janela
        agente: janela.agente
        titulo: janela.tituloDaBarra
    }

    Item {
        id: area
        objectName: "areaDaJanela"
        anchors.fill: parent
    }

    // window.csd: o contorno claro de 1 px; some com a janela maximizada ou em tela cheia. O raio é o do DWM (R9).
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
