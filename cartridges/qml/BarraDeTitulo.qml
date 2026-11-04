import QtQuick

// Barra de título própria, com os botões de sistema que o QWindowKit liga ao Windows (snap layouts no maximizar, hit-test
// de borda). `janela` e `agente` vêm de Principal.qml. `sombra` liga a linha de baixo quando o conteúdo está rolado.
// Desabilitada (`enabled: false`), o QWindowKit a trata como se não existisse: nem arrasto, nem botões do sistema
// (`isInTitleBarDraggableArea` e `isInSystemButtons` conferem o `isEnabled`). É assim que um modal a tranca.
Rectangle {
    id: barra

    required property Window janela
    // O WindowAgent; nulo nos testes, que rodam sem a ponte do QWindowKit.
    property QtObject agente
    property string titulo: ""
    property bool sombra: false
    // Sem fundo: a página de trás (os detalhes do jogo) passa por baixo.
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
            // O nome do jogo é texto de terceiros e pode ser longo; deixa folga para os botões dos dois lados.
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

    Rectangle {
        anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
        height: 1
        visible: barra.sombra
        color: Tema.sombraDaBarra
    }

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
