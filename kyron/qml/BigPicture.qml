import QtQuick
import QtQuick.Window

// O Cover Flow do Big Picture; o estado vem do `bigPicture` (Python).
Item {
    id: tela
    objectName: "bigPicture"

    readonly property var jogos: bigPicture.jogos
    readonly property int indice: bigPicture.indice
    readonly property int perspectiva: 900
    readonly property real anguloLateral: 65
    readonly property real espacoCentral: 1.15
    readonly property real espacoLateral: 0.45
    readonly property real profundidadeLateral: 220
    readonly property int capasDeCadaLado: 8
    readonly property int duracaoDoPasso: 350
    readonly property real reflexoAlcance: 0.72
    readonly property real reflexoOpacidade: 0.22

    property real posicao: 0
    property real virada: 1
    property real opacidadeCapas: 1
    property real opacidadeDosTextos: 1
    property bool animarPasso: true
    property bool sessaoEmAndamento: false

    property real escala: Screen.devicePixelRatio
    property real alturaCapa: height * 0.60
    property real larguraCapa: alturaCapa * 2 / 3
    readonly property real centroDasCapas: height * 0.52
    readonly property real espacoNoAlto: centroDasCapas - alturaCapa / 2
    readonly property real alturaDoLogoNaColuna: height * 0.10
    readonly property real alturaDoLogoDecodificado: Math.max(110, espacoNoAlto * 0.6, alturaDoLogoNaColuna) * escala
    // Só a capa selecionada fica inteira: as outras recuam com a distância.
    function escurecimento(i) {
        const distancia = Math.abs(i - posicao)
        return Math.min(0.7, Math.min(distancia, 1) * 0.4 + Math.max(distancia - 1, 0) * 0.08)
    }

    property bool saltando: false
    function irDireto(valor) {
        saltando = true
        posicao = valor
        saltando = false
    }
    Component.onCompleted: irDireto(indice)
    onIndiceChanged: { posicao = indice; assentarCentral() }
    onPosicaoChanged: assentarCentral()
    property int centralExibida: 0
    function assentarCentral() { if (Math.abs(posicao - indice) < 0.001) centralExibida = indice }

    // Lista refeita com o centro em outro índice: pula direto. Vem antes do `alterado`, então `indice` ainda é o antigo.
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

    // A conta da fila é a `quadro_da_fila` de regras_do_big_picture.py.
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
        opacidadeDosTextos = rodape
    }
    function reporQuadro() {
        irDireto(indice)
        virada = 1
        opacidadeCapas = 1
        opacidadeDosTextos = 1
    }
    function iniciarFila(entrar) {
        passo.stop()
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

    Connections {
        target: bigPicture
        function onEtapaPedida(de, para) { tela.mudarDeEtapa(de, para) }
        function onFocoPedido() { tela.forceActiveFocus() }
        function onFilaPedida(entrar) { tela.iniciarFila(entrar) }
        function onPrepararCapas() { tela.preparar() }
    }

    // O único lugar da troca de etapa: as animações das etapas entram aqui. Um pedido novo cancela o anterior, e só o
    // último chama `etapaTerminou`. A ida aos detalhes e a volta são uma animação só (`progressoDetalhe`); o que não
    // é animado ainda termina num ciclo de espera (a página fica ocupada nele) ou na hora, sem as animações do Windows.
    // shortcut: um pedido que corta a animação no meio recomeça dela inteira, sem emendar; só a exclusão do jogo dos
    // detalhes faz isso, e o carrossel já vem de capas que saíram da tela. Emendar se outro caminho passar a cortar a animação.
    function mudarDeEtapa(de, para) {
        fimDaEtapa.stop()
        animacaoDosDetalhes.stop()
        animacaoDaSessao.stop()
        terminaPelaSessao = false
        const alvoDetalhe = para === "carrossel" ? 0 : 1
        const alvoSessao = para === "sessao" ? 1 : 0
        if (alvoDetalhe === progressoDetalhe && alvoSessao === progressoSessao) {
            if (bigPicture.animacoes) fimDaEtapa.start()
            else bigPicture.etapaTerminou()
            return
        }
        voltandoDosDetalhes = alvoDetalhe === 0 && progressoDetalhe !== 0
        if (!bigPicture.animacoes) {
            progressoDetalhe = alvoDetalhe
            progressoSessao = alvoSessao
            voltandoDosDetalhes = false
            bigPicture.etapaTerminou()
            return
        }
        if (alvoSessao !== progressoSessao) {
            animacaoDaSessao.to = alvoSessao
            animacaoDaSessao.start()
        }
        if (alvoDetalhe !== progressoDetalhe) {
            animacaoDosDetalhes.from = alvoDetalhe === 0 ? 1 : 0
            animacaoDosDetalhes.to = alvoDetalhe
            animacaoDosDetalhes.start()
        } else {
            terminaPelaSessao = true  // só a central anda: a sessão é quem termina a etapa
        }
    }
    // A central saindo pela esquerda (ida à sessão) e voltando: 0 → 1 → 0, à parte do tempo dos detalhes.
    property real progressoSessao: 0
    property bool terminaPelaSessao: false
    NumberAnimation {
        id: animacaoDaSessao
        target: tela
        property: "progressoSessao"
        duration: tela.duracaoDaVizinha
        easing.type: Easing.OutCubic
        onFinished: if (tela.terminaPelaSessao) {
            tela.terminaPelaSessao = false
            bigPicture.etapaTerminou()
        }
    }
    // O tempo da animação dos detalhes, de 0 a 1 (na volta, de 1 a 0 contado ao contrário no `arranjo`).
    property real progressoDetalhe: 0
    property bool voltandoDosDetalhes: false
    readonly property int duracaoDaCentral: 900
    readonly property int duracaoDaVizinha: 750
    readonly property int atrasoDaVizinha: 45
    readonly property int duracaoDosDetalhes: duracaoDaVizinha + atrasoDaVizinha * (capasDeCadaLado - 1)
    NumberAnimation {
        id: animacaoDosDetalhes
        target: tela
        property: "progressoDetalhe"
        duration: tela.duracaoDosDetalhes
        easing.type: Easing.Linear
        onFinished: {
            tela.voltandoDosDetalhes = false
            bigPicture.etapaTerminou()
        }
    }
    Timer { id: fimDaEtapa; interval: 0; onTriggered: bigPicture.etapaTerminou() }

    // Capas da fila decodificadas antes de escurecer, no tamanho das vagas: o cache do Qt Quick só acerta com a mesma
    // URL, `sourceSize` e `fillMode`.
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
        visible: false
        Repeater {
            id: repetidorDoPreparo
            model: tela.preparo
            delegate: Image {
                required property string modelData
                objectName: "preparoDaCapa"
                source: modelData
                asynchronous: true
                fillMode: Image.Stretch
                sourceSize.height: Math.round(300 * tela.escala)
                onStatusChanged: Qt.callLater(tela.conferirPreparo)
            }
        }
        Image {
            id: preparoDaCentral
            objectName: "preparoDaCentral"
            source: tela.preparo.length > 0 && tela.jogos.length > 0 && tela.jogos[0].capaAnimada === "" ? tela.preparo[0] : ""
            asynchronous: true
            fillMode: Image.Stretch
            sourceSize.height: Math.round(900 * tela.escala)
            onStatusChanged: Qt.callLater(tela.conferirPreparo)
        }
    }

    focus: true

    function arranjo(i) {
        const d = i - posicao
        const a = Math.min(Math.abs(d), 1)
        const lado = d < 0 ? -1 : 1
        const x = Math.abs(d) <= 1
            ? d * larguraCapa * espacoCentral
            : lado * (larguraCapa * espacoCentral + (Math.abs(d) - 1) * larguraCapa * espacoLateral)
        const angulo = -lado * a * anguloLateral
        const prof = -a * profundidadeLateral
        let quadro
        if (virada === 1) {
            quadro = [x, angulo, prof, a, 1]
        } else {
            const xFila = d * larguraCapa * espacoLateral * 1.6
            quadro = [xFila + (x - xFila) * virada,
                      -anguloLateral + (angulo + anguloLateral) * virada,
                      -profundidadeLateral + (prof + profundidadeLateral) * virada, a, 1]
        }
        const nosDetalhes = progressoDetalhe > 0 ? rumoAosDetalhes(i, quadro) : quadro
        return progressoSessao > 0 && i === indice ? centralRumoAEsquerda(nosDetalhes) : nosDetalhes
    }

    // Da posição do carrossel à dos detalhes (e de volta): as vizinhas saem para o lado, a central vai à esquerda e
    // cresce. `v` é o quanto da viagem já foi feito; a central passa de 1 (balanço) e depois assenta.
    function rumoAosDetalhes(i, quadro) {
        const distancia = Math.abs(i - indice)
        const tempo = (voltandoDosDetalhes ? 1 - progressoDetalhe : progressoDetalhe) * duracaoDosDetalhes
        let v
        if (distancia === 0) {
            const f = limitar(tempo / duracaoDaCentral) - 1
            v = 1 + 2.35 * f * f * f + 1.35 * f * f  // OutBack, overshoot 1,35
        } else {
            const f = 1 - limitar((tempo - atrasoDaVizinha * (distancia - 1)) / duracaoDaVizinha)
            v = 1 - f * f * f  // OutCubic
        }
        if (voltandoDosDetalhes) v = 1 - v
        const [x, angulo, prof, a] = quadro
        if (distancia === 0)
            return [x + (-0.28 * width - x) * v, angulo * (1 - v), prof * (1 - v), a, 1 + (19 / 15 - 1) * v]
        const lado = i < indice ? -1 : 1
        const alvoX = lado * Math.max(Math.abs(x), width * 0.75 + larguraCapa)
        return [x + (alvoX - x) * v, angulo + (-lado * 75 - angulo) * v, prof, a, 1]
    }

    // A central sai toda pela esquerda, girando até 25°; a margem cobre o giro e a perspectiva.
    function centralRumoAEsquerda(quadro) {
        const [x, angulo, prof, a, tamanho] = quadro
        const alvoX = -(width / 2 + larguraCapa * tamanho * 0.75 + 0.05 * width)
        return [x + (alvoX - x) * progressoSessao, angulo + 25 * progressoSessao, prof, a, tamanho]
    }

    function translacao(x, y, z) {
        return Qt.matrix4x4(1, 0, 0, x, 0, 1, 0, y, 0, 0, 1, z, 0, 0, 0, 1)
    }

    function transformacao(i) {
        const [x, angulo, prof, a, tamanho] = arranjo(i)
        const r = angulo * Math.PI / 180
        const c = Math.cos(r), s = Math.sin(r)
        // A projeção zera o z para nada ser recortado em profundidade.
        const projecao = Qt.matrix4x4(1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, -1 / perspectiva, 1)
        const giro = Qt.matrix4x4(c, 0, s, 0, 0, 1, 0, 0, -s, 0, c, 0, 0, 0, 0, 1)
        return translacao(width / 2, centroDasCapas, 0)
            .times(projecao)
            .times(translacao(x, 0, prof))
            .times(giro)
            .times(Qt.matrix4x4(tamanho, 0, 0, 0, 0, tamanho, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1))
            .times(translacao(-larguraCapa / 2, -alturaCapa / 2, 0))
    }

    // O toque do Qt Quick acerta a capa errada sob a projeção: projeta os cantos e testa a caixa que os contém, da capa
    // mais próxima do centro à mais distante.
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
            const xs = cantos.map(c => c[0]), ys = cantos.map(c => c[1])
            if (px >= Math.min(...xs) && px <= Math.max(...xs) && py >= Math.min(...ys) && py <= Math.max(...ys)) return i
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
            [Qt.Key_Return]: () => bigPicture.ativar(),
            [Qt.Key_Enter]: () => bigPicture.ativar(),
            [Qt.Key_Space]: () => bigPicture.ativar(),
            [Qt.Key_Escape]: () => bigPicture.voltar(),
        }
        const acao = acoes[evento.key]
        if (!acao) return
        evento.accepted = true
        if (!bigPicture.ocupada) acao()
    }

    Rectangle { anchors.fill: parent; color: "black" }

    Image {
        objectName: "fundo"
        anchors.fill: parent
        source: !bigPicture.visivel ? ""
                : "image://fundo/" + Math.max(1, Math.round(tela.width * tela.escala))
                  + "x" + Math.max(1, Math.round(tela.height * tela.escala))
        smooth: false
        cache: false
        asynchronous: false  // provedor Python na thread de imagens trava: ela espera o GIL segurando o mutex do cache
    }

    FundoDoBigPicture {
        id: fundoDoBigPicture
        objectName: "fundoDoBigPicture"
        anchors.fill: parent
        fonte: bigPicture.visivel ? detalhes.fundoVivo : ""
        animar: bigPicture.animacoes
    }

    // A cor do jogo fica no alto; embaixo o fundo escurece e dá chão às capas.
    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            GradientStop { position: 0.45; color: "transparent" }
            GradientStop { position: 1.0; color: Qt.rgba(0, 0, 0, 0.7) }
        }
    }
    // Atrás do texto da tela do jogo; o lado da capa continua com a cor.
    Rectangle {
        objectName: "veuDosDetalhes"
        anchors.fill: parent
        opacity: tela.progressoDetalhe * (1 - tela.progressoSessao)
        visible: opacity > 0
        gradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop { position: 0.30; color: "transparent" }
            GradientStop { position: 0.55; color: Qt.rgba(0, 0, 0, 0.6) }
        }
    }

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

        // 17 vagas fixas em anel: a vaga `index` mostra o jogo da janela [base, base+16] com i ≡ index (mod 17); ao andar
        // uma capa, só uma vaga troca.
        readonly property int vagas: 2 * tela.capasDeCadaLado + 1
        readonly property int base: Math.floor(tela.posicao) - tela.capasDeCadaLado
        Repeater {
            model: palco.vagas
            delegate: Loader {
                id: vaga
                required property int index
                readonly property int i: palco.base + ((index - palco.base) % palco.vagas + palco.vagas) % palco.vagas
                active: bigPicture.visivel && i >= 0 && i < tela.jogos.length
                        && Math.abs(i - tela.posicao) < tela.capasDeCadaLado
                z: -Math.abs(i - tela.posicao)
                sourceComponent: CapaDoBigPicture {
                    jogo: tela.jogos[vaga.i]
                    indice: vaga.i
                    mascara: mascaraDoReflexo
                    placeholder: bigPicture.placeholder
                    largura: tela.larguraCapa
                    altura: tela.alturaCapa
                    escala: tela.escala
                    opacidadeDoReflexo: tela.reflexoOpacidade
                    escurecer: tela.escurecimento(vaga.i)
                    // Só no fim do passo: segurando a tecla, nenhuma capa de passagem carrega a cópia em alta.
                    central: vaga.i === tela.centralExibida
                    animar: bigPicture.animarCentral && bigPicture.visivel && !tela.sessaoEmAndamento
                    opacity: tela.opacidadeCapas
                    transform: Matrix4x4 { matrix: tela.transformacao(vaga.i) }
                }
            }
        }

        TapHandler {
            enabled: bigPicture.etapa === "carrossel" && !bigPicture.ocupada
            onTapped: (ponto) => {
                const i = tela.capaEm(ponto.position.x, ponto.position.y)
                if (i === tela.indice) bigPicture.ativar()
                else if (i >= 0) bigPicture.irPara(i)
            }
        }

        WheelHandler {
            enabled: bigPicture.etapa === "carrossel" && !bigPicture.ocupada
            acceptedDevices: PointerDevice.Mouse
            property int acumulado: 0
            onEnabledChanged: acumulado = 0
            onWheel: (evento) => {
                if (evento.angleDelta.y === 0) return
                if (acumulado * evento.angleDelta.y < 0) acumulado = 0
                acumulado += evento.angleDelta.y
                while (Math.abs(acumulado) >= 120) {
                    const lado = acumulado < 0 ? 1 : -1
                    bigPicture.mover(lado)
                    acumulado += lado * 120
                }
            }
        }

        DragHandler {
            enabled: bigPicture.etapa === "carrossel" && !bigPicture.ocupada
            target: null
            property int passos: 0
            onActiveChanged: passos = 0
            onTranslationChanged: {
                const alvo = -Math.trunc(translation.x / (tela.espacoLateral * tela.larguraCapa))
                if (alvo !== passos) { bigPicture.mover(alvo - passos); passos = alvo }
            }
        }
    }

    // Duas vagas em anel, como as capas: num passo, o logo que sai e o que chega ficam cada um na sua vaga, sem recarregar.
    // Cada um segue a capa do seu jogo e o fade só acontece no meio do caminho (até 70% da distância entre duas capas).
    Repeater {
        model: 2
        delegate: LogoDoBigPicture {
            required property int index
            readonly property int base: Math.floor(tela.posicao)
            readonly property int i: (base % 2 + 2) % 2 === index ? base : base + 1
            readonly property real d: i - tela.posicao
            readonly property bool perto: tela.opacidadeDosTextos > 0 && Math.abs(d) < 1
            visible: !bigPicture.vazia
            emCentro: i === tela.indice
            jogo: perto && i >= 0 && i < tela.jogos.length ? tela.jogos[i] : null
            deslocamento: d * tela.larguraCapa * tela.espacoCentral
            opacity: tela.opacidadeDosTextos * Math.max(0, 1 - Math.abs(d) / 0.7)
            posicao: bigPicture.etapa === "detalhes" ? "coluna" : bigPicture.etapa === "sessao" ? "relogio" : "alto"
            animar: bigPicture.animacoes
            espacoNoAlto: tela.espacoNoAlto
            alturaDecodificada: tela.alturaDoLogoDecodificado
            alturaNaColuna: tela.alturaDoLogoNaColuna
        }
    }

    // Os logos das capas vizinhas já decodificados: o do próximo passo chega junto com a capa.
    Item {
        visible: false
        Repeater {
            model: 2
            delegate: Image {
                required property int index
                readonly property int i: tela.indice + (index === 0 ? -1 : 1)
                readonly property bool existe: i >= 0 && i < tela.jogos.length
                objectName: "preparoDoLogo"
                source: existe ? bigPicture.logoDe(tela.jogos[i].jogoId) : ""
                asynchronous: true
                fillMode: Image.PreserveAspectFit  // o cache do Qt Quick só acerta com a mesma URL, `sourceSize` e `fillMode`
                sourceSize.height: tela.alturaDoLogoDecodificado
            }
        }
    }

    DetalhesDoBigPicture {
        x: tela.width * 0.42
        // Da altura do logo até o pé da capa selecionada, para o texto e a capa formarem um bloco só.
        y: tela.height * 0.14 + tela.alturaDoLogoNaColuna + tela.height * 0.03
        alturaDaTela: tela.height
        width: tela.width * 0.33  // termina em 3/4 da tela: linhas longas demais cansam a leitura
        height: tela.height * 0.90 - y
        mostrar: bigPicture.etapa === "detalhes"
        animar: bigPicture.animacoes
    }

    SessaoDoBigPicture {
        anchors.fill: parent
        mostrar: bigPicture.etapa === "sessao"
        animar: bigPicture.animacoes
    }

    // A ação que tem botão com glifo na tela não se repete em outro lugar.
    Row {
        id: dicasDoBigPicture
        objectName: "dicasDoBigPicture"
        readonly property bool soVoltar: bigPicture.etapa === "detalhes"
        readonly property var textos: bigPicture.etapa === "sessao" ? [] : soVoltar ? ["Voltar"] : ["Selecionar", "Voltar"]
        readonly property var letras: soVoltar ? ["B"] : ["A", "B"]
        visible: (bigPicture.etapa === "carrossel" || soVoltar) && !bigPicture.vazia
        opacity: tela.opacidadeDosTextos
        anchors { right: parent.right; bottom: parent.bottom; rightMargin: 40; bottomMargin: 32 }
        spacing: 28
        Repeater {
            model: dicasDoBigPicture.textos
            delegate: Row {
                required property int index
                required property string modelData
                spacing: 10
                GlifoDoBotao { letra: dicasDoBigPicture.letras[parent.index] ?? ""; anchors.verticalCenter: parent.verticalCenter }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: parent.modelData
                    textFormat: Text.PlainText
                    color: "white"
                    opacity: 0.8
                    font { family: Tema.fonte; pixelSize: Tema.corpo }
                }
            }
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
