import QtQuick
import QtQuick.Window

// Cover Flow do protótipo. Calibração copiada de cartridges/big_picture.py.
Window {
    id: janela
    title: "Big Picture (protótipo QML)"
    color: "black"

    readonly property var jogos: jogosDaBiblioteca
    readonly property int perspectiva: 900
    readonly property real anguloLateral: 65
    readonly property real espacoCentral: 1.15
    readonly property real espacoLateral: 0.45
    readonly property real profundidadeLateral: 220
    readonly property int capasDeCadaLado: 8
    readonly property real escalaNaAbertura: 1.6
    readonly property int jogosNaFila: 30

    property int indice: 0
    property real posicao: 0
    property real virada: 1
    property real opacidadeCapas: 1
    property real progressoAbertura: 0
    property bool ocupada: true  // começa na fila de entrada
    property bool naFila: true
    property real alturaCapa: height * 0.55
    property real larguraCapa: alturaCapa * 2 / 3

    Behavior on posicao {
        enabled: !janela.naFila
        NumberAnimation { duration: 350; easing.type: Easing.OutCubic }
    }

    function limitar(x) { return Math.max(0, Math.min(1, x)) }

    // (x, ângulo, profundidade) da capa `i`: a mistura, por `virada`, da fila e do normal.
    function arranjo(i) {
        const d = i - posicao
        const a = Math.min(Math.abs(d), 1)
        const lado = d < 0 ? -1 : 1
        const x = Math.abs(d) <= 1
            ? d * larguraCapa * espacoCentral
            : lado * (larguraCapa * espacoCentral + (Math.abs(d) - 1) * larguraCapa * espacoLateral)
        const angulo = -lado * a * anguloLateral
        const prof = -a * profundidadeLateral
        if (virada === 1)
            return [x, angulo, prof, a]
        const xFila = d * larguraCapa * espacoLateral * 1.6
        return [xFila + (x - xFila) * virada,
                -anguloLateral + (angulo + anguloLateral) * virada,
                -profundidadeLateral + (prof + profundidadeLateral) * virada, a]
    }

    function translacao(x, y, z) {
        return Qt.matrix4x4(1, 0, 0, x, 0, 1, 0, y, 0, 0, 1, z, 0, 0, 0, 1)
    }

    // Do espaço da capa (0,0 a largura,altura) ao da janela: o mesmo encadeamento
    // do Gsk.Transform do app. A projeção zera o z para nada ser recortado em profundidade.
    function transformacao(i) {
        const [x, angulo, prof, a] = arranjo(i)
        const escala = 1 + (escalaNaAbertura - 1) * progressoAbertura * (1 - a)
        const r = angulo * Math.PI / 180
        const c = Math.cos(r), s = Math.sin(r)
        const projecao = Qt.matrix4x4(1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, -1 / perspectiva, 1)
        const giro = Qt.matrix4x4(c, 0, s, 0, 0, 1, 0, 0, -s, 0, c, 0, 0, 0, 0, 1)
        const tamanho = Qt.matrix4x4(escala, 0, 0, 0, 0, escala, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)
        return translacao(width / 2, height * 0.40, 0)
            .times(projecao)
            .times(translacao(x, 0, prof))
            .times(giro)
            .times(tamanho)
            .times(translacao(-larguraCapa / 2, -alturaCapa / 2, 0))
    }

    function capaEm(px, py) {
        const visiveis = []
        for (let i = Math.max(0, Math.floor(posicao - capasDeCadaLado) + 1);
             i < Math.min(jogos.length, Math.ceil(posicao + capasDeCadaLado)); i++)
            visiveis.push(i)
        visiveis.sort((a, b) => Math.abs(a - posicao) - Math.abs(b - posicao))
        for (const i of visiveis) {
            const m = transformacao(i)
            const cantos = [[0, 0], [larguraCapa, 0], [larguraCapa, alturaCapa], [0, alturaCapa]]
                .map(([x, y]) => { const v = m.times(Qt.vector4d(x, y, 0, 1)); return [v.x / v.w, v.y / v.w] })
            // Dentro do quadrilátero convexo: o mesmo lado de todas as arestas.
            let dentro = true
            for (let k = 0; k < 4 && dentro; k++) {
                const [ax, ay] = cantos[k], [bx, by] = cantos[(k + 1) % 4]
                dentro = (bx - ax) * (py - ay) - (by - ay) * (px - ax) >= 0
            }
            if (dentro) return i
        }
        return -1
    }

    // --- navegação ---
    function irPara(novo) {
        if (ocupada || jogos.length === 0) return
        novo = Math.max(0, Math.min(novo, jogos.length - 1))
        if (novo === indice) return
        controle.tremer(novo - indice)
        indice = novo
        posicao = novo
    }
    function mover(delta) { irPara(indice + delta) }
    function abrir() {
        if (ocupada) return
        ocupada = true
        abertura.start()
    }

    Connections {
        target: controle
        function onMover(delta) { janela.mover(delta) }
        function onAbrir() { janela.abrir() }
        function onSair() { Qt.quit() }
    }

    // Abre e volta, só o visual: o protótipo não lança jogos.
    SequentialAnimation {
        id: abertura
        NumberAnimation { target: janela; property: "progressoAbertura"; to: 1; duration: 400 }
        PauseAnimation { duration: 600 }
        NumberAnimation { target: janela; property: "progressoAbertura"; to: 0; duration: 400 }
        ScriptAction { script: janela.ocupada = false }
    }

    // --- fila indiana de entrada (quadro_da_fila) ---
    property real tFila: 0
    onTFilaChanged: {
        const t = tFila
        const n = Math.min(jogosNaFila, Math.max(0, jogos.length - 1))
        const corrida = 1 - Math.pow(1 - limitar(t / 0.7), 3)
        const x = limitar((t - 0.65) / 0.35)
        const c1 = 1.4
        virada = x > 0 ? 1 + (c1 + 1) * Math.pow(x - 1, 3) + c1 * Math.pow(x - 1, 2) : 0
        posicao = n * (1 - corrida)
        opacidadeCapas = Math.min(1, 5 * t)
        rodape.opacity = limitar((t - 0.8) / 0.2)
    }
    NumberAnimation on tFila {
        from: 0; to: 1; duration: 1700
        onFinished: { janela.virada = 1; janela.naFila = false; janela.ocupada = false }
    }

    // --- desenho ---
    Image {
        anchors.fill: parent
        source: "image://fundo/" + Math.round(width * Screen.devicePixelRatio)
                + "x" + Math.round(height * Screen.devicePixelRatio)
        smooth: false
        cache: false
        asynchronous: true
    }

    // Máscara do reflexo, compartilhada: transparente até 55% da capa e
    // opaca na base (espelhada pelo reflexo, fica opaca junto da capa).
    Rectangle {
        id: mascaraDoReflexo
        visible: false
        width: janela.larguraCapa
        height: janela.alturaCapa
        layer.enabled: true
        gradient: Gradient {
            GradientStop { position: 0.55; color: "transparent" }
            GradientStop { position: 1.0; color: "white" }
        }
    }

    Item {
        id: palco
        anchors.fill: parent
        focus: true

        // 17 vagas fixas em anel, não uma por jogo: a vaga `index` mostra o jogo da
        // janela [base, base+16] com i ≡ index (mod 17). Ao andar uma capa, só uma vaga troca.
        readonly property int vagas: 2 * janela.capasDeCadaLado + 1
        readonly property int base: Math.floor(janela.posicao) - janela.capasDeCadaLado
        Repeater {
            model: palco.vagas
            delegate: Loader {
                id: vaga
                required property int index
                readonly property int i: palco.base + ((index - palco.base) % palco.vagas + palco.vagas) % palco.vagas
                active: i >= 0 && i < janela.jogos.length
                        && Math.abs(i - janela.posicao) < janela.capasDeCadaLado
                z: -Math.abs(i - janela.posicao)
                sourceComponent: Capa {
                    jogo: janela.jogos[vaga.i]
                    indice: vaga.i
                    mascara: mascaraDoReflexo
                    largura: janela.larguraCapa
                    altura: janela.alturaCapa
                    opacity: (1 - janela.progressoAbertura) * janela.opacidadeCapas
                    transform: Matrix4x4 { matrix: janela.transformacao(vaga.i) }
                }
            }
        }

        Keys.onPressed: (evento) => {
            const acoes = {
                [Qt.Key_Left]: () => janela.mover(-1),
                [Qt.Key_Right]: () => janela.mover(1),
                [Qt.Key_PageUp]: () => janela.mover(-10),
                [Qt.Key_PageDown]: () => janela.mover(10),
                [Qt.Key_Home]: () => janela.irPara(0),
                [Qt.Key_End]: () => janela.irPara(janela.jogos.length - 1),
                [Qt.Key_Return]: janela.abrir,
                [Qt.Key_Enter]: janela.abrir,
                [Qt.Key_Space]: janela.abrir,
                [Qt.Key_Escape]: Qt.quit,
                [Qt.Key_F]: () => diagnostico.visible = !diagnostico.visible,
            }
            const acao = acoes[evento.key]
            if (acao) { acao(); evento.accepted = true }
        }

        // O toque do Qt Quick acerta a capa errada sob a projeção, mesmo com a
        // matriz invertível (m33 = 1e-4, testado). Aqui projeta os cantos e testa
        // da capa mais próxima do centro à mais distante. O capa_em do app usa a
        // caixa alinhada (transform_bounds); o quadrilátero exato é mais justo nas bordas.
        TapHandler {
            onTapped: (ponto) => {
                const i = janela.capaEm(ponto.position.x, ponto.position.y)
                if (i === janela.indice) janela.abrir()
                else if (i >= 0) janela.irPara(i)
            }
        }

        WheelHandler {
            acceptedDevices: PointerDevice.Mouse
            onWheel: (evento) => janela.mover(evento.angleDelta.y < 0 ? 1 : -1)
        }

        DragHandler {
            target: null
            property int passos: 0
            onActiveChanged: passos = 0
            onTranslationChanged: {
                const alvo = -Math.trunc(translation.x / (janela.espacoLateral * janela.larguraCapa))
                if (alvo !== passos) { janela.mover(alvo - passos); passos = alvo }
            }
        }
    }

    Column {
        id: rodape
        visible: janela.jogos.length > 0
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 48
        spacing: 6
        opacity: 0
        readonly property var jogo: janela.jogos[janela.indice]
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            width: Math.min(implicitWidth, janela.width * 0.8)
            text: rodape.jogo ? rodape.jogo.nome : ""
            color: "white"
            font.pixelSize: 27
            font.weight: Font.ExtraBold
            wrapMode: Text.Wrap
            horizontalAlignment: Text.AlignHCenter
        }
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: rodape.jogo ? rodape.jogo.desenvolvedora : ""
            color: "white"
            opacity: 0.55
            font.pixelSize: 15
        }
    }

    Text {
        visible: janela.jogos.length === 0
        anchors.centerIn: parent
        text: "Nenhum jogo\nPressione B ou Esc para voltar à biblioteca."
        color: "white"
        horizontalAlignment: Text.AlignHCenter
    }

    Text {
        id: diagnostico
        visible: diagnosticoInicial
        x: 16; y: 16
        color: "#9f9"
        font.family: "Consolas"
        text: medidor.fps + " fps · " + janela.jogos.length + " jogos · "
              + Screen.name + " · escala " + Screen.devicePixelRatio
    }
}
