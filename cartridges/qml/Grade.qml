import QtQuick

// A grade de capas da biblioteca.
GridView {
    id: grade

    // ModeloDaBiblioteca
    property QtObject biblioteca

    readonly property int margem: 12
    cellWidth: 200 + 2 * margem
    cellHeight: 300 + 40 + 2 * margem
    clip: true
    model: biblioteca

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
