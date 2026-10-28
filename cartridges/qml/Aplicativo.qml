import QtQuick

// A janela do app: a grade da biblioteca e as camadas de aviso e confirmação.
// `biblioteca` e `ponte` vêm do contexto (cartridges/app.py).
Principal {
    id: janela

    // Lidos aqui, fora da Grade e dos Avisos, porque lá os nomes das propriedades são os mesmos.
    readonly property QtObject modelo: biblioteca
    readonly property QtObject ligacao: ponte

    // Depois do setup do QWindowKit (Principal.qml), que roda no onCompleted da base.
    Component.onCompleted: visible = true

    Grade {
        anchors.fill: parent
        biblioteca: janela.modelo
    }

    Avisos {
        anchors.fill: parent
        ponte: janela.ligacao
    }

    Connections {
        target: janela.ligacao
        function onSairDaFrente() { janela.showMinimized() }
    }
}
