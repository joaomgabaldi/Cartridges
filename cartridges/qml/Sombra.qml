import QtQuick

// A sombra sem sombreador: anéis em volta do pai, cada um mais fraco, e nada por baixo dele (o cartão do
// tema escuro é translúcido e a sombra não pode aparecer através). `camadas`: as de `Tema.sombra*`. Não recebe clique.
Item {
    id: sombra

    property var camadas: []
    property real raio: 0

    anchors.fill: parent
    z: -1
    enabled: false

    Repeater {
        model: {
            var aneis = []
            for (var c of sombra.camadas) {
                const [dy, desfoque, espalhamento, r, g, b, a] = c
                const fim = espalhamento + desfoque
                // Queda linear de `a` a 0 entre (espalhamento - desfoque) e (espalhamento + desfoque), como um gaussiano.
                const forca = x => desfoque === 0 ? (x < espalhamento ? a : 0)
                    : a * Math.max(0, Math.min(1, (espalhamento + desfoque - x) / (2 * desfoque)))
                for (var d = 1; d <= fim; ++d)
                    aneis.push({ dy: dy, d: d, cor: Qt.rgba(r, g, b, forca(d - 1) - forca(d)) })
            }
            return aneis
        }
        Rectangle {
            required property var modelData
            x: -modelData.d
            y: -modelData.d + modelData.dy
            width: sombra.width + 2 * modelData.d
            height: sombra.height + 2 * modelData.d
            radius: sombra.raio > 0 ? sombra.raio + modelData.d : 0
            color: "transparent"
            border { width: modelData.d; color: modelData.cor }
        }
    }
}
