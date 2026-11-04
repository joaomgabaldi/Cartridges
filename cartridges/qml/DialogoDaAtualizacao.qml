import QtQuick
import QtQuick.Controls.Basic

// A pergunta da versão nova e o download, na camada dos avisos. As notas vão em RichText porque o `notes_to_markup` as
// entrega só com <b>, <tt> e <br>; o resto é PlainText.
// Atualizar destacado, mas não como padrão: a caixa aparece sem ser pedida, e um Enter perdido (digitando na busca) não
// pode começar o download.
DialogoDeAlerta {
    id: dialogo

    property QtObject atualizador
    readonly property var pergunta: atualizador ? atualizador.pergunta : ({})
    readonly property bool baixando: !!atualizador && atualizador.baixando
    readonly property bool perguntando: !baixando && pergunta.versao !== undefined

    function recusar() {
        if (baixando) atualizador.cancelar()
        else if (perguntando) atualizador.responder(false)
    }

    aberto: baixando || perguntando
    fechaAoResponder: false
    objetoDoTitulo: "tituloDaAtualizacao"
    objetoDoCorpo: "corpoDaAtualizacao"
    largo: true
    titulo: baixando ? "Baixando atualização…" : "Nova versão disponível: " + (pergunta.versao || "")
    corpo: baixando ? "" : "Deseja baixar e instalar a atualização agora? O aplicativo será fechado durante a instalação."
    respostas: baixando
        ? [{ id: "cancelar", rotulo: "Cancelar", objeto: "botaoCancelarAtualizacao" }]
        : [{ id: "agora-nao", rotulo: "Agora não", objeto: "botaoAgoraNao" },
           { id: "atualizar", rotulo: "Atualizar", objeto: "botaoAtualizar", aparencia: "sugestao" }]
    respostaDeEscape: baixando ? "cancelar" : "agora-nao"
    onRespondido: resposta => {
        if (resposta === "atualizar") atualizador.responder(true)
        else recusar()
    }
    onBaixandoChanged: if (aberto) Qt.callLater(focarInicial)

    Flickable {
        id: notasRolagem
        width: parent.width
        height: Math.min(notas.implicitHeight, 360)
        visible: !dialogo.baixando && notas.text !== ""
        contentHeight: notas.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        RolagemDaRoda { alvo: notasRolagem }
        ScrollBar.vertical: BarraDeRolagem {}

        Text {
            id: notas
            objectName: "notasDaAtualizacao"
            width: parent.width
            text: dialogo.pergunta.notas || ""
            textFormat: Text.RichText
            wrapMode: Text.Wrap
            color: Tema.texto
            font { family: Tema.fonte; pixelSize: Tema.corpo }
        }
    }

    Column {
        width: parent.width
        spacing: 6
        visible: dialogo.baixando

        Text {
            objectName: "porcentagemDaAtualizacao"
            anchors.horizontalCenter: parent.horizontalCenter
            text: Math.round((dialogo.atualizador ? dialogo.atualizador.progresso : 0) * 100) + " %"
            textFormat: Text.PlainText
            color: Tema.textoSecundario
            font { family: Tema.fonte; pixelSize: Tema.legenda }
        }
        BarraDeProgresso {
            objectName: "barraDaAtualizacao"
            width: parent.width
            value: dialogo.atualizador ? dialogo.atualizador.progresso : 0
            corDaTrilha: Tema.botaoSobre
        }
    }
}
