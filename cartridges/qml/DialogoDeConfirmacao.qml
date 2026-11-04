import QtQuick

// Pergunta com dois botões (três, com `rotuloAlternativo`). Texto em PlainText: nome de jogo e URL não são marcação.
DialogoDeAlerta {
    id: dialogo

    property string rotuloConfirmar: "Confirmar"
    property string rotuloCancelar: "Cancelar"
    property string rotuloAlternativo: ""
    property bool destrutivo: false
    property bool sugerido: false

    signal confirmado()
    signal cancelado()
    signal alternativo()

    function abrir() {
        aberto = true
        Qt.callLater(focarInicial)
    }
    function resolverComo(escolha) { responder(escolha) }
    function resolver(confirmou) { responder(confirmou ? "confirmar" : "cancelar") }

    respostas: {
        var lista = [
            { id: "cancelar", rotulo: rotuloCancelar, objeto: "botaoCancelarDoDialogo" },
            { id: "confirmar", rotulo: rotuloConfirmar, objeto: "botaoConfirmarDoDialogo", aparencia: destrutivo ? "destrutivo" : sugerido ? "sugestao" : "normal" }
        ]
        if (rotuloAlternativo !== "")
            lista.push({ id: "alternativo", rotulo: rotuloAlternativo, objeto: "botaoAlternativoDoDialogo" })
        return lista
    }
    respostaDeEscape: "cancelar"
    onRespondido: resposta => resposta === "confirmar" ? confirmado() : resposta === "alternativo" ? alternativo() : cancelado()
}
