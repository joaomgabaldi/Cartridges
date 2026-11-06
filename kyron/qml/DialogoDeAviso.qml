import QtQuick

// Confirmação de um aviso com título, corpo e lista de itens. Textos em PlainText: caminhos e mensagens de erro não são
// marcação.
DialogoDeAlerta {
    id: dialogo

    property var itens: []
    property string rotuloDoBotao: "Dispensar"
    property string rotuloSecundario: ""

    signal dispensado()
    signal secundario()

    function abrir(novoTitulo, novoCorpo, novosItens, novoRotuloSecundario) {
        titulo = novoTitulo
        corpo = novoCorpo
        itens = novosItens
        rotuloSecundario = novoRotuloSecundario || ""
        aberto = true
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
