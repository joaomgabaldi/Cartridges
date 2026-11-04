import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Dialogs

// A escolha do atalho de um jogo restaurado: o título é o nome do jogo e há uma linha por atalho candidato. Sem
// candidatos não abre: o modelo pede direto o seletor de arquivos (`procurarPedido`), que este modal cria sob demanda.
ModalDaRestauracao {
    id: dialogo
    objectName: "dialogoDaEscolhaDoAtalho"

    aberto: restauracao.escolhaAberta
    titulo: restauracao.escolha.nome || ""
    inicial: lista.vista.count > 0 ? lista.vista.itemAtIndex(0).botaoDaLinha : botaoProcurar
    onSaiu: restauracao.fecharEscolha()

    ModalDaRestauracao.Cartela {
        id: lista
        width: parent.width
        objetoDaLista: "listaDeCandidatos"
        alturaMaxima: 360
        model: restauracao.escolha.candidatos || []

        delegate: LinhaDeAcao {
            id: linha
            required property int index
            required property var modelData
            objectName: "candidato-" + index
            titulo: modelData.titulo
            subtitulo: modelData.subtitulo
            // Os testes e o controle acionam a linha pelo botão que a cobre.
            function click() { botaoDaLinha.click() }
            onAcionada: restauracao.usarAtalho(modelData.caminho)
        }
    }
    Item {
        width: parent.width
        height: botaoProcurar.height
        BotaoDoModal {
            id: botaoProcurar
            objectName: "botaoProcurarOutro"
            anchors.horizontalCenter: parent.horizontalCenter
            text: "Procurar outro atalho…"
            onClicked: restauracao.procurar()
        }
    }
    // O seletor nativo só existe depois do primeiro pedido, e nunca nos testes.
    Loader {
        id: carga
        active: false
        visible: false  // sem isto a `Column` soma um espaço vazio por Loader
        sourceComponent: FileDialog {
            nameFilters: ["Atalhos (*.lnk *.url)"]
            onAccepted: restauracao.procurado(selectedFile)
        }
        onLoaded: item.open()
    }
    Connections {
        target: restauracao
        function onProcurarPedido() { if (carga.item) carga.item.open(); else carga.active = true }
    }
}
