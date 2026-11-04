import QtQuick
import QtQuick.Window

// A janela "Tarefas em andamento": de topo, sem moldura e com a barra própria (título, minimizar e fechar), não modal,
// com entrada na barra de tarefas. Um bloco por tarefa; continua aberta quando a última acaba. Posta pelo Python logo
// acima do botão (`alvo`), depois do primeiro quadro; invisível até lá. `painelDasTarefas` vem do contexto.
Window {
    id: raiz
    objectName: "janelaDasTarefas"

    // O lugar do botão à vista (BotaoDasTarefas.alvo), posto por quem a carrega.
    property Item alvo: null
    property bool pronta: false
    // Os testes rodam sem a ponte do QWindowKit.
    property bool semAgente: false
    readonly property QtObject agente: carga.item

    // O nome de uma tarefa não quebra: um nome longo alarga a janela, com 360 de mínimo.
    property real larguraDoConteudo: 0
    readonly property real larguraPedida: Math.max(360, larguraDoConteudo + 48)

    title: "Tarefas em andamento"
    width: larguraPedida
    minimumWidth: larguraPedida
    maximumWidth: larguraPedida
    // Ligadas ao conteúdo, e não ao `height`: o limite lido de volta travaria a janela na altura de antes.
    minimumHeight: alturaPedida
    maximumHeight: alturaPedida
    height: alturaPedida
    // O aviso de erro precisa de lugar, se a lista for curta.
    readonly property real alturaPedida: Math.max(barra.altura + conteudo.implicitHeight, aviso.aberto ? aviso._alturaPedida + 2 * aviso.margemV : 0)
    color: Tema.fundo
    opacity: pronta ? 1 : 0
    transientParent: null  // solta: não some junto com a principal
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
        width = Qt.binding(() => larguraPedida)
        minimumWidth = Qt.binding(() => larguraPedida)
        maximumWidth = Qt.binding(() => larguraPedida)
        height = Qt.binding(() => alturaPedida)
        minimumHeight = Qt.binding(() => alturaPedida)
        maximumHeight = Qt.binding(() => alturaPedida)
    }

    function medir() {
        var maior = 0
        for (var i = 0; i < repetidor.count; ++i) {
            var bloco = repetidor.itemAt(i)
            if (bloco) maior = Math.max(maior, bloco.larguraDoNome)
        }
        larguraDoConteudo = maior
    }

    // A superfície e a altura da moldura só existem depois do primeiro quadro.
    onFrameSwapped: {
        if (pronta) return
        if (alvo) {
            var ponto = alvo.mapToGlobal(0, 0)
            painelDasTarefas.posicionar(raiz, ponto.x, ponto.y, alvo.width, alvo.height)
        }
        pronta = true
    }
    // Com a principal escondida (fechada com trabalho em andamento), fechar esta encerra o app. Fechada com o aviso
    // aberto: libera o erro inesperado já (se o fechamento for recusado, o `onDispensado` nunca viria).
    onClosing: { painelDasTarefas.avisoFechado(); painelDasTarefas.janelaFechada() }

    Connections {
        target: painelDasTarefas
        function onFrente() {
            if (raiz.visibility === Window.Minimized) raiz.showNormal()
            raiz.raise()
            raiz.requestActivate()
        }
        function onAvisoPedido(titulo, corpo) {
            aviso.abrir(titulo, corpo, [], "")
            raiz.raise()
            raiz.requestActivate()
        }
    }

    Item {
        anchors.fill: parent
        focus: true
        Keys.onEscapePressed: raiz.close()
    }

    BarraDeTitulo {
        id: barra
        objectName: "barraDasTarefas"
        anchors { top: parent.top; left: parent.left; right: parent.right }
        janela: raiz
        agente: raiz.agente
        titulo: "Tarefas em andamento"
        comMaximizar: false
    }

    Column {
        id: conteudo
        x: 24
        y: barra.altura
        width: parent.width - 48
        topPadding: 12
        bottomPadding: 24
        spacing: 18

        Repeater {
            id: repetidor
            model: painelDasTarefas.lista
            onItemAdded: raiz.medir()
            onItemRemoved: raiz.medir()
            delegate: Column {
                id: bloco
                required property string nome
                required property int feitos
                required property int total
                width: conteudo.width
                spacing: 6
                readonly property real larguraDoNome: nomeDaTarefa.implicitWidth

                Text {
                    id: nomeDaTarefa
                    objectName: "nomeDaTarefa"
                    readonly property bool textoPuro: textFormat === Text.PlainText
                    width: parent.width
                    text: bloco.nome
                    textFormat: Text.PlainText
                    wrapMode: Text.NoWrap
                    onImplicitWidthChanged: raiz.medir()
                    color: Tema.texto
                    font { family: Tema.fonte; pixelSize: Tema.corpo; weight: Tema.pesoForte }
                }
                Text {
                    objectName: "contagemDaTarefa"
                    text: bloco.feitos + " de " + bloco.total
                    textFormat: Text.PlainText
                    color: Tema.textoSecundario
                    font { family: Tema.fonte; pixelSize: Tema.corpo }
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
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            visible: painelDasTarefas.quantas === 0
            text: "Nenhuma tarefa em andamento"
            textFormat: Text.PlainText
            color: Tema.textoSecundario
            font { family: Tema.fonte; pixelSize: Tema.corpo }
        }
    }

    // O contorno claro de 1 px; o raio é o do DWM.
    Rectangle {
        objectName: "contornoDasTarefas"
        anchors.fill: parent
        z: 1000
        enabled: false
        visible: raiz.visibility === Window.Windowed
        radius: 8
        color: "transparent"
        border { width: 1; color: Tema.contorno }
    }

    // Um erro inesperado com a principal escondida.
    DialogoDeAviso {
        id: aviso
        objectName: "avisoNaJanelaDasTarefas"
        onDispensado: painelDasTarefas.avisoFechado()
    }
}
