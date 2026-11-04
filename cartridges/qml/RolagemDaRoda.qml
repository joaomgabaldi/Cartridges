import QtQuick

// A roda do mouse nas listas rolantes: cada entalhe anda `pow(altura visível, 2/3)` pixels (cerca de 78 nas Preferências; o `Flickable` puro anda uns 23), sem mola. Só o mouse.
Item {
    id: roda

    required property Flickable alvo
    property bool ativa: true

    readonly property real passo: Math.pow(alvo.height, 2 / 3)

    function rolar(entalhes) {
        const topo = alvo.originY - alvo.topMargin
        const fim = Math.max(topo, alvo.originY + alvo.contentHeight + alvo.bottomMargin - alvo.height)
        if (fim <= topo) return false
        alvo.contentY = Math.max(topo, Math.min(alvo.contentY + entalhes * passo, fim))
        return true
    }

    WheelHandler {
        parent: roda.alvo
        enabled: roda.ativa
        acceptedDevices: PointerDevice.Mouse
        acceptedModifiers: Qt.NoModifier
        onWheel: event => event.accepted = roda.rolar(-event.angleDelta.y / 120)
    }
}
