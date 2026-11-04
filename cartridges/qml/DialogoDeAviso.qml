import QtQuick

// A confirmação de um aviso com título, corpo e, se houver, uma lista de itens (título e subtítulo).
// Os textos vão sempre em PlainText: caminhos e mensagens de erro não são marcação.
DialogoDeAlerta {
    id: dialogo

    // [{ titulo, subtitulo }]
    property var itens: []
    property string rotuloDoBotao: "Dispensar"
    // O segundo botão (o padrão, como o `set_default_response` da `main`); vazio = escondido.
    property string rotuloSecundario: ""

    signal dispensado()
    signal secundario()

    function abrir(novoTitulo, novoCorpo, novosItens, novoRotuloSecundario) {
        titulo = novoTitulo
        corpo = novoCorpo
        itens = novosItens
        rotuloSecundario = novoRotuloSecundario || ""
        aberto = true
        // Reaberto com outro conteúdo (a pilha da D72), o foco vai de novo ao botão inicial.
        Qt.callLater(focarInicial)
    }
    function acionarSecundario() { responder("secundario") }
    function fechar() { responder("dispensar") }

    respostas: {
        var lista = [{ id: "dispensar", rotulo: rotuloDoBotao, objeto: "botaoDoDialogo" }]
        if (rotuloSecundario !== "")
            lista.push({ id: "secundario", rotulo: rotuloSecundario, objeto: "botaoSecundarioDoDialogo" })
        return lista
    }
    respostaDeEscape: "dispensar"
    respostaInicial: rotuloSecundario !== "" ? "secundario" : "dispensar"
    onRespondido: resposta => resposta === "secundario" ? secundario() : dispensado()

    // O `boxed-list` da `main` (`importer.py`): um cartão só, com as linhas separadas.
    GrupoDeLinhas {
        objectName: "listaDoDialogo"
        width: parent.width
        visible: dialogo.itens.length > 0
        Repeater {
            model: dialogo.itens
            delegate: LinhaDoGrupo {
                required property var modelData
                objectName: "item"
                titulo: modelData.titulo
                subtitulo: modelData.subtitulo
                quebraDoSubtitulo: Text.WrapAnywhere
            }
        }
    }
}
