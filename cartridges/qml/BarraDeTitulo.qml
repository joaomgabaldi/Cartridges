import QtQuick

// Barra de título própria, com os botões de sistema que o QWindowKit liga ao Windows
// (snap layouts no maximizar, hit-test de borda). `janela` e `agente` vêm de Principal.qml.
// Plana (a ToolbarView da `main`): da cor do fundo; `sombra` liga a linha de baixo quando o conteúdo está rolado.
// Desabilitada (`enabled: false`), o QWindowKit a trata como se não existisse: nem arrasto, nem botões do sistema
// (`isInTitleBarDraggableArea` e `isInSystemButtons` conferem o `isEnabled`). É assim que um modal a tranca (J05).
Rectangle {
    id: barra

    required property Window janela
    // O WindowAgent; nulo nos testes, que rodam sem a ponte do QWindowKit.
    property QtObject agente
    property string titulo: ""
    property bool sombra: false
    // Só minimizar e fechar (`:minimize,close`), como a janela das tarefas.
    property bool comMaximizar: true
    // Sem o fechar (`:minimize`), como a janela "Restaurando o backup".
    property bool comFechar: true
    // Os botões da página: `inicio` à esquerda do título, `fim` à direita, antes dos botões do sistema.
    default property alias inicio: areaDoInicio.data
    property alias fim: areaDoFim.data

    // headerbar: min-height 47.
    readonly property int altura: 47
    // windowcontrols > button: 24 de largura e 5 de recuo; o círculo é a imagem.
    readonly property int larguraDoBotao: 34

    height: altura
    color: Tema.fundo

    // Chamado pela Principal depois do setup do agente.
    function ligarAgente() {
        agente.setTitleBar(barra)
        agente.botaoDeSistema("minimizar", minimizar)
        if (comMaximizar) agente.botaoDeSistema("maximizar", maximizar)
        if (comFechar) agente.botaoDeSistema("fechar", fechar)
    }

    // padding 6/7/7/7 da headerbar: o centro do conteúdo fica em 23, não em 23,5.
    // headerbar:backdrop > windowhandle: o conteúdo da janela inativa fica a 50%, com a transição de 200 ms.
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

    // A linha de baixo da headerbar, com o conteúdo rolado.
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
