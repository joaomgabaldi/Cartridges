import QtQuick
import QtQuick.Controls.Basic

// A grade de capas da biblioteca: cartões de 200x347 com 3 de respiro e 12 de espaçamento, centralizada na janela.
GridView {
    id: grade

    property QtObject biblioteca
    property int colunasMaximas: 0
    property bool tocarSempre: false
    property bool ativa: true
    // Os cartões só ligam ou desligam a animação 200 ms depois da rolagem parar, para os que só cruzam a tela não abrirem
    // a cópia.
    property real contentYParado: 0
    onContentYChanged: assentarRolagem.restart()
    Component.onCompleted: { contentYParado = contentY; _colunasVistas = width > 0 ? colunas : 0 }
    Timer {
        id: assentarRolagem
        interval: 200
        onTriggered: grade.contentYParado = grade.contentY
    }

    signal abrirDetalhes(string jogoId)
    signal editar(string jogoId)
    property bool porTeclado: false

    readonly property int espacamento: 12
    readonly property int margem: 15
    readonly property int respiro: 6
    readonly property int colunas: {
        var cabem = Math.max(1, Math.floor((width - 2 * margem + espacamento) / larguraDaCelula))
        return colunasMaximas > 0 ? Math.min(cabem, colunasMaximas) : cabem
    }

    readonly property int larguraDaCelula: 200 + respiro + espacamento
    cellWidth: larguraDaCelula
    cellHeight: 347 + respiro + espacamento
    leftMargin: Math.max(0, (width - colunas * larguraDaCelula) / 2)
    rightMargin: leftMargin
    // O GridView só refaz as colunas quando a largura ou a célula mudam: mexer na célula e devolver o vínculo força o
    // recálculo; as duas margens chamam.
    function refazerColunas() {
        cellWidth = larguraDaCelula + 1
        cellWidth = Qt.binding(() => larguraDaCelula)
    }
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

    RolagemPorMola { objectName: "rolagemPorMola"; alvo: grade; ativa: Tema.animacoes }

    Keys.onReturnPressed: { porTeclado = true; abrirDoAtual() }
    Keys.onEnterPressed: { porTeclado = true; abrirDoAtual() }
    Keys.onSpacePressed: { porTeclado = true; abrirDoAtual() }
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
    Keys.onLeftPressed: event => { porTeclado = true; event.accepted = false }
    Keys.onRightPressed: event => { porTeclado = true; event.accepted = false }
    Keys.onUpPressed: event => { porTeclado = true; event.accepted = false }
    Keys.onDownPressed: event => { porTeclado = true; event.accepted = false }
    // Só o ponteiro que anda apaga o anel: o Qt reenvia o hover quando a página volta com o mouse parado.
    property point _ultimoPonteiro
    property bool _registrarPonteiro: false
    function marcarTeclado() {
        porTeclado = true
        _registrarPonteiro = true
    }
    HoverHandler {
        onPointChanged: {
            const p = point.scenePosition
            const andou = p.x !== grade._ultimoPonteiro.x || p.y !== grade._ultimoPonteiro.y
            if (andou && !grade._registrarPonteiro) grade.porTeclado = false
            grade._registrarPonteiro = false
            grade._ultimoPonteiro = p
        }
    }

    // As capas que só passam a existir quando a grade refaz as colunas (as de baixo, ao maximizar) partem de onde
    // estariam com as colunas de antes, para todas deslizarem juntas.
    property int colunasAnteriores: 0
    property int _colunasVistas: 0
    property bool refazendo: false
    onColunasChanged: {
        if (_colunasVistas > 0 && count > 0) { colunasAnteriores = _colunasVistas; refazendo = true; fimDoRefazer.restart() }
        _colunasVistas = width > 0 ? colunas : 0
    }
    Timer { id: fimDoRefazer; interval: 150; onTriggered: grade.refazendo = false }

    property bool contagemMudou: false
    onCountChanged: { contagemMudou = true; fimDaContagem.restart() }
    Timer { id: fimDaContagem; interval: 150; onTriggered: grade.contagemMudou = false }

    // A busca e os filtros: as capas que saem esmaecem, as que entram surgem e as que ficam deslizam até o novo lugar.
    property bool filtrando: false
    Connections {
        target: grade.biblioteca
        ignoreUnknownSignals: true
        function onFiltrou() { grade.filtrando = true; fimDoFiltro.restart() }
    }
    Timer { id: fimDoFiltro; interval: 150; onTriggered: grade.filtrando = false }
    add: Transition {
        objectName: "entradaDaCapa"
        enabled: Tema.animacoes && grade.filtrando
        NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 200; easing.type: Easing.OutCubic }
        NumberAnimation { property: "scale"; from: 0.92; to: 1; duration: 200; easing.type: Easing.OutCubic }
    }
    remove: Transition {
        objectName: "saidaDaCapa"
        enabled: Tema.animacoes && grade.filtrando
        NumberAnimation { property: "opacity"; to: 0; duration: 150; easing.type: Easing.InCubic }
        NumberAnimation { property: "scale"; to: 0.92; duration: 150; easing.type: Easing.InCubic }
    }

    function abrirDoAtual() {
        if (currentItem) grade.abrirDetalhes(currentItem.jogoId)
    }

    function focarJogo(jogoId) {
        var i = biblioteca.indiceDe(jogoId)
        currentIndex = i >= 0 ? i : 0
        positionViewAtIndex(currentIndex, GridView.Contain)
        porTeclado = true
        forceActiveFocus()
    }

    readonly property bool menuAberto: menuDoJogo.visible
    function fecharMenu() { menuDoJogo.close() }
    readonly property bool rolado: contentY - (originY - topMargin) > 0

    function moverSelecao(dx, dy) {
        porTeclado = true
        forceActiveFocus()
        if (count === 0) return false
        var i = currentIndex
        var alvo = i
        if (dx < 0) alvo = i > 0 ? i - 1 : i
        else if (dx > 0) alvo = i < count - 1 ? i + 1 : i
        else if (dy < 0) alvo = i - colunas >= 0 ? i - colunas : i
        else if (dy > 0) alvo = i + colunas < count ? i + colunas : i
        if (alvo === i) return false
        currentIndex = alvo
        rolarAte(alvo)
        return true
    }

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

    // A máscara dos cantos das capas, uma para todos os cartões (cada um criaria a sua, uma camada fora da tela a mais).
    Item {
        id: mascaraDosCartoes
        width: 200
        height: 300
        visible: false
        layer.enabled: true
        Rectangle { width: parent.width; height: parent.height + 12; radius: 12 }
    }

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

        // Mola de amortecimento crítico (massa 1, rigidez 450) quando a grade refaz as linhas; recentrar a grade (que é
        // seco) não passa por aqui.
        // shortcut: parte de onde a capa está desenhada, mas não herda a velocidade da mola em curso.
        property real xAnterior: NaN
        property real yAnterior: NaN
        property real baseX: 0
        property real baseY: 0
        property real tau: 8.3
        readonly property real restante: tau >= 8.3 ? 0 : (1 + tau) * Math.exp(-tau)
        readonly property real desvioX: baseX * restante
        readonly property real desvioY: baseY * restante
        function reposicionar() {
            if (!grade) return
            if (isNaN(xAnterior) && grade.refazendo) {
                xAnterior = x + (index % grade.colunasAnteriores - index % grade.colunas) * grade.cellWidth
                yAnterior = y + (Math.floor(index / grade.colunasAnteriores) - Math.floor(index / grade.colunas)) * grade.cellHeight
            }
            if (!isNaN(xAnterior) && Tema.animacoes && (!grade.contagemMudou || grade.filtrando) && (x !== xAnterior || y !== yAnterior)) {
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
            mascaraCompartilhada: mascaraDosCartoes
            onPausou: CapasPausadas.registrar(cartao)
            Component.onDestruction: CapasPausadas.esquecer(cartao)
            modelo: grade.biblioteca
            jogoId: parent.jogoId
            nome: parent.nome
            capa: parent.capa
            zerado: parent.zerado
            carregando: parent.carregando
            capaAnimada: parent.capaAnimada
            naVista: grade.ativa && grade.visible
                && parent.y + parent.height > grade.contentYParado && parent.y < grade.contentYParado + grade.height
            tocarSempre: grade.tocarSempre
            focado: grade.activeFocus && grade.porTeclado && parent.GridView.isCurrentItem
            menuAberto: menuDoJogo.visible && menuDoJogo.jogoId === jogoId
            onAbrirDetalhes: id => { grade.porTeclado = false; grade.currentIndex = index; grade.abrirDetalhes(id) }
            onEditar: id => grade.editar(id)
            onMenuPedido: (id, ancora) => {
                grade.currentIndex = index
                menuDoJogo.jogoId = id
                menuDoJogo.popup(ancora, ancora.width - menuDoJogo.width, ancora.height + 6)
            }
        }
    }
}
