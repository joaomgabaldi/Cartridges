import QtQuick

// Uma pergunta com dois botões (três, com `rotuloAlternativo`). O texto vai sempre em PlainText (nome de jogo e URL não
// são marcação). Esc vale como cancelar. Nenhum botão é destacado, salvo o destrutivo, em vermelho; o foco inicial vai ao
// primeiro, o de sair.
DialogoDeAlerta {
    id: dialogo

    property string rotuloConfirmar: "Confirmar"
    property string rotuloCancelar: "Cancelar"
    // Vazio = sem o terceiro botão. Com ele a ordem é Cancelar | confirmar | alternativo.
    property string rotuloAlternativo: ""
    property bool destrutivo: false
    // Raro: a pergunta comum não destaca nada.
    property bool sugerido: false

    signal confirmado()
    signal cancelado()
    signal alternativo()

    function abrir() {
        aberto = true
        // Reaberto com outro conteúdo, o foco vai de novo ao botão inicial.
        Qt.callLater(focarInicial)
    }
    // `escolha`: "confirmar", "alternativo" ou qualquer outra coisa (cancelar).
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
