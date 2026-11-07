import QtQuick

// O fundo de uma camada que cobre a janela: clique, roda e passagem do mouse param aqui e não chegam ao que está embaixo.
// Vai como primeiro filho (ou `background`) da camada, para ficar abaixo dos controles dela.
MouseArea {
    anchors.fill: parent
    acceptedButtons: Qt.AllButtons
    hoverEnabled: true
    onWheel: wheel => wheel.accepted = true
}
