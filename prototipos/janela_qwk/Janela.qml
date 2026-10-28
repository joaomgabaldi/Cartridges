import QtQuick
import QtQuick.Window
import QWindowKit

// Janela principal sem moldura, com a barra de título própria (como a
// Adw.HeaderBar do app) e o QWindowKit cuidando de borda, sombra e snap.
Window {
    id: janela
    width: 1100
    height: 700
    color: "#242424"
    title: "Cartridges (protótipo da janela)"

    readonly property int alturaDaBarra: 46
    readonly property int larguraDoBotao: 46

    Component.onCompleted: {
        agente.setup(janela)
        agente.setWindowAttribute("dark-mode", true)
    }

    WindowAgent { id: agente }

    Rectangle {
        id: barra
        anchors { top: parent.top; left: parent.left; right: parent.right }
        height: janela.alturaDaBarra
        color: janela.active ? "#303030" : "#2a2a2a"
        Component.onCompleted: agente.setTitleBar(barra)

        Text {
            anchors.centerIn: parent
            text: "Biblioteca"
            color: janela.active ? "#ffffff" : "#9a9a9a"
            font.pixelSize: 15
            font.weight: Font.Bold
        }

        Row {
            anchors { top: parent.top; right: parent.right; bottom: parent.bottom }
            Botao {
                id: minimizar
                glifo: ""
                onClicked: janela.showMinimized()
                Component.onCompleted: agente.setSystemButton(WindowAgent.Minimize, minimizar)
            }
            Botao {
                id: maximizar
                glifo: janela.visibility === Window.Maximized ? "" : ""
                onClicked: janela.visibility === Window.Maximized ? janela.showNormal() : janela.showMaximized()
                Component.onCompleted: agente.setSystemButton(WindowAgent.Maximize, maximizar)
            }
            Botao {
                id: fechar
                glifo: ""
                corDoFoco: "#c42b1c"
                onClicked: janela.close()
                Component.onCompleted: agente.setSystemButton(WindowAgent.Close, fechar)
            }
        }
    }

    component Botao: Rectangle {
        id: botao
        property string glifo
        property color corDoFoco: "#3d3d3d"
        signal clicked()
        width: janela.larguraDoBotao
        height: janela.alturaDaBarra
        color: area.containsMouse ? corDoFoco : "transparent"
        Text {
            anchors.centerIn: parent
            text: botao.glifo
            // Mesmos códigos nas duas fontes; a Fluent só existe no Windows 11.
            font.family: Qt.fontFamilies().includes("Segoe Fluent Icons") ? "Segoe Fluent Icons" : "Segoe MDL2 Assets"
            font.pixelSize: 10
            color: "white"
        }
        MouseArea {
            id: area
            anchors.fill: parent
            hoverEnabled: true
            onClicked: botao.clicked()
        }
    }

    Text {
        anchors.centerIn: parent
        color: "#9a9a9a"
        font.pixelSize: 14
        text: "Conteúdo da biblioteca\n" + janela.width + " × " + janela.height
              + " · " + Screen.name + " · escala " + Screen.devicePixelRatio
        horizontalAlignment: Text.AlignHCenter
    }
}
