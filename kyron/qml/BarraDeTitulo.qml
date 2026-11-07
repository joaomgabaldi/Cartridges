import QtQuick

// Barra de título própria, com os botões de sistema que o QWindowKit liga ao Windows. `janela` e `agente` vêm de
// Principal.qml.
// Desabilitada, o QWindowKit a trata como inexistente (`isInTitleBarDraggableArea` e `isInSystemButtons` conferem o
// `isEnabled`): é assim que um modal a tranca.
Rectangle {
    id: barra

    required property Window janela
    property QtObject agente
    property string titulo: ""
    property bool sombra: false
    property bool transparente: false
    property bool comMaximizar: true
    property bool comFechar: true
    default property alias inicio: areaDoInicio.data
    property alias fim: areaDoFim.data

    readonly property int altura: 47
    readonly property int larguraDoBotao: 34

    height: altura
    color: transparente ? "transparent" : Tema.fundo

    function ligarAgente() {
        agente.setTitleBar(barra)
        agente.botaoDeSistema("minimizar", minimizar)
        if (comMaximizar) agente.botaoDeSistema("maximizar", maximizar)
        if (comFechar) agente.botaoDeSistema("fechar", fechar)
    }

    Item {
        anchors.fill: parent
        opacity: barra.janela.active ? 1 : 0.5
        Behavior on opacity { NumberAnimation { duration: Tema.duracaoCurta } }

        Row {
            id: areaDoInicio
            anchors { left: parent.left; leftMargin: 6; verticalCenter: parent.verticalCenter; verticalCenterOffset: -0.5 }
            spacing: 6
        }

        Text {
            anchors { centerIn: parent; verticalCenterOffset: -1.5 }
            objectName: "tituloDaBarraTexto"
            width: Math.min(implicitWidth, Math.max(0, parent.width - 2 * Math.max(areaDoInicio.width + 12, areaDoFim.width + sistema.width + 12)))
            elide: Text.ElideRight
            text: barra.titulo
            textFormat: Text.PlainText
            color: Tema.texto
            font { family: Tema.fonte; pixelSize: Tema.corpo; weight: Tema.pesoForte }
        }

        Row {
            id: areaDoFim
            anchors { right: sistema.left; rightMargin: 6; verticalCenter: parent.verticalCenter; verticalCenterOffset: -0.5 }
            spacing: 6
            layoutDirection: Qt.RightToLeft
        }

        Row {
            id: sistema
            anchors { top: parent.top; right: parent.right; rightMargin: 6; bottom: parent.bottom }
            spacing: 3
            Botao {
                id: minimizar
                icone: "window-minimize"
                onClicked: barra.janela.showMinimized()
            }
            Botao {
                id: maximizar
                visible: barra.comMaximizar
                icone: barra.janela.visibility === Window.Maximized ? "window-restore" : "window-maximize"
                onClicked: barra.janela.visibility === Window.Maximized ? barra.janela.showNormal() : barra.janela.showMaximized()
            }
            Botao {
                id: fechar
                visible: barra.comFechar
                icone: "window-close"
                onClicked: barra.janela.close()
            }
        }
    }

    SombraDeRolagem { objectName: "sombraDaBarra"; ativa: barra.sombra }

    component Botao: Item {
        id: botao
        property string icone
        signal clicked()
        width: barra.larguraDoBotao
        height: barra.altura
        Rectangle {
            anchors { centerIn: parent; verticalCenterOffset: -0.5 }
            width: 24
            height: 24
            radius: 12
            color: area.pressed ? Tema.pressionado : area.containsMouse ? Tema.botaoSobre : Tema.botao
            Behavior on color { ColorAnimation { duration: Tema.duracaoCurta } }
            Icone {
                anchors.centerIn: parent
                nome: botao.icone
            }
        }
        MouseArea {
            id: area
            anchors.fill: parent
            hoverEnabled: true
            onClicked: botao.clicked()
        }
    }
}
