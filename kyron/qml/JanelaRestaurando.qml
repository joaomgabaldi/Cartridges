import QtQuick
import QtQuick.Window

// A janela "Restaurando o backup" da abertura, num motor próprio antes da biblioteca; `restaurando` vem do contexto.
Window {
    id: raiz
    objectName: "janelaRestaurando"

    readonly property bool semAgente: typeof comAgente === "undefined"
    readonly property QtObject agente: carga.item
    readonly property real alturaPedida: barra.altura + conteudo.implicitHeight

    title: "Kyron"
    width: 420
    minimumWidth: width
    maximumWidth: width
    // Ligadas ao conteúdo, e não ao `height`: o limite lido de volta travaria a janela na altura de antes.
    minimumHeight: alturaPedida
    maximumHeight: alturaPedida
    height: alturaPedida
    color: Tema.fundo
    flags: semAgente ? Qt.Window | Qt.CustomizeWindowHint | Qt.WindowTitleHint | Qt.WindowMinimizeButtonHint : Qt.Window
    visible: true

    onClosing: (fechar) => fechar.accepted = restaurando.podeFechar

    Loader {
        id: carga
        active: !raiz.semAgente
        source: "AgenteDaJanela.qml"
    }
    // O tamanho e os limites só depois do `setup`: antes, o QWindowKit os sobrescreve.
    Component.onCompleted: {
        if (agente) {
            agente.setup(raiz)
            agente.setWindowAttribute("dark-mode", true)
            barra.ligarAgente()
        }
        width = 420
        minimumWidth = 420
        maximumWidth = 420
        height = Qt.binding(() => alturaPedida)
        minimumHeight = Qt.binding(() => alturaPedida)
        maximumHeight = Qt.binding(() => alturaPedida)
    }

    BarraDeTitulo {
        id: barra
        objectName: "barraDeTituloDaRestauracao"
        anchors { top: parent.top; left: parent.left; right: parent.right }
        visible: !raiz.semAgente
        janela: raiz
        agente: raiz.agente
        titulo: "Kyron"
        comMaximizar: false
        comFechar: false
    }

    Column {
        id: conteudo
        x: 24
        y: raiz.semAgente ? 0 : barra.altura
        width: parent.width - 48
        topPadding: 12
        bottomPadding: 24
        spacing: 12

        Text {
            objectName: "tituloDaRestauracao"
            width: parent.width
            text: "Restaurando o backup"
            textFormat: Text.PlainText
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.Wrap
            color: Tema.texto
            font { family: Tema.fonte; pixelSize: Tema.titulo2; weight: Tema.pesoTitulo2 }
        }
        Text {
            objectName: "textoDaRestauracao"
            width: parent.width
            text: "O aplicativo será aberto quando a restauração terminar."
            textFormat: Text.PlainText
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.Wrap
            color: Tema.textoSecundario
            font { family: Tema.fonte; pixelSize: Tema.corpo }
        }
        Column {
            width: parent.width
            spacing: 6

            Text {
                objectName: "porcentagemDaRestauracao"
                width: parent.width
                text: restaurando.porcentagem
                textFormat: Text.PlainText
                horizontalAlignment: Text.AlignHCenter
                color: Tema.texto
                font { family: Tema.fonte; pixelSize: Tema.legenda; features: { "tnum": 1 } }
            }
            BarraDeProgresso {
                objectName: "barraDaRestauracao"
                width: parent.width
                value: restaurando.fracao
                Accessible.name: "Restaurando o backup"
            }
        }
    }

    Rectangle {
        anchors.fill: parent
        z: 1000
        enabled: false
        visible: !raiz.semAgente
        radius: 8
        color: "transparent"
        border { width: 1; color: Tema.contorno }
    }
}
