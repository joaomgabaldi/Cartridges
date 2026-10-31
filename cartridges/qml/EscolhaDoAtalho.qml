import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Dialogs

// A escolha do atalho de um jogo restaurado: o título é o nome do jogo e há uma linha por atalho candidato (D81). Sem
// candidatos não abre: o modelo pede direto o seletor de arquivos (`procurarPedido`), que este modal cria sob demanda.
ModalDaRestauracao {
    id: dialogo
    objectName: "dialogoDaEscolhaDoAtalho"

    aberto: restauracao.escolhaAberta
    titulo: restauracao.escolha.nome || ""
    inicial: lista.count > 0 ? lista.itemAtIndex(0) : botaoProcurar
    onSaiu: restauracao.fecharEscolha()

    ListView {
        id: lista
        objectName: "listaDeCandidatos"
        width: parent.width
        height: Math.min(contentHeight, 360)
        model: restauracao.escolha.candidatos || []
        spacing: 4
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: BarraDeRolagem {}

        delegate: Button {
            id: linha
            required property int index
            required property var modelData
            objectName: "candidato-" + index
            width: ListView.view.width
            implicitHeight: 56
            focusPolicy: Qt.StrongFocus
            leftPadding: 16
            rightPadding: 16
            Accessible.name: modelData.titulo + ", " + modelData.subtitulo
            Keys.onReturnPressed: click()
            Keys.onEnterPressed: click()
            onClicked: restauracao.usarAtalho(modelData.caminho)

            contentItem: Column {
                anchors.verticalCenter: parent.verticalCenter
                spacing: 2
                Text {
                    objectName: "tituloDoCandidato"
                    width: parent.width
                    text: linha.modelData.titulo
                    textFormat: Text.PlainText
                    elide: Text.ElideRight
                    color: Tema.texto
                    font { family: Tema.fonte; pixelSize: 14 }
                }
                Text {
                    objectName: "subtituloDoCandidato"
                    width: parent.width
                    text: linha.modelData.subtitulo
                    textFormat: Text.PlainText
                    elide: Text.ElideRight
                    color: Tema.textoSecundario
                    font { family: Tema.fonte; pixelSize: 12 }
                }
            }
            background: Rectangle {
                radius: 6
                color: linha.down ? Tema.pressionado : linha.hovered ? Tema.botaoSobre : Tema.superficie
                border { width: linha.visualFocus ? 2 : 1; color: linha.visualFocus ? Tema.texto : Tema.borda }
            }
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
