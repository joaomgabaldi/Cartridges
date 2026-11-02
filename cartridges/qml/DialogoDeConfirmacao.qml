import QtQuick

// Uma pergunta com dois botões (três, com `rotuloAlternativo`). O texto vai sempre em PlainText (nome de jogo e URL não são marcação).
// Esc vale como cancelar. Nenhum botão é destacado, salvo o destrutivo, em vermelho, como o `create_dialog` da `main`; o
// foco inicial vai ao primeiro, o de sair, como o AdwAlertDialog sem resposta padrão.
DialogoDeAlerta {
    id: dialogo

    property string rotuloConfirmar: "Confirmar"
    property string rotuloCancelar: "Cancelar"
    // Vazio = sem o terceiro botão. Com ele a ordem é Cancelar | confirmar | alternativo.
    property string rotuloAlternativo: ""
    property bool destrutivo: false
    // SUGGESTED da `main`: raro; a pergunta comum não destaca nada.
    property bool sugerido: false

    signal confirmado()
    signal cancelado()
    signal alternativo()

    function abrir() {
        aberto = true
        // Reaberto com outro conteúdo (a pilha da D72), o foco vai de novo ao botão inicial.
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
