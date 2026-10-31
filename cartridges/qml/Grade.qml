import QtQuick
import QtQuick.Controls.Basic

// A grade de capas da biblioteca: células de 200 de largura, 12 de espaçamento e 15 de margem,
// centralizada na janela.
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
    // A célula leva o espaçamento inteiro; a margem de 15 é a diferença para o que ela já tem.
    readonly property int colunas: {
        var cabem = Math.max(1, Math.floor((width - 2 * margem + espacamento) / larguraDaCelula))
        return colunasMaximas > 0 ? Math.min(cabem, colunasMaximas) : cabem
    }

    readonly property int larguraDaCelula: 200 + espacamento
    cellWidth: larguraDaCelula
    cellHeight: 300 + 50 + espacamento
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
    boundsBehavior: Flickable.StopAtBounds
    model: biblioteca
    ScrollBar.vertical: BarraDeRolagem {}
    keyNavigationEnabled: true
    currentIndex: 0

    Keys.onReturnPressed: { porTeclado = true; abrirDoAtual() }
    Keys.onEnterPressed: { porTeclado = true; abrirDoAtual() }
    Keys.onMenuPressed: { porTeclado = true; if (currentItem) currentItem.abrirMenu() }
    // Setas: só marcam o uso do teclado; o GridView é quem move o `currentIndex`.
    Keys.onLeftPressed: event => { porTeclado = true; event.accepted = false }
    Keys.onRightPressed: event => { porTeclado = true; event.accepted = false }
    Keys.onUpPressed: event => { porTeclado = true; event.accepted = false }
    Keys.onDownPressed: event => { porTeclado = true; event.accepted = false }
    HoverHandler { onPointChanged: grade.porTeclado = false }
    // Não é Keys.onPressed: a página já usa o da grade para abrir a busca ao digitar.
    Shortcut {
        sequence: "Shift+F10"
        enabled: grade.activeFocus
        onActivated: { grade.porTeclado = true; if (grade.currentItem) grade.currentItem.abrirMenu() }
    }

    function abrirDoAtual() {
        if (currentItem) grade.abrirDetalhes(currentItem.jogoId)
    }

    // O foco volta ao cartão do jogo (ao sair do Big Picture), ou ao primeiro se ele não está na página.
    function focarJogo(jogoId) {
        var i = biblioteca.indiceDe(jogoId)
        currentIndex = i >= 0 ? i : 0
        positionViewAtIndex(currentIndex, GridView.Contain)
        forceActiveFocus()
    }

    readonly property bool menuAberto: menuDoJogo.visible

    // O passo do controle: um cartão para o lado ou para cima/baixo, sem passar da borda.
    // Devolve se o cartão atual mudou; na borda, quem chamou faz o controle vibrar (ou, em ↑ na primeira linha, vai à barra).
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
        else if (dy > 0)
            // Embaixo de uma coluna sem cartão, a última linha para no último jogo.
            alvo = i + colunas < count ? i + colunas
                : (Math.floor(i / colunas) < Math.floor((count - 1) / colunas) ? count - 1 : i)
        if (alvo === i) return false
        currentIndex = alvo
        positionViewAtIndex(alvo, GridView.Contain)
        return true
    }

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
        width: grade.cellWidth
        height: grade.cellHeight

        function abrirMenu() { cartao.abrirMenu() }

        CartaoDoJogo {
            id: cartao
            anchors.centerIn: parent
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
                menuDoJogo.popup(ancora, ancora.width - menuDoJogo.width, ancora.height + 4)
            }
        }
    }
}
