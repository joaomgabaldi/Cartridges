import QtQuick
import QtQuick.Controls.Basic

// As horas jogadas por dia, em linha (D54). Só desenha: a geometria (posições, grade, rótulos, quebras) vem pronta do
// `historico` (cartridges/session_history.py); aqui só entram as medidas em pixels e as cores do Tema.
Item {
    id: raiz
    objectName: "graficoDoHistorico"

    // As margens do desenho, em pixels.
    readonly property int margemEsquerda: 44
    readonly property int margemInferior: 24
    readonly property int margemSuperior: 8
    readonly property int margemDireita: 12

    readonly property var geometria: historico.grafico
    // Quantas vezes o desenho foi refeito (os testes esperam por ele).
    property int desenhos: 0
    // O x do mouse sobre o gráfico (-1 fora dele) e a dica do dia mais perto dele.
    property real xDoMouse: -1
    readonly property real larguraUtil: width - margemEsquerda - margemDireita
    readonly property string dicaDoMouse: {
        var g = geometria
        if (xDoMouse < 0 || !g.horas || g.horas.length === 0) return ""
        return historico.dica(larguraUtil > 0 ? (xDoMouse - margemEsquerda) / larguraUtil : 0)
    }

    Accessible.role: Accessible.Graphic
    Accessible.name: "Horas jogadas por dia"
    Accessible.description: historico.totalDoPeriodo

    onGeometriaChanged: tela.requestPaint()

    function cor(c, alfa) { return Qt.rgba(c.r, c.g, c.b, alfa) }

    // Escreve `t` com o centro vertical em `y`; `alinhamento` é onde `x` cai no texto (0 = começo, 0,5 = meio, 1 = fim).
    // Preso à área: um "set 26" centrado num dia 1º perto da borda não sai cortado.
    function escrever(ctx, t, x, y, alinhamento) {
        var largura = ctx.measureText(t).width
        ctx.fillText(t, Math.min(Math.max(0, x - largura * alinhamento), width - largura), y)
    }

    function desenhar(ctx) {
        ctx.reset()
        var g = geometria
        if (!g.horas || g.horas.length === 0) return
        var w = width, h = height
        var baseY = h - margemInferior
        var alturaUtil = baseY - margemSuperior
        var n = g.horas.length
        var ultima = g.posicoes[n - 1]
        function xDe(i) { return n === 1 ? margemEsquerda + larguraUtil / 2 : margemEsquerda + larguraUtil * g.posicoes[i] / ultima }
        function yDe(valor) { return baseY - alturaUtil * valor / g.topo }

        ctx.font = "9.84px '" + Tema.fonte + "'"  // .caption, 82% de 12 px
        ctx.textAlign = "left"
        ctx.textBaseline = "middle"

        // Grade e eixo Y.
        ctx.lineWidth = 1
        for (var i = 0; i < g.grade.length; ++i) {
            var y = Math.round(yDe(g.grade[i][0])) + 0.5
            ctx.strokeStyle = cor(Tema.texto, 0.12)
            ctx.beginPath()
            ctx.moveTo(margemEsquerda, y)
            ctx.lineTo(w - margemDireita, y)
            ctx.stroke()
            ctx.fillStyle = cor(Tema.texto, 0.6)
            escrever(ctx, g.grade[i][1], margemEsquerda - 6, y, 1)
        }

        // Eixo X; as pontas já vêm alinhadas para dentro.
        ctx.fillStyle = cor(Tema.texto, 0.6)
        for (var r = 0; r < g.rotulos.length; ++r)
            escrever(ctx, g.rotulos[r][1], xDe(g.rotulos[r][0]), baseY + margemInferior / 2 + 2, g.rotulos[r][2])

        var pontos = []
        for (var p = 0; p < n; ++p) pontos.push([xDe(p), yDe(g.horas[p])])

        // Cada pausa cortada: uma linha tracejada no meio do vão, e a linha do gráfico não o atravessa, para ninguém
        // ler o vão como dias seguidos.
        ctx.strokeStyle = cor(Tema.texto, 0.35)
        ctx.lineWidth = 1
        ctx.setLineDash([4, 4])
        for (var q = 0; q < g.quebras.length; ++q) {
            var xq = Math.round((pontos[g.quebras[q]][0] + pontos[g.quebras[q] + 1][0]) / 2) + 0.5
            ctx.beginPath()
            ctx.moveTo(xq, margemSuperior)
            ctx.lineTo(xq, baseY)
            ctx.stroke()
        }
        ctx.setLineDash([])

        // A linha e a área sob ela, em trechos separados pelas quebras.
        var inicio = 0
        for (var t = 0; t <= g.quebras.length; ++t) {
            var fim = t < g.quebras.length ? g.quebras[t] + 1 : n
            if (fim - inicio >= 2) {
                ctx.beginPath()
                ctx.moveTo(pontos[inicio][0], baseY)
                for (var a = inicio; a < fim; ++a) ctx.lineTo(pontos[a][0], pontos[a][1])
                ctx.lineTo(pontos[fim - 1][0], baseY)
                ctx.closePath()
                ctx.fillStyle = cor(Tema.destaqueTexto, 0.15)
                ctx.fill()

                ctx.beginPath()
                ctx.moveTo(pontos[inicio][0], pontos[inicio][1])
                for (var b = inicio + 1; b < fim; ++b) ctx.lineTo(pontos[b][0], pontos[b][1])
                ctx.strokeStyle = cor(Tema.destaqueTexto, 1)
                ctx.lineWidth = 2
                ctx.lineJoin = "round"
                ctx.stroke()
            }
            inicio = fim
        }

        // Pontos só enquanto cabem: num período de anos eles viram uma faixa.
        if (n === 1 || larguraUtil / (ultima + 1) >= 8) {
            ctx.fillStyle = cor(Tema.destaqueTexto, 1)
            for (var d = 0; d < n; ++d) {
                ctx.beginPath()
                ctx.arc(pontos[d][0], pontos[d][1], 3, 0, 2 * Math.PI)
                ctx.fill()
            }
        }
    }

    Canvas {
        id: tela
        anchors.fill: parent
        onPaint: {
            raiz.desenhar(getContext("2d"))
            raiz.desenhos += 1
        }
        onWidthChanged: requestPaint()
        onHeightChanged: requestPaint()
        Connections {
            target: Tema
            function onEscuroChanged() { tela.requestPaint() }
            function onDestaqueTextoChanged() { tela.requestPaint() }
        }
    }

    MouseArea {
        id: area
        anchors.fill: parent
        hoverEnabled: true
        acceptedButtons: Qt.NoButton
        onPositionChanged: mouse => raiz.xDoMouse = mouse.x
        onExited: raiz.xDoMouse = -1
    }

    // A dica do app (500 ms, como a do GTK), junto do mouse.
    Dica {
        x: area.mouseX + 12
        y: area.mouseY + 16
        ativa: area.containsMouse
        texto: raiz.dicaDoMouse
    }
}
