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

    // O jogo que o clique na capa, o clique direito ou o Enter abrem; o receptor é do plano 3.
    signal abrirDetalhes(string jogoId)
    // O clique direito num cartão: na `main`, o diálogo Editar (plano 3).
    signal editar(string jogoId)
    // O foco do cartão (anel e botões) só aparece depois de uma tecla; o mouse o apaga.
    property bool porTeclado: false

    readonly property int espacamento: 12
    readonly property int margem: 15
    // A célula leva o espaçamento inteiro; a margem de 15 é a diferença para o que ela já tem.
    readonly property int colunas: {
        var cabem = Math.max(1, Math.floor((width - 2 * margem + espacamento) / cellWidth))
        return colunasMaximas > 0 ? Math.min(cabem, colunasMaximas) : cabem
    }

    cellWidth: 200 + espacamento
    cellHeight: 300 + 50 + espacamento
    // Poucos jogos ficam centralizados, como o FlowBox de antes.
    leftMargin: Math.max(0, (width - Math.min(colunas, Math.max(1, count)) * cellWidth) / 2)
    rightMargin: leftMargin
    // O Flickable não recoloca o conteúdo quando a margem muda sozinha.
    onLeftMarginChanged: contentX = -leftMargin
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

    // Um menu para a grade toda; o cartão diz a que jogo ele se refere.
    MenuDoJogo {
        id: menuDoJogo
        objectName: "menuDoJogo"
        modelo: grade.biblioteca
    }

    delegate: Item {
        required property int index
        required property string jogoId
        required property string nome
        required property string capa
        required property bool zerado
        required property bool carregando
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
            focado: grade.activeFocus && grade.porTeclado && parent.GridView.isCurrentItem
            menuAberto: menuDoJogo.visible && menuDoJogo.jogoId === jogoId
            onAbrirDetalhes: id => grade.abrirDetalhes(id)
            onEditar: id => grade.editar(id)
            onMenuPedido: (id, ancora) => {
                grade.currentIndex = index
                menuDoJogo.jogoId = id
                menuDoJogo.popup(ancora, ancora.width - menuDoJogo.width, ancora.height + 4)
            }
        }
    }
}
