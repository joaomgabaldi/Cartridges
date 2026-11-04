import QtQuick
import QtQuick.Dialogs

// "Pasta de atalhos": obrigatória, sem Esc nem X; só sai com a pasta escolhida. O seletor nativo é criado só ao clicar.
// Só desenha: o texto e a gravação são do `restauracao`.
ModalDaRestauracao {
    id: dialogo
    objectName: "dialogoDaPastaDeAtalhos"

    aberto: restauracao.pedindoPasta
    titulo: "Pasta de atalhos"
    fechavel: false
    inicial: botao

    Text {
        objectName: "textoDaPasta"
        width: parent.width
        text: restauracao.textoDaPasta
        textFormat: Text.PlainText
        wrapMode: Text.Wrap
        horizontalAlignment: Text.AlignHCenter
        color: Tema.texto
        font { family: Tema.fonte; pixelSize: Tema.corpo }
    }
    Item {
        width: parent.width
        height: botao.height
        BotaoDoModal {
            id: botao
            objectName: "botaoEscolherPasta"
            anchors.horizontalCenter: parent.horizontalCenter
            text: "Escolher pasta…"
            destaque: true
            onClicked: if (carga.item) carga.item.open(); else carga.active = true
        }
    }
    Loader {
        id: carga
        active: false
        visible: false  // sem isto a `Column` soma um espaço vazio por Loader
        sourceComponent: FolderDialog {
            onAccepted: restauracao.escolherPasta(selectedFolder)
        }
        onLoaded: item.open()
    }
}
