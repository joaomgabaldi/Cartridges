import QtQuick

// Um grupo de linhas das Preferências (AdwPreferencesGroup): título e descrição acima de um `GrupoDeLinhas`.
// O grupo inteiro some quando nenhuma das linhas aparece. A descrição é texto puro; só a que leva o
// link "Obtenha aqui" (texto nosso, `descricaoRica`) é StyledText e avisa o link tocado em `linkAcionado`.
Column {
    id: grupo

    property string titulo
    property string descricao
    property bool descricaoRica: false
    // `separate-rows`: cada linha é um cartão.
    property alias separada: caixa.separada
    default property alias linhas: caixa.linhas
    property alias sufixo: sufixoDoTitulo.data

    signal linkAcionado(string endereco)

    width: parent ? parent.width : implicitWidth
    // preferencesgroup > box: 6 entre o cabeçalho e o cartão; com descrição, 6 a mais.
    spacing: 6
    // Com linhas das Preferências, conta-as pela regra (`aparece`), nunca pelo `visible` ou pelo `implicitHeight`:
    // estes dependem do próprio grupo e o deixavam sempre escondido (D58).
    readonly property int linhasAMostrar: {
        var n = 0
        for (var i = 0; i < caixa.itens.length; ++i) {
            var c = caixa.itens[i]
            if (c.buscavel === true && c.aparece) ++n
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
    // box.single-line: 34 de altura mínima quando só há o título.
    Item {
        width: parent.width
        // Título e descrição apagam com o grupo; as linhas apagam sozinhas.
        opacity: grupo.enabled ? 1 : Tema.opacidadeDesabilitado
        height: Math.max(tituloDoGrupo.implicitHeight, sufixoDoTitulo.implicitHeight, grupo.descricao === "" ? 34 : 0)
        visible: tituloDoGrupo.text !== "" || sufixoDoTitulo.children.length > 0

        Text {
            id: tituloDoGrupo
            objectName: grupo.objectName + "Titulo"
            width: parent.width - (sufixoDoTitulo.children.length > 0 ? sufixoDoTitulo.width + 8 : 0)
            anchors.verticalCenter: parent.verticalCenter
            text: grupo.titulo
            textFormat: Text.PlainText
            wrapMode: Text.Wrap
            color: Tema.texto
            font { family: Tema.fonte; pixelSize: Tema.corpo; weight: Tema.pesoForte }
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
        opacity: grupo.enabled ? 1 : Tema.opacidadeDesabilitado
        visible: text !== ""
        bottomPadding: 6
        text: grupo.descricao
        textFormat: grupo.descricaoRica ? Text.StyledText : Text.PlainText
        wrapMode: Text.Wrap
        linkColor: Tema.destaqueTexto
        color: Tema.textoSecundario
        font { family: Tema.fonte; pixelSize: Tema.corpo }
        onLinkActivated: endereco => grupo.linkAcionado(endereco)
    }
    GrupoDeLinhas {
        id: caixa
        width: parent.width
    }
}
