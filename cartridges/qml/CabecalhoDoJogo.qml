import QtQuick
import QtQuick.Window

// O logo do jogo ou o nome, nunca os dois: a manchete do histórico de sessões e da lista de conquistas.
// `logo` é um arquivo `file:` (vazio = sem logo); o nome é de terceiros, sempre texto puro.
Item {
    id: cabecalho

    property string logo: ""
    property int larguraDoLogo: 0
    property string nome: ""
    property int tamanhoDoNome: Tema.titulo1  // .title-1
    // Os `objectName` dos dois, para os testes de cada diálogo.
    property string nomeDoLogo: "logoDoCabecalho"
    property string nomeDoTexto: "nomeDoCabecalho"

    implicitHeight: logoVisivel ? imagem.height : texto.implicitHeight
    readonly property bool logoVisivel: logo !== "" && imagem.status === Image.Ready

    Image {
        id: imagem
        objectName: cabecalho.nomeDoLogo
        visible: cabecalho.logoVisivel
        anchors.horizontalCenter: parent.horizontalCenter
        source: cabecalho.logo
        width: Math.min(cabecalho.larguraDoLogo, parent.width)
        height: implicitWidth > 0 ? width * implicitHeight / implicitWidth : 0
        fillMode: Image.PreserveAspectFit
        asynchronous: false
        sourceSize.width: width * Screen.devicePixelRatio
    }
    Text {
        id: texto
        objectName: cabecalho.nomeDoTexto
        visible: !cabecalho.logoVisivel
        width: parent.width
        text: cabecalho.nome
        textFormat: Text.PlainText
        wrapMode: Text.Wrap
        horizontalAlignment: Text.AlignHCenter
        color: Tema.texto
        font { family: Tema.fonte; pixelSize: cabecalho.tamanhoDoNome; weight: Tema.pesoTitulo1 }
    }
}
