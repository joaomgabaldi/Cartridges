import QtQuick
import QtQuick.Controls.Basic

// A grade de capas da biblioteca (o `AnimatedFlowBox` da `main`): cartões de 200x347, com 3 de respiro de cada lado
// (`flowboxchild`) e 12 de espaçamento, a 15 de margem, centralizada na janela.
GridView {
    id: grade

    // FiltroDaPagina ou ModeloDaBiblioteca
    property QtObject biblioteca
    // `library-rows`: 0 deixa as colunas acompanharem a largura da janela.
    property int colunasMaximas: 0
    // `cover-autoplay`: as capas animadas à vista tocam sem o mouse.
    property bool tocarSempre: false
    // A página da grade está por cima (a coberta pelos Jogos Zerados não anima).
    property bool ativa: true
    // Onde a rolagem parou: os cartões só ligam ou desligam a animação 200 ms depois dela,
    // como na `main`, para os que só cruzam a tela não abrirem a cópia.
    property real contentYParado: 0
    onContentYChanged: assentarRolagem.restart()
    Component.onCompleted: contentYParado = contentY
    Timer {
        id: assentarRolagem
        interval: 200
        onTriggered: grade.contentYParado = grade.contentY
    }

    // O jogo que o clique na capa, o Enter ou o A do controle abrem.
    signal abrirDetalhes(string jogoId)
    // O clique direito num cartão: na `main`, o diálogo Editar (tarefa 6 do plano 3).
    signal editar(string jogoId)
    // O foco do cartão (anel e botões) só aparece depois de uma tecla; o mouse o apaga.
    property bool porTeclado: false

    readonly property int espacamento: 12
    readonly property int margem: 15
    // O `flowboxchild` tem 3 de padding em volta do cartão (CSS 2950): o passo é 200 + 6 + 12 = 218 na horizontal e
    // 347 + 6 + 12 = 365 na vertical; o cartão fica centrado na célula, a 18 da borda (15 + 3).
    readonly property int respiro: 6
    // A célula leva o espaçamento inteiro; a margem de 15 é a diferença para o que ela já tem.
    readonly property int colunas: {
        var cabem = Math.max(1, Math.floor((width - 2 * margem + espacamento) / larguraDaCelula))
        return colunasMaximas > 0 ? Math.min(cabem, colunasMaximas) : cabem
    }

    readonly property int larguraDaCelula: 200 + respiro + espacamento
    cellWidth: larguraDaCelula
    cellHeight: 347 + respiro + espacamento
    // Poucos jogos ficam centralizados, como o FlowBox de antes.
    leftMargin: Math.max(0, (width - Math.min(colunas, Math.max(1, count)) * larguraDaCelula) / 2)
    rightMargin: leftMargin
    // O GridView só refaz as colunas quando a largura ou a célula mudam: com a biblioteca vazia na
    // abertura a margem é grande e a grade ficava em poucas colunas. Mexer na célula e devolver o
    // vínculo força o recálculo; as duas margens chamam, para a ordem em que mudam não importar.
    function refazerColunas() {
        cellWidth = larguraDaCelula + 1
        cellWidth = Qt.binding(() => larguraDaCelula)
    }
    // O Flickable não recoloca o conteúdo quando a margem muda sozinha.
    onLeftMarginChanged: { contentX = -leftMargin; refazerColunas() }
    onRightMarginChanged: refazerColunas()
    topMargin: margem - espacamento / 2
    bottomMargin: topMargin
    clip: true
    focus: true
    // Sem o salto elástico do toque; deixa arrastar além da ponta só para o brilho de `overshoot` (PaginaDaBiblioteca).
    boundsBehavior: Flickable.DragOverBounds
    model: biblioteca
    ScrollBar.vertical: BarraDeRolagem {}
    keyNavigationEnabled: true
    currentIndex: 0

    // A roda do mouse com mola (`spring_scroll.py`); o touchpad segue o do Flickable.
    RolagemPorMola { objectName: "rolagemPorMola"; alvo: grade; ativa: Tema.animacoes }

    // O foco é do botão da capa na `main`: Enter e Espaço abrem os detalhes. Sem tecla de menu ("No keyboard shortcuts
    // on purpose", `main.py:693`); o menu abre pelo botão "Mais opções" e pelo clique direito.
    Keys.onReturnPressed: { porTeclado = true; abrirDoAtual() }
    Keys.onEnterPressed: { porTeclado = true; abrirDoAtual() }
    Keys.onSpacePressed: { porTeclado = true; abrirDoAtual() }
    // Tab percorre os cartões um a um; nas pontas o foco sai da grade.
    Keys.onTabPressed: event => {
        porTeclado = true
        if (currentIndex < count - 1) { currentIndex++; positionViewAtIndex(currentIndex, GridView.Contain) }
        else event.accepted = false
    }
    Keys.onBacktabPressed: event => {
        porTeclado = true
        if (currentIndex > 0) { currentIndex--; positionViewAtIndex(currentIndex, GridView.Contain) }
        else event.accepted = false
    }
    // Setas: só marcam o uso do teclado; o GridView é quem move o `currentIndex`.
    Keys.onLeftPressed: event => { porTeclado = true; event.accepted = false }
    Keys.onRightPressed: event => { porTeclado = true; event.accepted = false }
    Keys.onUpPressed: event => { porTeclado = true; event.accepted = false }
    Keys.onDownPressed: event => { porTeclado = true; event.accepted = false }
    HoverHandler { onPointChanged: grade.porTeclado = false }

    // Entrar ou sair capa (importar, buscar, esconder) não anima: o salto é o de sempre (`animated_flow_box.py`).
    property bool contagemMudou: false
    onCountChanged: { contagemMudou = true; fimDaContagem.restart() }
    Timer { id: fimDaContagem; interval: 150; onTriggered: grade.contagemMudou = false }

    function abrirDoAtual() {
        if (currentItem) grade.abrirDetalhes(currentItem.jogoId)
    }

    // O foco volta ao cartão do jogo (ao sair do Big Picture), ou ao primeiro se ele não está na página.
    function focarJogo(jogoId) {
        var i = biblioteca.indiceDe(jogoId)
        currentIndex = i >= 0 ? i : 0
        positionViewAtIndex(currentIndex, GridView.Contain)
        // Saindo do Big Picture pelo controle, o cartão volta com a seleção à mostra (`set_focus_visible`).
        porTeclado = true
        forceActiveFocus()
    }

    readonly property bool menuAberto: menuDoJogo.visible
    function fecharMenu() { menuDoJogo.close() }
    // Rolada para além do topo: a linha de baixo da barra de título acende (`sombraDaBarra`).
    readonly property bool rolado: contentY - (originY - topMargin) > 0

    // O passo do controle: um cartão para o lado ou para cima/baixo, sem passar da borda.
    // Devolve se o cartão atual mudou; na borda, quem chamou decide (em ↑ na primeira linha, vai à barra).
    function moverSelecao(dx, dy) {
        porTeclado = true
        forceActiveFocus()
        if (count === 0) return false
        var i = currentIndex
        var alvo = i
        // ← e → seguem a ordem dos jogos: do fim de uma linha passam ao começo da outra.
        if (dx < 0) alvo = i > 0 ? i - 1 : i
        else if (dx > 0) alvo = i < count - 1 ? i + 1 : i
        else if (dy < 0) alvo = i - colunas >= 0 ? i - colunas : i
        // Embaixo de uma coluna sem cartão o `GtkFlowBox` não anda: o foco fica onde está.
        else if (dy > 0) alvo = i + colunas < count ? i + colunas : i
        if (alvo === i) return false
        currentIndex = alvo
        rolarAte(alvo)
        return true
    }

    // A rolagem do controle (`_scroll_to_focus`): 200 ms, OutCubic. Na primeira linha volta à margem de cima, na última vai
    // ao fim; nas outras só o bastante para o cartão caber. Uma animação em curso é interrompida e a nova parte de onde está.
    function rolarAte(indice) {
        var topo = originY + Math.floor(indice / colunas) * cellHeight
        var base = topo + cellHeight
        var minimo = originY - topMargin
        var maximo = Math.max(minimo, originY + contentHeight + bottomMargin - height)
        var alvo
        if (indice < colunas) alvo = minimo
        else if (base >= originY + contentHeight - 1) alvo = maximo
        else if (topo < contentY) alvo = topo
        else if (base > contentY + height) alvo = base - height
        else return
        alvo = Math.min(Math.max(alvo, minimo), maximo)
        rolagemDoControle.stop()
        if (Math.abs(alvo - contentY) < 1) return
        cancelFlick()
        if (!Tema.animacoes) { contentY = alvo; return }
        rolagemDoControle.from = contentY
        rolagemDoControle.to = alvo
        rolagemDoControle.start()
    }
    NumberAnimation { id: rolagemDoControle; objectName: "rolagemDoControle"; target: grade; property: "contentY"; duration: 200; easing.type: Easing.OutCubic }

    // Um menu para a grade toda; o cartão diz a que jogo ele se refere.
    MenuDoJogo {
        id: menuDoJogo
        objectName: "menuDoJogo"
        modelo: grade.biblioteca
        onEditar: id => grade.editar(id)
    }

    delegate: Item {
        required property int index
        required property string jogoId
        required property string nome
        required property string capa
        required property bool zerado
        required property bool carregando
        required property string capaAnimada
        required property bool temAtualizacao
        id: celula
        width: grade.cellWidth
        height: grade.cellHeight

        function abrirMenu() { cartao.abrirMenu() }

        // As capas deslizam até o lugar novo, com mola de amortecimento crítico (massa 1, rigidez 450, epsilon .002),
        // quando a grade refaz as linhas: mudou o número de colunas ou alguma capa mudou de linha. O `x` da célula
        // não inclui a margem esquerda, então recentrar a grade (que é seco) não passa por aqui.
        // shortcut: parte de onde a capa está desenhada, mas não herda a velocidade da mola em curso.
        property real xAnterior: NaN
        property real yAnterior: NaN
        property real baseX: 0
        property real baseY: 0
        // 1 - progresso da mola: (1 + tau) e^-tau, com tau de 0 a 8,3 em 387 ms (1% de erro como o epsilon da `main`).
        property real tau: 8.3
        readonly property real restante: tau >= 8.3 ? 0 : (1 + tau) * Math.exp(-tau)
        readonly property real desvioX: baseX * restante
        readonly property real desvioY: baseY * restante
        function reposicionar() {
            if (!isNaN(xAnterior) && Tema.animacoes && !grade.contagemMudou && (x !== xAnterior || y !== yAnterior)) {
                baseX = xAnterior - x + desvioX
                baseY = yAnterior - y + desvioY
                tau = 0
                deslize.restart()
            }
            xAnterior = x
            yAnterior = y
        }
        onXChanged: Qt.callLater(reposicionar)
        onYChanged: Qt.callLater(reposicionar)
        Component.onCompleted: Qt.callLater(reposicionar)
        NumberAnimation { id: deslize; target: celula; property: "tau"; from: 0; to: 8.3; duration: 387 }

        CartaoDoJogo {
            id: cartao
            anchors { centerIn: parent; horizontalCenterOffset: celula.desvioX; verticalCenterOffset: celula.desvioY }
            temAtualizacao: parent.temAtualizacao
            onPausou: CapasPausadas.registrar(cartao)
            Component.onDestruction: CapasPausadas.esquecer(cartao)
            modelo: grade.biblioteca
            jogoId: parent.jogoId
            nome: parent.nome
            capa: parent.capa
            zerado: parent.zerado
            carregando: parent.carregando
            capaAnimada: parent.capaAnimada
            // Só o que cruza a janela da grade toca; o GridView ainda guarda cartões além das bordas.
            naVista: grade.ativa && grade.visible
                && parent.y + parent.height > grade.contentYParado && parent.y < grade.contentYParado + grade.height
            tocarSempre: grade.tocarSempre
            focado: grade.activeFocus && grade.porTeclado && parent.GridView.isCurrentItem
            menuAberto: menuDoJogo.visible && menuDoJogo.jogoId === jogoId
            // O índice vai junto: ao voltar, o foco é do cartão de onde a página saiu.
            onAbrirDetalhes: id => { grade.currentIndex = index; grade.abrirDetalhes(id) }
            onEditar: id => grade.editar(id)
            onMenuPedido: (id, ancora) => {
                grade.currentIndex = index
                menuDoJogo.jogoId = id
                menuDoJogo.popup(ancora, ancora.width - menuDoJogo.width, ancora.height + 6)
            }
        }
    }
}
