import QtQuick

// Um grupo de linhas das Preferências: título e descrição acima de um `GrupoDeLinhas`.
// O grupo inteiro some quando nenhuma das linhas aparece. A descrição é texto puro; só a que leva o
// link "Obtenha aqui" (texto nosso, `descricaoRica`) é StyledText e avisa o link tocado em `linkAcionado`.
Column {
    id: grupo

    property string titulo
    property string descricao
    property bool descricaoRica: false
    default property alias linhas: caixa.linhas

    signal linkAcionado(string endereco)

    width: parent ? parent.width : implicitWidth
    spacing: 8
    visible: caixa.implicitHeight > 0

    Text {
        objectName: grupo.objectName + "Titulo"
        width: parent.width
        visible: text !== ""
        text: grupo.titulo
        textFormat: Text.PlainText
        wrapMode: Text.Wrap
        color: Tema.texto
        font { family: Tema.fonte; pixelSize: 15; weight: Font.DemiBold }
        Accessible.role: Accessible.Heading
    }
    Text {
        objectName: grupo.objectName + "Descricao"
        width: parent.width
        visible: text !== ""
        text: grupo.descricao
        textFormat: grupo.descricaoRica ? Text.StyledText : Text.PlainText
        wrapMode: Text.Wrap
        linkColor: Tema.destaque
        color: Tema.textoSecundario
        font { family: Tema.fonte; pixelSize: 13 }
        onLinkActivated: endereco => grupo.linkAcionado(endereco)
    }
    GrupoDeLinhas {
        id: caixa
        width: parent.width
    }
}
