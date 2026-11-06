import QtQuick
import QtQuick.Controls.Basic

LinhaDoGrupo {
    id: linha

    property string icone
    property string rotulo
    property string dica
    property string rotuloSecundario
    property bool secundarioAtivo: true

    property alias botaoDaLinha: botao

    signal acionada()
    signal secundaria()

    quebraDoSubtitulo: Text.WrapAnywhere
    reservaADireita: ladoDireito.width
    sobre: botao.hovered && !botaoSecundario.hovered
    pressionada: botao.down
    foco: botao.visualFocus

    Button {
        id: botao
        objectName: linha.objectName + "Botao"
        anchors.fill: parent
        focusPolicy: Qt.StrongFocus
        hoverEnabled: true
        Accessible.name: linha.dica !== "" ? linha.dica : linha.titulo
        Accessible.description: linha.subtitulo
        Accessible.role: Accessible.Button
        Keys.onReturnPressed: click()
        Keys.onEnterPressed: click()
        onClicked: linha.acionada()
        contentItem: Item {}
        background: Item {}
        Dica { texto: linha.dica; ativa: botao.hovered; someAoClicar: true }
    }

    Row {
        id: ladoDireito
        anchors { right: parent.right; rightMargin: 14; verticalCenter: parent.verticalCenter }
        spacing: 12
        Botao {
            id: botaoSecundario
            objectName: linha.objectName + "BotaoSecundario"
            anchors.verticalCenter: parent.verticalCenter
            visible: linha.rotuloSecundario !== ""
            enabled: linha.secundarioAtivo
            text: linha.rotuloSecundario
            onClicked: linha.secundaria()
        }
        Icone {
            anchors.verticalCenter: parent.verticalCenter
            visible: linha.icone !== ""
            nome: linha.icone
        }
        // Só o desenho do botão: a linha inteira é o controle, então não há segunda parada de Tab.
        Rectangle {
            objectName: linha.objectName + "Rotulo"
            anchors.verticalCenter: parent.verticalCenter
            visible: linha.icone === "" && linha.rotulo !== ""
            width: textoDoRotulo.implicitWidth + 34
            height: 34
            radius: 9
            color: Qt.alpha(Tema.texto, Tema.texto.a * (linha.pressionada ? 0.30 : linha.sobre ? 0.15 : 0.10))
            Behavior on color { ColorAnimation { duration: Tema.duracaoCurta } }
            Text {
                id: textoDoRotulo
                anchors.centerIn: parent
                text: linha.rotulo
                textFormat: Text.PlainText
                color: Tema.texto
                font { family: Tema.fonte; pixelSize: Tema.corpo; weight: Tema.pesoForte }
            }
        }
    }
}
