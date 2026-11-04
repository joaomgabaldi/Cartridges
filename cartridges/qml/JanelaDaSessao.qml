import QtQuick
import QtQuick.Window

// A janela "Jogando {nome}" da sessão manual: sem moldura, com a barra própria, tamanho fixo. Posta pelo Python.
Window {
    id: raiz
    objectName: "janelaDaSessao"

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
    transientParent: null
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

    // O retângulo da janela só vale depois do primeiro quadro e da moldura removida.
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
