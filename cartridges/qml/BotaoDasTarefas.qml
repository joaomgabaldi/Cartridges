import QtQuick
import QtQuick.Controls.Basic

// O botão redondo do canto inferior esquerdo que abre as tarefas em andamento (D77).
// Não fica à vista: entra deslizando quando uma tarefa começa, recua depois de `entradaMs` e volta quando o mouse
// passa rente à borda, no canto. Cobre a área das páginas sem tirar nada delas: só o canto é vigiado, por um
// `HoverHandler`, e o botão recolhido não recebe o mouse. `painelDasTarefas` vem do contexto (cartridges/app.py).
Item {
    id: raiz
    objectName: "botaoDasTarefas"

    // "todos", "zerados" ou "jogo"; fora das duas bibliotecas o botão não aparece.
    property string pagina: "todos"
    property bool modalAberto: false
    property bool emBigPicture: false
    property bool emSessao: false

    // Tempos e medidas (propriedades para os testes): a entrada dura 10 s, a saída do canto 5 s, o canto é de 72 px
    // e, com o botão escondido, só a faixa de 16 px junto à borda o chama.
    property int entradaMs: 10000
    property int saidaMs: 5000
    property int canto: 72
    property int faixa: 16
    // Desligável para os testes chamarem `aoMover` à mão: o offscreen sintetiza movimentos do mouse por conta própria.
    property bool vigiarMouse: true
    readonly property int tamanho: 34
    readonly property int margem: 12

    function podeAgora() {
        return painelDasTarefas.podeMostrar(painelDasTarefas.quantas, pagina, modalAberto, emBigPicture, emSessao)
    }
    readonly property bool pode: podeAgora()
    property bool aVista: false
    property bool noCanto: false
    // Desligado só no instante em que o botão some sem deslizar.
    property bool deslizar: true
    readonly property bool girando: aVista
    // O lugar do botão à vista, que nunca desliza: a janela das tarefas se põe acima dele.
    readonly property Item alvo: lugarDoBotao
    property int vistas: 0

    // Nada some com o botão à vista e nada aparece sem tarefa: o que muda a regra reavalia.
    function reavaliar() {
        // Na sessão e no Big Picture o botão está atrás da camada cheia: some sem deslizar.
        if (!podeAgora()) esconder(!(emSessao || emBigPicture))
    }
    onPodeChanged: reavaliar()

    function mostrar() {
        recuo.stop()
        aVista = true
    }
    function esconder(animado) {
        recuo.stop()
        if (!animado) deslizar = false
        aVista = false
        deslizar = true
    }
    function agendar(espera) {
        recuo.interval = espera
        recuo.restart()
    }
    // Com o mouse no canto, a entrada automática não tira o botão de baixo dele; sair do canto agenda a saída de novo.
    function recolher() {
        if (!noCanto) aVista = false
    }
    function aoEntrar() {
        if (podeAgora()) mostrar()
    }
    function aoSair() { agendar(saidaMs) }

    function aoMover(x, y) {
        // Escondido, só a faixa colada à borda chama o botão; à vista, o canto cobre o botão inteiro, para o mouse
        // chegar até ele sem que recue.
        var dentro = x < (aVista ? canto : faixa) && y > height - canto
        // Sem tarefas não há o que mostrar, mas o canto continua anotado: uma tarefa que começa com o mouse parado
        // ali não recua debaixo dele.
        if (painelDasTarefas.quantas === 0) {
            noCanto = dentro
            return
        }
        if (dentro) {
            // Fechar a janela com o mouse ainda no canto deixa o botão escondido: o próximo movimento o traz de volta.
            if (!noCanto || !aVista) {
                noCanto = true
                aoEntrar()
            }
        } else if (noCanto) {
            noCanto = false
            aoSair()
        }
    }
    function aoDeixar() {
        if (noCanto) {
            noCanto = false
            aoSair()
        }
    }
    // O botão fica por cima do vigia e tira o hover dele: em cima do botão o mouse continua no canto, e o botão não recua.
    function aoPassarNoBotao(sobre) {
        if (sobre) {
            noCanto = true
            recuo.stop()
        } else if (!vigiaDoHover.hovered) {
            aoDeixar()
        }
    }

    Component.onCompleted: vistas = painelDasTarefas.quantas

    Connections {
        target: painelDasTarefas
        function onAlterado() {
            var quantas = painelDasTarefas.quantas
            var nova = quantas > raiz.vistas
            raiz.vistas = quantas
            raiz.reavaliar()
            if (nova && raiz.podeAgora()) {
                raiz.mostrar()
                raiz.agendar(raiz.entradaMs)
            }
        }
    }

    Timer {
        id: recuo
        objectName: "recuoDasTarefas"
        onTriggered: raiz.recolher()
    }

    // Só no canto: um `HoverHandler` do tamanho da página, por cima dela, tirava o hover de todas as capas (mesmo com
    // `blocking: false`, medido no Qt 6.12).
    Item {
        id: vigia
        objectName: "vigiaDoCanto"
        y: raiz.height - raiz.canto
        width: raiz.aVista ? raiz.canto : raiz.faixa
        height: raiz.canto
        HoverHandler {
            id: vigiaDoHover
            enabled: raiz.vigiarMouse
            onPointChanged: raiz.aoMover(point.position.x, vigia.y + point.position.y)
            onHoveredChanged: if (!hovered && !sobreOBotao.hovered) raiz.aoDeixar()
        }
    }

    Item {
        id: lugarDoBotao
        objectName: "alvoDoBotao"
        x: raiz.margem
        y: raiz.height - raiz.margem - raiz.tamanho
        width: raiz.tamanho
        height: raiz.tamanho
    }

    Button {
        id: circulo
        objectName: "circuloDasTarefas"
        width: raiz.tamanho
        height: raiz.tamanho
        x: raiz.aVista ? raiz.margem : -(raiz.tamanho + raiz.margem)
        y: lugarDoBotao.y
        // Recolhido, o botão não recebe nada: o clique no lugar dele chega à capa.
        enabled: raiz.aVista && raiz.pode
        visible: x + width > 0
        Accessible.name: "Tarefas em andamento"
        HoverHandler {
            id: sobreOBotao
            enabled: raiz.vigiarMouse
            onHoveredChanged: raiz.aoPassarNoBotao(hovered)
        }
        // A dica da libadwaita; acima do botão, porque ele fica rente ao fundo da janela.
        Dica {
            texto: "Tarefas em andamento"
            ativa: circulo.hovered
            y: -height - 6
        }
        onClicked: {
            raiz.esconder(true)
            painelDasTarefas.mostrar()
        }

        Behavior on x {
            enabled: raiz.deslizar
            NumberAnimation { objectName: "deslizeDasTarefas"; duration: Tema.duracaoMedia; easing.type: Easing.OutCubic }
        }

        // `view-refresh-symbolic`, branco a 90% (`.osd`).
        contentItem: Item {
            Icone {
                id: glifo
                anchors.centerIn: parent
                nome: "view-refresh"
                cor: "white"
                opacity: 0.9
            }
        }
        // `.circular.osd`: preto a 65%; ao passar, 15% de branco na mistura; pressionado, 25%. Com a sombra do
        // `.botao-tarefas`: `0 2px 8px rgba(0, 0, 0, .35)`.
        background: Rectangle {
            radius: width / 2
            color: circulo.down ? Qt.rgba(0.25, 0.25, 0.25, 0.65)
                : circulo.hovered ? Qt.rgba(0.15, 0.15, 0.15, 0.65) : Qt.rgba(0, 0, 0, 0.65)
            Behavior on color { ColorAnimation { duration: Tema.duracaoCurta } }
            Sombra { camadas: [[2, 8, 0, 0, 0, 0, 0.35]]; raio: parent.radius }
        }
        AnelDeFoco { ativo: circulo.visualFocus; raio: 17; afastamento: 1 }

        // Gira enquanto à vista.
        RotationAnimator {
            id: giro
            objectName: "giroDasTarefas"
            target: glifo
            from: 0
            to: 360
            duration: 1200
            loops: Animation.Infinite
            running: raiz.girando
            onRunningChanged: if (!running) glifo.rotation = 0
        }
    }
}
