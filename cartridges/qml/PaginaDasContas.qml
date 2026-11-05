import QtQuick

Column {
    id: pagina
    objectName: "paginaDasContas"

    width: parent ? parent.width : implicitWidth
    spacing: 24

    // As contas existem só com as Preferências abertas; o `Loader` evita ler um `contas` nulo ao fechar.
    Loader {
        objectName: "carregadorDasContas"
        width: parent.width
        active: preferencias.contas !== null
        visible: active
        sourceComponent: GrupoDasContas { contas: preferencias.contas }
    }
}
