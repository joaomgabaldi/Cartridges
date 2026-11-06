import QtQuick

Rectangle {
    id: anel

    property bool ativo: false
    property real raio: 9
    property real raioSuperior: raio
    property real raioInferior: raio
    property real afastamento: 1
    property real _fora: ativo ? 2 + afastamento : 5 + afastamento

    objectName: "anelDeFoco"
    anchors { fill: parent; margins: -_fora }
    z: 10
    enabled: false
    topLeftRadius: Math.max(0, raioSuperior + _fora)
    topRightRadius: topLeftRadius
    bottomLeftRadius: Math.max(0, raioInferior + _fora)
    bottomRightRadius: bottomLeftRadius
    color: "transparent"
    border { width: 2; color: Qt.alpha(Tema.destaqueTexto, 0.5) }
    opacity: ativo ? 1 : 0
    visible: opacity > 0

    Behavior on opacity { NumberAnimation { duration: Tema.duracaoCurta; easing { type: Easing.Bezier; bezierCurve: Tema.curva } } }
    Behavior on _fora { NumberAnimation { duration: Tema.duracaoCurta; easing { type: Easing.Bezier; bezierCurve: Tema.curva } } }
}
