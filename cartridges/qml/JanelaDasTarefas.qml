import QtQuick
import QtQuick.Window

// A janela "Tarefas em andamento" (D77): de topo, com a moldura nativa (só minimizar e fechar), não modal, com entrada
// na barra de tarefas. Um bloco por tarefa; continua aberta quando a última acaba. Posta pelo Python logo acima do
// botão (`alvo`), depois do primeiro quadro; invisível até lá. `painelDasTarefas` vem do contexto.
Window {
    id: raiz
    objectName: "janelaDasTarefas"

    // O lugar do botão à vista (BotaoDasTarefas.alvo), posto por quem a carrega.
    property Item alvo: null
    property bool pronta: false

    title: "Tarefas em andamento"
    width: 360
    minimumWidth: width
    maximumWidth: width
    // Ligadas ao conteúdo, e não ao `height`: o limite lido de volta travaria a janela na altura de antes.
    minimumHeight: conteudo.implicitHeight
    maximumHeight: conteudo.implicitHeight
    height: conteudo.implicitHeight
    color: Tema.fundo
    opacity: pronta ? 1 : 0
    transientParent: null  // solta: não some junto com a principal
    flags: Qt.Window | Qt.CustomizeWindowHint | Qt.WindowTitleHint | Qt.WindowSystemMenuHint
        | Qt.WindowMinimizeButtonHint | Qt.WindowCloseButtonHint
    visible: true

    // A superfície e a altura da moldura só existem depois do primeiro quadro.
    onFrameSwapped: {
        if (pronta) return
        if (alvo) {
            var ponto = alvo.mapToGlobal(0, 0)
            painelDasTarefas.posicionar(raiz, ponto.x, ponto.y)
        }
        pronta = true
    }
    onClosing: painelDasTarefas.janelaFechada()

    Connections {
        target: painelDasTarefas
        function onFrente() {
            if (raiz.visibility === Window.Minimized) raiz.showNormal()
            raiz.raise()
            raiz.requestActivate()
        }
    }

    Item {
        anchors.fill: parent
        focus: true
        Keys.onEscapePressed: raiz.close()
    }

    Column {
        id: conteudo
        x: 24
        width: parent.width - 48
        topPadding: 12
        bottomPadding: 24
        spacing: 18

        Repeater {
            model: painelDasTarefas.lista
            delegate: Column {
                id: bloco
                required property string nome
                required property int feitos
                required property int total
                width: conteudo.width
                spacing: 6

                Text {
                    objectName: "nomeDaTarefa"
                    readonly property bool textoPuro: textFormat === Text.PlainText
                    width: parent.width
                    text: bloco.nome
                    textFormat: Text.PlainText
                    wrapMode: Text.Wrap
                    color: Tema.texto
                    font { family: Tema.fonte; pixelSize: 15; weight: Font.DemiBold }
                }
                Text {
                    objectName: "contagemDaTarefa"
                    text: bloco.feitos + " de " + bloco.total
                    textFormat: Text.PlainText
                    color: Tema.textoSecundario
                    font { family: Tema.fonte; pixelSize: 13 }
                }
                BarraDeProgresso {
                    objectName: "barraDaTarefa"
                    width: parent.width
                    value: bloco.total > 0 ? bloco.feitos / bloco.total : 0
                    Accessible.name: bloco.nome
                    Accessible.role: Accessible.ProgressBar
                    readonly property string nomeAcessivel: Accessible.name
                    readonly property string papelAcessivel: Accessible.role === Accessible.ProgressBar ? "ProgressBar" : ""
                }
            }
        }

        Text {
            objectName: "avisoDeVazio"
            visible: painelDasTarefas.quantas === 0
            text: "Nenhuma tarefa em andamento"
            textFormat: Text.PlainText
            color: Tema.textoSecundario
            font { family: Tema.fonte; pixelSize: 14 }
        }
    }
}
