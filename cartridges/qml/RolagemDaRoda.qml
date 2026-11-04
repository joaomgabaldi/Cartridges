import QtQuick

// A roda do mouse nas listas rolantes dos diálogos e das páginas: o padrão do `Gtk.ScrolledWindow`, em que cada entalhe
// anda `pow(altura visível, 2/3)` pixels (cerca de 78 nas Preferências); o `Flickable` puro anda uns 23. Sem mola: a
// mola é só das duas bibliotecas e da lista de zerados (`RolagemPorMola`) e das Preferências (com animações). Só o mouse; o touchpad segue o do Flickable.
// Filho do Flickable: `RolagemDaRoda { alvo: rolagem }`.
Item {
    id: roda

    required property Flickable alvo
    property bool ativa: true

    // Pixels por entalhe.
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
        // Cada entalhe é 120 de `angleDelta`; para cima (positivo) é rolar para cima.
        onWheel: event => event.accepted = roda.rolar(-event.angleDelta.y / 120)
    }
}
