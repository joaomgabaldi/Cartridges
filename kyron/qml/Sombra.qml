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
        model: Tema.aneis(sombra.camadas)
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
