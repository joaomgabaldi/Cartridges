import QtQuick

// O `list.boxed-list`: um cartão com raio 12, sombra e as linhas empilhadas; o grupo some quando nenhuma aparece.
// `separada` (`boxed-list-separate`): cada linha é o seu próprio cartão, com 12 entre elas.
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
