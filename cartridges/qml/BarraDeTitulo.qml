import QtQuick

// Barra de título própria, com os botões de sistema que o QWindowKit liga ao Windows
// (snap layouts no maximizar, hit-test de borda). `janela` e `agente` vêm de Principal.qml.
Rectangle {
    id: barra

    required property Window janela
    // O WindowAgent; nulo nos testes, que rodam sem a ponte do QWindowKit.
    property QtObject agente
    property string titulo: ""
    // Os botões da página: `inicio` à esquerda do título, `fim` à direita, antes dos botões do sistema.
    default property alias inicio: areaDoInicio.data
    property alias fim: areaDoFim.data

    readonly property int altura: 46
    readonly property int larguraDoBotao: 46

    height: altura
    color: janela.active ? Tema.barra : Tema.barraInativa

    // Chamado pela Principal depois do setup do agente.
    function ligarAgente() {
        agente.setTitleBar(barra)
        agente.botaoDeSistema("minimizar", minimizar)
        agente.botaoDeSistema("maximizar", maximizar)
        agente.botaoDeSistema("fechar", fechar)
    }

    Row {
        id: areaDoInicio
        anchors { left: parent.left; leftMargin: 6; verticalCenter: parent.verticalCenter }
        spacing: 2
    }

    Text {
        anchors.centerIn: parent
        objectName: "tituloDaBarraTexto"
        // O nome do jogo é texto de terceiros e pode ser longo; deixa folga para os botões dos dois lados.
        width: Math.min(implicitWidth, Math.max(0, parent.width - 320))
        elide: Text.ElideRight
        text: barra.titulo
        textFormat: Text.PlainText
        color: barra.janela.active ? Tema.texto : Tema.textoSecundario
        font.family: Tema.fonte
        font.pixelSize: 15
        font.weight: Font.Bold
    }

    Row {
        id: areaDoFim
        anchors { right: sistema.left; rightMargin: 6; verticalCenter: parent.verticalCenter }
        spacing: 2
        layoutDirection: Qt.RightToLeft
    }

    Row {
        id: sistema
        anchors { top: parent.top; right: parent.right; bottom: parent.bottom }
        Botao {
            id: minimizar
            glifo: "\uE921"
            onClicked: barra.janela.showMinimized()
        }
        Botao {
            id: maximizar
            glifo: barra.janela.visibility === Window.Maximized ? "\uE923" : "\uE922"
            onClicked: barra.janela.visibility === Window.Maximized ? barra.janela.showNormal() : barra.janela.showMaximized()
        }
        Botao {
            id: fechar
            glifo: "\uE8BB"
            ehFechar: true
            corDoFoco: Tema.botaoFechar
            onClicked: barra.janela.close()
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
            font.family: Tema.fonteDeIcones
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
