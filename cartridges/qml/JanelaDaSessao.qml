import QtQuick
import QtQuick.Window

// A janela "Jogando {nome}" da sessão manual (D50, R3): como a `Adw.Window` da `main` (`session_window.py`), sem moldura,
// com a barra própria de 47 px (título centrado, minimizar e fechar, sem maximizar), 300×150 no total e tamanho fixo.
// Fechar pela barra e o botão fazem o mesmo: encerrar a sessão com registro. Posta pelo Python.
Window {
    id: raiz
    objectName: "janelaDaSessao"

    // Os testes rodam sem a ponte do QWindowKit (como a `Principal`).
    property bool semAgente: false
    readonly property QtObject agente: carga.item
    property bool _posta: false

    title: sessao.tituloDaJanela
    // O `Adw.Window` da `main` não desce de 360x200, apesar do `set_default_size(300, 150)` (medido na janela real).
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

    // O botão no meio do que sobra abaixo da barra (`valign: center`, `vexpand`).
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

    // window.csd: o contorno claro de 1 px; o raio é o do DWM (R9).
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
