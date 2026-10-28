import QtQuick
import QWindowKit

// Barra de título própria, com os botões de sistema que o QWindowKit liga ao Windows
// (snap layouts no maximizar, hit-test de borda). `janela` e `agente` vêm de Principal.qml.
Rectangle {
    id: barra

    required property Window janela
    required property WindowAgent agente
    property string titulo: ""

    readonly property int altura: 46
    readonly property int larguraDoBotao: 46

    height: altura
    color: janela.active ? Tema.barra : Tema.barraInativa
    Component.onCompleted: agente.setTitleBar(barra)

    Text {
        anchors.centerIn: parent
        text: barra.titulo
        color: barra.janela.active ? Tema.texto : Tema.textoSecundario
        font.family: Tema.fonte
        font.pixelSize: 15
        font.weight: Font.Bold
    }

    Row {
        anchors { top: parent.top; right: parent.right; bottom: parent.bottom }
        Botao {
            id: minimizar
            glifo: "\uE921"
            onClicked: barra.janela.showMinimized()
            Component.onCompleted: barra.agente.setSystemButton(WindowAgent.Minimize, minimizar)
        }
        Botao {
            id: maximizar
            glifo: barra.janela.visibility === Window.Maximized ? "\uE923" : "\uE922"
            onClicked: barra.janela.visibility === Window.Maximized ? barra.janela.showNormal() : barra.janela.showMaximized()
            Component.onCompleted: barra.agente.setSystemButton(WindowAgent.Maximize, maximizar)
        }
        Botao {
            id: fechar
            glifo: "\uE8BB"
            ehFechar: true
            corDoFoco: Tema.botaoFechar
            onClicked: barra.janela.close()
            Component.onCompleted: barra.agente.setSystemButton(WindowAgent.Close, fechar)
        }
    }

    component Botao: Rectangle {
        id: botao
        property string glifo
        property color corDoFoco: Tema.botaoSobre
        property bool ehFechar: false
        signal clicked()
        width: barra.larguraDoBotao
        height: barra.altura
        color: area.containsMouse ? corDoFoco : "transparent"
        Text {
            anchors.centerIn: parent
            text: botao.glifo
            // Mesmos códigos nas duas fontes; a Fluent só existe no Windows 11.
            font.family: Qt.fontFamilies().includes("Segoe Fluent Icons") ? "Segoe Fluent Icons" : "Segoe MDL2 Assets"
            font.pixelSize: 10
            color: botao.ehFechar && area.containsMouse ? "white" : Tema.texto
        }
        MouseArea {
            id: area
            anchors.fill: parent
            hoverEnabled: true
            onClicked: botao.clicked()
        }
    }
}
