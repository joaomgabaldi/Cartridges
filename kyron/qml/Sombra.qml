import QtQuick

// A sombra sem sombreador: anéis em volta do pai, cada um mais fraco, e nada por baixo (o cartão do tema escuro é translúcido).
Item {
    id: sombra

    property var camadas: []
    property real raio: 0

    anchors.fill: parent
    z: -1
    enabled: false

    Repeater {
        // Como o `box-shadow` do CSS (GTK): gaussiana de desvio desfoque/2 depois do espalhamento, até 3 desvios.
        // O anel `d` cobre a faixa de 0 a d e os anéis se compõem (1 - Π(1 - α)), então cada α é o que leva
        // a composição até a força `forca(d - 1)`.
        model: {
            var aneis = []
            const fi = z => {  // Φ, a normal acumulada (Abramowitz-Stegun 7.1.26: erro < 1,5e-7)
                const t = 1 / (1 + 0.3275911 * Math.abs(z) / Math.SQRT2)
                const erf = 1 - t * (0.254829592 + t * (-0.284496736 + t * (1.421413741 + t * (-1.453152027 + t * 1.061405429)))) * Math.exp(-z * z / 2)
                return 0.5 * (1 + (z < 0 ? -erf : erf))
            }
            for (var c of sombra.camadas) {
                const [dy, desfoque, espalhamento, r, g, b, a] = c
                const sigma = desfoque / 2
                const fim = espalhamento + Math.ceil(3 * sigma)
                const forca = x => x >= fim ? 0 : sigma === 0 ? (x < espalhamento ? a : 0) : a * (1 - fi((x - espalhamento) / sigma))
                for (var d = 1; d <= fim; ++d) {
                    const alfa = (forca(d - 1) - forca(d)) / Math.max(1e-6, 1 - forca(d))
                    if (alfa * 255 >= 0.5)  // abaixo de meio passo de 8 bits o anel não muda nenhum pixel: não vira Rectangle
                        aneis.push({ dy: dy, d: d, cor: Qt.rgba(r, g, b, alfa) })
                }
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
