import QtQuick

// O contorno do foco do teclado (`outline` da libadwaita): 2 px em `destaqueTexto` a 50%, com a transição de 200 ms.
// Filho do item focável: `AnelDeFoco { ativo: botao.visualFocus; raio: 9 }`. `afastamento`: o `outline-offset` do CSS
// (1 nos botões e no interruptor, -2 nas linhas e nos botões da barra, -1 nos campos).
Rectangle {
    id: anel

    property bool ativo: false
    property real raio: 9
    // Cantos de cima e de baixo à parte: a linha de um grupo só arredonda onde o cartão arredonda.
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
