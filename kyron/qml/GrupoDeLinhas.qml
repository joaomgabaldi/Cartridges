import QtQuick

Item {
    id: grupo

    default property alias linhas: coluna.data
    readonly property alias itens: coluna.children
    property bool separada: false

    implicitHeight: coluna.implicitHeight
    visible: coluna.implicitHeight > 0

    Rectangle {
        anchors.fill: parent
        visible: !grupo.separada
        radius: 12
        color: Tema.cartao
        Sombra { camadas: Tema.sombraCartao; raio: 12 }
    }

    Column {
        id: coluna
        readonly property bool separada: grupo.separada
        width: parent.width
        spacing: grupo.separada ? 12 : 0
    }
}
