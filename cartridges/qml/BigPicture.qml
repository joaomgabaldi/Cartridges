import QtQuick
import QtQuick.Window

// O Cover Flow do Big Picture. Calibração copiada de cartridges/big_picture.py (valores da `main`);
// o estado vem do `bigPicture` (Python). A geometria é a do protótipo (D6).
Item {
    id: tela
    objectName: "bigPicture"

    signal abrir()
    signal sair()

    readonly property var jogos: bigPicture.jogos
    readonly property int indice: bigPicture.indice
    readonly property int perspectiva: 900
    readonly property real anguloLateral: 65
    readonly property real espacoCentral: 1.15
    readonly property real espacoLateral: 0.45
    readonly property real profundidadeLateral: 220
    readonly property int capasDeCadaLado: 8
    readonly property int duracaoDoPasso: 350
    readonly property real escalaNaAbertura: 1.6
    readonly property int duracaoDaAbertura: 400  // DURACAO_ABERTURA_MS
    readonly property real reflexoAlcance: 0.55
    readonly property real reflexoOpacidade: 0.35

    // As quatro que a entrada e a saída (Task 3) animam; em repouso valem 1/0/0/1.
    property real posicao: 0  // segue o índice (`onIndiceChanged`); a fila da entrada e da saída a escreve quadro a quadro
    property real virada: 1
    property real opacidadeCapas: 1
    property real progressoAbertura: 0
    property real opacidadeDoRodape: 1
    property bool animarPasso: true

    property real escala: Screen.devicePixelRatio  // pixels reais por pixel lógico
    property real alturaCapa: height * 0.55
    property real larguraCapa: alturaCapa * 2 / 3

    // Pôr a posição sem animar (lista refeita, valor inicial): só um passo do carrossel desliza.
    property bool saltando: false
    function irDireto(valor) {
        saltando = true
        posicao = valor
        saltando = false
    }
    Component.onCompleted: irDireto(indice)
    onIndiceChanged: posicao = indice

    // Lista refeita com o centro em outro índice: pula direto, como o `definir_jogos` da `main`.
    // Vem antes do `alterado`, então `indice` ainda é o antigo; mudança só de capa não passa por aqui.
    Connections {
        target: bigPicture
        function onJogosMudaram() {
            if (bigPicture.indice !== tela.indice) tela.irDireto(bigPicture.indice)
        }
    }
    Behavior on posicao {
        enabled: tela.animarPasso && !tela.saltando
        NumberAnimation { id: passo; duration: tela.duracaoDoPasso; easing.type: Easing.OutCubic }
    }

    // --- A fila indiana de entrada e saída (a conta é a `quadro_da_fila` de regras_do_big_picture.py) ---
    property real t: 0
    property real baseDaFila: 0
    property bool entrando: true
    property bool naFila: false

    function limitar(x) { return Math.max(0, Math.min(1, x)) }
    function quadroDaFila(t, n, base) {
        const corrida = 1 - Math.pow(1 - limitar(t / 0.7), 3)
        const x = limitar((t - 0.65) / 0.35)
        const c1 = 1.4
        const viradaDoQuadro = x > 0 ? 1 + (c1 + 1) * Math.pow(x - 1, 3) + c1 * Math.pow(x - 1, 2) : 0
        return [base + n * (1 - corrida), viradaDoQuadro, Math.min(1, 5 * t), limitar((t - 0.8) / 0.2)]
    }
    function aplicarQuadro(instante) {
        const [p, v, capas, rodape] = quadroDaFila(instante, Math.min(bigPicture.jogosNaFila, Math.max(0, jogos.length - 1)), baseDaFila)
        irDireto(p)
        virada = v
        opacidadeCapas = capas
        opacidadeDoRodape = rodape
    }
    // O estado de repouso: em cima da capa central, sem fila.
    function reporQuadro() {
        irDireto(indice)
        virada = 1
        opacidadeCapas = 1
        opacidadeDoRodape = 1
    }
    function iniciarFila(entrar) {
        passo.stop()  // o passo em curso para onde está: a saída parte da posição visual
        entrando = entrar
        baseDaFila = entrar ? 0 : posicao
        naFila = true
        aplicarQuadro(entrar ? 0 : 1)
        if (!bigPicture.animacoes) {
            terminarFila()
            return
        }
        fila.from = entrar ? 0 : 1
        fila.to = entrar ? 1 : 0
        fila.duration = entrar ? 1700 : 1100
        fila.restart()
    }
    function terminarFila() {
        naFila = false
        if (entrando) {
            reporQuadro()
            soltarPreparo()
        }
        bigPicture.filaTerminou()
    }
    // Na saída o quadro só volta com a camada já escondida, no escuro: antes o carrossel reapareceria.
    onVisibleChanged: if (!visible) {
        abertura.stop()
        progressoAbertura = 0
        reporQuadro()
        soltarPreparo()
    }
    NumberAnimation {
        id: fila
        target: tela
        property: "t"
        easing.type: Easing.Linear
        onFinished: tela.terminarFila()
    }
    onTChanged: if (naFila) aplicarQuadro(t)

    // --- Abrir o jogo: a central cresce e as outras esmaecem; no fim da ida o Python inicia o jogo ---
    function animarAbertura(de, para) {
        abertura.stop()
        progressoAbertura = de
        if (!bigPicture.animacoes) {
            progressoAbertura = para
            bigPicture.aberturaTerminou()
            return
        }
        abertura.from = de
        abertura.to = para
        abertura.start()
    }
    NumberAnimation {
        id: abertura
        target: tela
        property: "progressoAbertura"
        duration: tela.duracaoDaAbertura
        easing.type: Easing.OutCubic
        onFinished: bigPicture.aberturaTerminou()
    }
    Connections {
        target: bigPicture
        function onAberturaPedida(de, para) { tela.animarAbertura(de, para) }
        function onFocoPedido() { tela.forceActiveFocus() }
        function onFilaPedida(entrar) { tela.iniciarFila(entrar) }
        function onPrepararCapas() { tela.preparar() }
    }

    // --- P1: as capas da fila decodificadas antes de escurecer ---
    // No tamanho das vagas em tela cheia no monitor da janela (Review Focus 4): o cache do Qt Quick
    // só acerta com a mesma URL, `sourceSize` e `fillMode`. Vivem até o fim da fila de entrada.
    readonly property real alturaEmTelaCheia: Screen.height * 0.55
    property var preparo: []
    property bool preparoAvisado: true
    function preparar() {
        preparo = jogos.slice(0, bigPicture.jogosNaFila + capasDeCadaLado + 1).map(j => j.capa)
        preparoAvisado = false
        Qt.callLater(conferirPreparo)
    }
    function soltarPreparo() {
        preparo = []
        preparoAvisado = true
    }
    // Pronta, ilegível ou sem capa contam: só a que ainda carrega segura a troca.
    function conferirPreparo() {
        if (preparoAvisado || repetidorDoPreparo.count < preparo.length || preparoDaCentral.status === Image.Loading)
            return
        for (let k = 0; k < repetidorDoPreparo.count; k++) {
            const imagem = repetidorDoPreparo.itemAt(k)
            if (!imagem || imagem.status === Image.Loading) return
        }
        preparoAvisado = true
        bigPicture.capasProntas()
    }
    Item {
        visible: false  // fora da tela: só decodifica e prende o cache
        Repeater {
            id: repetidorDoPreparo
            model: tela.preparo
            delegate: Image {
                required property string modelData
                objectName: "preparoDaCapa"
                source: modelData
                asynchronous: true
                fillMode: Image.PreserveAspectCrop
                sourceSize.height: Math.round(tela.alturaEmTelaCheia * tela.escala)
                onStatusChanged: Qt.callLater(tela.conferirPreparo)
            }
        }
        // A central em alta do índice 0, como a `capaEmAlta` da CapaDoBigPicture.qml.
        Image {
            id: preparoDaCentral
            objectName: "preparoDaCentral"
            source: tela.preparo.length > 0 && tela.jogos.length > 0 && tela.jogos[0].capaAnimada === "" ? tela.preparo[0] : ""
            asynchronous: true
            fillMode: Image.PreserveAspectCrop
            sourceSize.height: Math.round(tela.alturaEmTelaCheia * tela.escalaNaAbertura * tela.escala)
            onStatusChanged: Qt.callLater(tela.conferirPreparo)
        }
    }

    focus: true

    // (x, ângulo, profundidade, afastamento) da capa `i`: a mistura, por `virada`, da fila e do normal.
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

    // Do espaço da capa (0,0 a largura,altura) ao da tela: o mesmo encadeamento do Gsk.Transform
    // do app. A projeção zera o z para nada ser recortado em profundidade.
    function transformacao(i) {
        const [x, angulo, prof, a] = arranjo(i)
        const fator = 1 + (escalaNaAbertura - 1) * progressoAbertura * (1 - a)
        const r = angulo * Math.PI / 180
        const c = Math.cos(r), s = Math.sin(r)
        const projecao = Qt.matrix4x4(1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, -1 / perspectiva, 1)
        const giro = Qt.matrix4x4(c, 0, s, 0, 0, 1, 0, 0, -s, 0, c, 0, 0, 0, 0, 1)
        const tamanho = Qt.matrix4x4(fator, 0, 0, 0, 0, fator, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)
        return translacao(width / 2, height * 0.40, 0)
            .times(projecao)
            .times(translacao(x, 0, prof))
            .times(giro)
            .times(tamanho)
            .times(translacao(-larguraCapa / 2, -alturaCapa / 2, 0))
    }

    // O toque do Qt Quick acerta a capa errada sob a projeção (ADR 0005, D44): projeta os cantos e
    // testa o quadrilátero, da capa mais próxima do centro à mais distante.
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
            let positivos = 0, negativos = 0
            for (let k = 0; k < 4; k++) {
                const [ax, ay] = cantos[k], [bx, by] = cantos[(k + 1) % 4]
                const lado = (bx - ax) * (py - ay) - (by - ay) * (px - ax)
                if (lado < 0) negativos++
                if (lado > 0) positivos++
            }
            if (positivos === 0 || negativos === 0) return i
        }
        return -1
    }

    Keys.onPressed: (evento) => {
        const acoes = {
            [Qt.Key_Left]: () => bigPicture.mover(-1),
            [Qt.Key_Right]: () => bigPicture.mover(1),
            [Qt.Key_PageUp]: () => bigPicture.mover(-10),
            [Qt.Key_PageDown]: () => bigPicture.mover(10),
            [Qt.Key_Home]: () => bigPicture.inicio(),
            [Qt.Key_End]: () => bigPicture.fim(),
            [Qt.Key_Return]: () => tela.abrir(),
            [Qt.Key_Enter]: () => tela.abrir(),
            [Qt.Key_Space]: () => tela.abrir(),
            [Qt.Key_Escape]: () => tela.sair(),
        }
        const acao = acoes[evento.key]
        if (!acao) return
        evento.accepted = true  // consome a tecla mesmo ocupada, como a `main`
        if (!bigPicture.ocupada) acao()
    }

    Rectangle { anchors.fill: parent; color: "black" }

    // Em pixels reais do monitor da janela (Review Focus 4).
    Image {
        objectName: "fundo"
        anchors.fill: parent
        // Só com o Big Picture à vista: escondido, o degradê não é gerado (nem na abertura do app).
        source: !bigPicture.visivel ? ""
                : "image://fundo/" + Math.max(1, Math.round(tela.width * tela.escala))
                  + "x" + Math.max(1, Math.round(tela.height * tela.escala))
        smooth: false
        cache: false
        asynchronous: false  // provedor Python na thread de imagens trava: ela espera o GIL segurando o mutex do cache
    }

    // Máscara do reflexo, compartilhada: transparente até 55% da capa e
    // opaca na base (espelhada pelo reflexo, fica opaca junto da capa).
    Rectangle {
        id: mascaraDoReflexo
        visible: false
        width: tela.larguraCapa
        height: tela.alturaCapa
        layer.enabled: true
        gradient: Gradient {
            GradientStop { position: tela.reflexoAlcance; color: "transparent" }
            GradientStop { position: 1.0; color: "white" }
        }
    }

    Item {
        id: palco
        anchors.fill: parent

        // 17 vagas fixas em anel, não uma por jogo: a vaga `index` mostra o jogo da
        // janela [base, base+16] com i ≡ index (mod 17). Ao andar uma capa, só uma vaga troca.
        readonly property int vagas: 2 * tela.capasDeCadaLado + 1
        readonly property int base: Math.floor(tela.posicao) - tela.capasDeCadaLado
        Repeater {
            model: palco.vagas
            delegate: Loader {
                id: vaga
                required property int index
                readonly property int i: palco.base + ((index - palco.base) % palco.vagas + palco.vagas) % palco.vagas
                // Só à vista: na entrada a lista nasce antes da tela cheia, e no tamanho da janela a vaga decodificaria à toa.
                active: bigPicture.visivel && i >= 0 && i < tela.jogos.length
                        && Math.abs(i - tela.posicao) < tela.capasDeCadaLado
                z: -Math.abs(i - tela.posicao)
                sourceComponent: CapaDoBigPicture {
                    jogo: tela.jogos[vaga.i]
                    indice: vaga.i
                    mascara: mascaraDoReflexo
                    largura: tela.larguraCapa
                    altura: tela.alturaCapa
                    escala: tela.escala
                    escalaDaCentral: tela.escalaNaAbertura
                    opacidadeDoReflexo: tela.reflexoOpacidade
                    // Só no fim do passo: segurando a tecla nenhuma capa de passagem carrega a cópia em alta.
                    central: vaga.i === tela.indice && Math.abs(tela.posicao - vaga.i) < 0.001
                    animar: bigPicture.animarCentral && bigPicture.visivel
                    opacity: (1 - tela.progressoAbertura) * tela.opacidadeCapas
                    transform: Matrix4x4 { matrix: tela.transformacao(vaga.i) }
                }
            }
        }

        TapHandler {
            enabled: !bigPicture.ocupada
            onTapped: (ponto) => {
                const i = tela.capaEm(ponto.position.x, ponto.position.y)
                if (i === tela.indice) tela.abrir()
                else if (i >= 0) bigPicture.irPara(i)
            }
        }

        WheelHandler {
            enabled: !bigPicture.ocupada
            acceptedDevices: PointerDevice.Mouse
            // Um passo por entalhe (120), como o DISCRETE da `main`; roda horizontal não move.
            property int acumulado: 0
            onEnabledChanged: acumulado = 0  // ocupada: o resto não vale para depois
            onWheel: (evento) => {
                if (evento.angleDelta.y === 0) return
                if (acumulado * evento.angleDelta.y < 0) acumulado = 0  // mudou de sentido
                acumulado += evento.angleDelta.y
                while (Math.abs(acumulado) >= 120) {
                    const lado = acumulado < 0 ? 1 : -1
                    bigPicture.mover(lado)
                    acumulado += lado * 120
                }
            }
        }

        DragHandler {
            enabled: !bigPicture.ocupada
            target: null
            property int passos: 0
            onActiveChanged: passos = 0
            onTranslationChanged: {
                const alvo = -Math.trunc(translation.x / (tela.espacoLateral * tela.larguraCapa))
                if (alvo !== passos) { bigPicture.mover(alvo - passos); passos = alvo }
            }
        }
    }

    Column {
        objectName: "rodape"
        visible: !bigPicture.vazia
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 48
        spacing: 6
        opacity: tela.opacidadeDoRodape
        Text {
            objectName: "nomeDoRodape"
            width: tela.width * 0.8
            text: bigPicture.nome
            textFormat: Text.PlainText
            color: "white"
            font { family: Tema.fonte; pixelSize: 27; weight: Font.ExtraBold }
            wrapMode: Text.Wrap
            horizontalAlignment: Text.AlignHCenter
        }
        Text {
            width: tela.width * 0.8
            text: bigPicture.desenvolvedora
            textFormat: Text.PlainText
            color: "white"
            opacity: 0.55
            font { family: Tema.fonte; pixelSize: 15 }
            horizontalAlignment: Text.AlignHCenter
        }
    }

    EstadoVazio {
        objectName: "estadoVazioDoBigPicture"
        visible: bigPicture.vazia
        anchors.fill: parent
        titulo: "Nenhum jogo"
        descricao: "Pressione B ou Esc para voltar à biblioteca."
        corDoTitulo: "white"
        corDaDescricao: "white"
    }
}
