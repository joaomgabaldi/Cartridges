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

    readonly property int espacamento: 12
    readonly property int margem: 15
    // A célula leva o espaçamento inteiro; a margem de 15 é a diferença para o que ela já tem.
    readonly property int colunas: {
        var cabem = Math.max(1, Math.floor((width - 2 * margem + espacamento) / cellWidth))
        return colunasMaximas > 0 ? Math.min(cabem, colunasMaximas) : cabem
    }

    cellWidth: 200 + espacamento
    cellHeight: 300 + 40 + espacamento
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

    delegate: Item {
        required property string jogoId
        required property string nome
        required property string capa
        required property bool zerado
        width: grade.cellWidth
        height: grade.cellHeight

        CartaoDoJogo {
            anchors.centerIn: parent
            modelo: grade.biblioteca
            jogoId: parent.jogoId
            nome: parent.nome
            capa: parent.capa
            zerado: parent.zerado
        }
    }
}
