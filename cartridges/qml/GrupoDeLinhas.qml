import QtQuick

// Um grupo de linhas do diálogo de edição: uma superfície arredondada com as linhas empilhadas.
// O grupo some quando nenhuma das linhas aparece.
Rectangle {
    id: grupo

    default property alias linhas: coluna.data

    implicitHeight: coluna.implicitHeight
    visible: coluna.implicitHeight > 0
    radius: 8
    color: Tema.superficie
    border.color: Tema.borda

    Column {
        id: coluna
        width: parent.width
    }
}
