import QtQuick
import QtQuick.Window

// A janela "Restaurando o backup" da abertura (D74): a moldura nativa, só com minimizar (arrastar e minimizar durante a
// espera; fechar, não). Num motor próprio, antes da biblioteca; `restaurando` vem do contexto. O `app` a fecha depois
// de a principal aparecer.
Window {
    id: raiz
    objectName: "janelaRestaurando"

    title: "Cartridges"
    width: 420
    minimumWidth: width
    maximumWidth: width
    // Ligadas ao conteúdo, e não ao `height`: o limite lido de volta travaria a janela na altura de antes.
    minimumHeight: conteudo.implicitHeight
    maximumHeight: conteudo.implicitHeight
    height: conteudo.implicitHeight
    color: Tema.fundo
    flags: Qt.Window | Qt.CustomizeWindowHint | Qt.WindowTitleHint | Qt.WindowMinimizeButtonHint
    visible: true

    onClosing: (fechar) => fechar.accepted = restaurando.podeFechar

    Column {
        id: conteudo
        x: 24
        width: parent.width - 48
        topPadding: 12
        bottomPadding: 24
        spacing: 12

        Text {
            objectName: "tituloDaRestauracao"
            width: parent.width
            text: "Restaurando o backup"
            textFormat: Text.PlainText
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.Wrap
            color: Tema.texto
            font { family: Tema.fonte; pixelSize: 20; weight: Font.DemiBold }
        }
        Text {
            objectName: "textoDaRestauracao"
            width: parent.width
            text: "O aplicativo será aberto quando a restauração terminar."
            textFormat: Text.PlainText
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.Wrap
            color: Tema.textoSecundario
            font { family: Tema.fonte; pixelSize: 14 }
        }
        Column {
            width: parent.width
            spacing: 6

            // A porcentagem num rótulo próprio: o texto da própria barra fica colado nela.
            Text {
                objectName: "porcentagemDaRestauracao"
                width: parent.width
                text: restaurando.porcentagem
                textFormat: Text.PlainText
                horizontalAlignment: Text.AlignHCenter
                color: Tema.textoSecundario
                font { family: Tema.fonte; pixelSize: 12; features: { "tnum": 1 } }
            }
            BarraDeProgresso {
                objectName: "barraDaRestauracao"
                width: parent.width
                value: restaurando.fracao
                Accessible.name: "Restaurando o backup"
            }
        }
    }
}
