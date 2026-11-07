import QtQuick

// A pílula do Big Picture com a tecla do controle: o conteúdo centrado, com a mesma folga dos dois lados.
Rectangle {
    id: botao

    property string texto
    property string letra: "A"
    property bool ativo: true
    property real unidade: 1  // acompanha o tamanho da tela
    signal acionado()

    width: conteudo.width + 48 * unidade
    height: 52 * unidade
    radius: height / 2
    color: "white"
    Accessible.role: Accessible.Button
    Accessible.name: texto

    Row {
        id: conteudo
        objectName: "conteudoDoBotao"
        anchors.centerIn: parent
        spacing: 10 * botao.unidade
        GlifoDoBotao {
            visible: controle.temControle  // sem controle, a tecla dele não diz nada: fica só o texto
            letra: botao.letra
            tamanho: 26 * botao.unidade
            anchors.verticalCenter: parent.verticalCenter
        }
        Text {
            anchors.verticalCenter: parent.verticalCenter
            text: botao.texto
            textFormat: Text.PlainText
            color: "black"
            font { family: Tema.fonte; pixelSize: Math.round(16 * botao.unidade); weight: Tema.pesoForte }
        }
    }
    TapHandler {
        enabled: botao.ativo
        onTapped: botao.acionado()
    }
}
