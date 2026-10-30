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
    property alias sufixo: sufixoDoTitulo.data

    signal linkAcionado(string endereco)

    width: parent ? parent.width : implicitWidth
    spacing: 8
    // Com linhas das Preferências, conta-as pela regra e pelo filtro (`aparece` e `passaNoFiltro`), nunca pelo `visible` ou pelo `implicitHeight`:
    // estes dependem do próprio grupo e o deixavam sempre escondido (D58).
    readonly property int linhasAMostrar: {
        var n = 0
        for (var i = 0; i < caixa.itens.length; ++i) {
            var c = caixa.itens[i]
            if (c.buscavel === true && c.aparece && c.passaNoFiltro) ++n
        }
        return n
    }
    // Sem linha buscável (os assistentes): vale a altura, como antes da busca.
    readonly property bool soTemOutros: {
        for (var i = 0; i < caixa.itens.length; ++i)
            if (caixa.itens[i].buscavel === true) return false
        return true
    }
    visible: soTemOutros ? caixa.implicitHeight > 0 : linhasAMostrar > 0

    // O título e, à direita dele, o que o grupo puser em `sufixo` (um botão-link, como o `header-suffix` do Adwaita).
    Item {
        width: parent.width
        height: Math.max(tituloDoGrupo.implicitHeight, sufixoDoTitulo.implicitHeight)
        visible: tituloDoGrupo.text !== ""

        Text {
            id: tituloDoGrupo
            objectName: grupo.objectName + "Titulo"
            width: parent.width - (sufixoDoTitulo.children.length > 0 ? sufixoDoTitulo.width + 8 : 0)
            anchors.verticalCenter: parent.verticalCenter
            text: grupo.titulo
            textFormat: Text.PlainText
            wrapMode: Text.Wrap
            color: Tema.texto
            font { family: Tema.fonte; pixelSize: 15; weight: Font.DemiBold }
            Accessible.role: Accessible.Heading
        }
        Row {
            id: sufixoDoTitulo
            anchors { right: parent.right; verticalCenter: parent.verticalCenter }
        }
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
