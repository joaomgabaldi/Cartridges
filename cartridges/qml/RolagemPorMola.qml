import QtQuick

// A roda do mouse com inércia de mola (`spring_scroll.py` da `main`): cada entalhe soma `passo` px ao destino, que a
// mola leva por amortecimento crítico (massa 1, rigidez 220), herdando a velocidade da que ainda corre. Só o mouse:
// o touchpad segue o comportamento do Flickable. Filho do Flickable (`alvo`): `RolagemPorMola { alvo: grade }`.
Item {
    id: mola

    required property Flickable alvo
    property real passo: 120
    property real rigidez: 220
    // Perto o bastante do destino para parar, em pixels.
    property real epsilon: 0.5
    property bool ativa: true

    property real _destino: 0
    property real _velocidade: 0
    property real _desvio: 0   // posição menos destino, no instante `_tempo` = 0
    property real _tempo: 0
    property real _escrito: NaN
    readonly property real _omega: Math.sqrt(rigidez)
    readonly property bool correndo: relogio.running

    function _limites() {
        const topo = alvo.originY - alvo.topMargin
        return [topo, Math.max(topo, alvo.originY + alvo.contentHeight + alvo.bottomMargin - alvo.height)]
    }

    // A velocidade em `_tempo` segundos depois do início do trecho atual.
    function _velocidadeEm(t) {
        const b = _velocidade + _omega * _desvio
        return (b - _omega * _desvio - _omega * b * t) * Math.exp(-_omega * t)
    }
    function _desvioEm(t) {
        return (_desvio + (_velocidade + _omega * _desvio) * t) * Math.exp(-_omega * t)
    }

    function empurrar(entalhes) {
        const [minimo, maximo] = _limites()
        if (maximo <= minimo) return false
        const atual = alvo.contentY
        let velocidade = 0
        if (relogio.running) velocidade = _velocidadeEm(_tempo)
        else _destino = atual
        _destino = Math.max(minimo, Math.min(_destino + entalhes * passo, maximo))
        _desvio = atual - _destino
        _velocidade = velocidade
        _tempo = 0
        relogio.running = true
        return true
    }

    FrameAnimation {
        id: relogio
        onTriggered: {
            mola._tempo += frameTime
            const d = mola._desvioEm(mola._tempo)
            const v = mola._velocidadeEm(mola._tempo)
            const [minimo, maximo] = mola._limites()
            if (Math.abs(d) < mola.epsilon && Math.abs(v) < mola.epsilon) {
                mola._escrito = mola._destino
                mola.alvo.contentY = mola._destino
                running = false
            } else {
                mola._escrito = Math.max(minimo, Math.min(mola._destino + d, maximo))
                mola.alvo.contentY = mola._escrito
            }
        }
    }

    // Outra coisa mexeu na rolagem (teclado, barra de rolagem, `positionViewAtIndex`): a mola larga, senão sobrescreveria.
    Connections {
        target: mola.alvo
        function onContentYChanged() {
            if (relogio.running && Math.abs(mola.alvo.contentY - mola._escrito) > 0.5) relogio.running = false
        }
    }

    WheelHandler {
        parent: mola.alvo
        enabled: mola.ativa
        acceptedDevices: PointerDevice.Mouse
        acceptedModifiers: Qt.NoModifier
        // Cada entalhe é 120 de `angleDelta`; para cima (positivo) é rolar para cima.
        onWheel: event => event.accepted = mola.empurrar(-event.angleDelta.y / 120)
    }
}
