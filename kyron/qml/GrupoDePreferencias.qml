import QtQuick

// Um grupo de linhas das Preferências. A descrição é texto puro; só a que leva o link "Obtenha aqui" (`descricaoRica`) é
// StyledText.
Column {
    id: grupo

    property string titulo
    property string descricao
    property bool descricaoRica: false
    property alias separada: caixa.separada
    default property alias linhas: caixa.linhas
    property alias sufixo: sufixoDoTitulo.data

    signal linkAcionado(string endereco)

    width: parent ? parent.width : implicitWidth
    spacing: 6
    // Conta as linhas pela regra (`aparece`), nunca pelo `visible` ou `implicitHeight`: estes dependem do próprio grupo e
    // o deixavam sempre escondido.
    readonly property int linhasAMostrar: {
        var n = 0
        for (var i = 0; i < caixa.itens.length; ++i) {
            var c = caixa.itens[i]
            if (c.buscavel === true && c.aparece) ++n
        }
        return n
    }
    readonly property bool soTemOutros: {
        for (var i = 0; i < caixa.itens.length; ++i)
            if (caixa.itens[i].buscavel === true) return false
        return true
    }
    visible: soTemOutros ? caixa.implicitHeight > 0 : linhasAMostrar > 0

    Item {
        width: parent.width
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
        linkColor: Qt.alpha(Tema.destaqueTexto, Tema.destaqueTexto.a * Tema.opacidadeApagado)
        color: Tema.textoSecundario
        font { family: Tema.fonte; pixelSize: Tema.corpo }
        onLinkActivated: endereco => grupo.linkAcionado(endereco)
    }
    GrupoDeLinhas {
        id: caixa
        width: parent.width
    }
}
