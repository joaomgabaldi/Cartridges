import QtQuick
import QtQuick.Window

// A janela "Jogando {nome}" da sessão manual: sem moldura, com a barra própria de 47 px (título centrado, minimizar e
// fechar, sem maximizar), 300×150 no total e tamanho fixo. Fechar pela barra e o botão fazem o mesmo: encerrar a sessão
// com registro. Posta pelo Python.
Window {
    id: raiz
    objectName: "janelaDaSessao"

    // Os testes rodam sem a ponte do QWindowKit.
    property bool semAgente: false
    readonly property QtObject agente: carga.item
    property bool _posta: false

    title: sessao.tituloDaJanela
    width: 360
    height: 200
    minimumWidth: width
    maximumWidth: width
    minimumHeight: height
    maximumHeight: height
    color: Tema.fundo
    transientParent: null  // solta: não some junto com a janela principal
    flags: Qt.Window
    visible: true

    Loader {
        id: carga
        active: !raiz.semAgente
        source: "AgenteDaJanela.qml"
    }
    Connections {
        target: Tema
        function onEscuroChanged() { if (raiz.agente) raiz.agente.setWindowAttribute("dark-mode", Tema.escuro) }
    }
    // O tamanho e os limites só depois do `setup`: antes, o QWindowKit os sobrescreve.
    Component.onCompleted: {
        if (agente) {
            agente.setup(raiz)
            agente.setWindowAttribute("dark-mode", Tema.escuro)
            barra.ligarAgente()
        }
        width = 360
        height = 200
        minimumWidth = 360
        maximumWidth = 360
        minimumHeight = 200
        maximumHeight = 200
    }

    // Acima do relógio: o retângulo da janela só vale depois do primeiro quadro e da moldura removida.
    onFrameSwapped: {
        if (_posta) return
        _posta = true
        sessao.posicionarJanelaManual(raiz)
    }
    onClosing: sessao.janelaManualFechada()

    BarraDeTitulo {
        id: barra
        objectName: "barraDaJanelaDaSessao"
        anchors { top: parent.top; left: parent.left; right: parent.right }
        janela: raiz
        agente: raiz.agente
        titulo: sessao.tituloDaJanela
        comMaximizar: false
    }

    Botao {
        id: botao
        objectName: "botaoTermineiDaJanela"
        anchors { horizontalCenter: parent.horizontalCenter; verticalCenter: parent.verticalCenter; verticalCenterOffset: barra.altura / 2 }
        focus: true
        estilo: "sugestao"
        pilula: true
        text: "Já terminei de jogar"
        onClicked: sessao.janelaManualFechada()
    }

    // O contorno claro de 1 px; o raio é o do DWM.
    Rectangle {
        objectName: "contornoDaJanelaDaSessao"
        anchors.fill: parent
        z: 1000
        enabled: false
        visible: raiz.visibility === Window.Windowed
        radius: 8
        color: "transparent"
        border { width: 1; color: Tema.contorno }
    }
}
