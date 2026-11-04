import QtQuick
import QtQuick.Shapes

// Um arco que gira, cresce e encolhe, na cor do texto. Só anima com `running`.
Item {
    id: girador

    property bool running: true
    property color cor: Tema.texto
    property real grossura: width / 10

    implicitWidth: 64
    implicitHeight: 64
    Accessible.role: Accessible.Animation

    property real _arco: 90

    Shape {
        anchors.fill: parent
        layer.enabled: true
        layer.samples: 4
        ShapePath {
            strokeColor: girador.cor
            strokeWidth: girador.grossura
            fillColor: "transparent"
            capStyle: ShapePath.RoundCap
            PathAngleArc {
                centerX: girador.width / 2
                centerY: girador.height / 2
                radiusX: (girador.width - girador.grossura) / 2
                radiusY: radiusX
                startAngle: -90
                sweepAngle: girador._arco
            }
        }
    }

    RotationAnimator on rotation {
        running: girador.running && girador.visible
        from: 0
        to: 360
        duration: 1200
        loops: Animation.Infinite
    }
    SequentialAnimation {
        running: girador.running && girador.visible
        loops: Animation.Infinite
        NumberAnimation { target: girador; property: "_arco"; from: 30; to: 270; duration: 700; easing.type: Easing.InOutQuad }
        NumberAnimation { target: girador; property: "_arco"; from: 270; to: 30; duration: 700; easing.type: Easing.InOutQuad }
    }
}
