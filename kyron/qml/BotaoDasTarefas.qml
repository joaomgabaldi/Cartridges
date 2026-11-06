import QtQuick
import QtQuick.Controls.Basic

// O botão redondo do canto inferior esquerdo que abre as tarefas em andamento; entra deslizando quando uma tarefa começa
// e volta quando o mouse passa rente ao canto.
Item {
    id: raiz
    objectName: "botaoDasTarefas"

    property string pagina: "todos"
    property bool modalAberto: false
    property bool emBigPicture: false
    property bool emSessao: false

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
    property bool deslizar: true
    readonly property bool girando: aVista
    readonly property Item alvo: lugarDoBotao
    property int vistas: 0

    function reavaliar() {
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
    function recolher() {
        if (!noCanto) aVista = false
    }
    function aoEntrar() {
        if (podeAgora()) mostrar()
    }
    function aoSair() { agendar(saidaMs) }

    function aoMover(x, y) {
        var dentro = x < (aVista ? canto : faixa) && y > height - canto
        if (painelDasTarefas.quantas === 0) {
            noCanto = dentro
            return
        }
        if (dentro) {
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
    // O botão fica por cima do vigia e tira o hover dele: em cima do botão o mouse continua no canto.
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

    // Só no canto: um `HoverHandler` do tamanho da página tirava o hover de todas as capas (mesmo com `blocking: false`,
    // medido no Qt 6.12).
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
        enabled: raiz.aVista && raiz.pode
        visible: x + width > 0
        Accessible.name: "Tarefas em andamento"
        HoverHandler {
            id: sobreOBotao
            enabled: raiz.vigiarMouse
            onHoveredChanged: raiz.aoPassarNoBotao(hovered)
        }
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

        contentItem: Item {
            Icone {
                id: glifo
                anchors.centerIn: parent
                nome: "view-refresh"
                cor: "white"
                opacity: 0.9
            }
        }
        background: Rectangle {
            radius: width / 2
            color: circulo.down ? Qt.rgba(0.25, 0.25, 0.25, 0.65)
                : circulo.hovered ? Qt.rgba(0.15, 0.15, 0.15, 0.65) : Qt.rgba(0, 0, 0, 0.65)
            Behavior on color { ColorAnimation { duration: Tema.duracaoCurta } }
            // Sem deslocamento: os anéis deslocados deixam uma meia-lua sob o círculo translúcido, que parece uma borda.
            Sombra { camadas: [[0, 8, 0, 0, 0, 0, 0.3]]; raio: parent.radius }
        }
        AnelDeFoco { ativo: circulo.visualFocus; raio: 17; afastamento: 1 }

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
