import QtQuick

// O logo do jogo central (ou o nome, sem logo). Anda entre as posições do Big Picture; a troca de jogo é só um fade.
Item {
    id: logo
    objectName: "logoDoBigPicture"

    property string posicao: "alto"  // "alto", "coluna" ou "relogio"
    property bool animar: true

    readonly property bool naColuna: posicao === "coluna"
    // A altura anda junto com x e y; a imagem é decodificada uma vez, na maior (`sourceSize` fixo).
    property real altura: naColuna ? 72 : 110
    Behavior on altura { enabled: logo.animar; NumberAnimation { duration: 800; easing.type: Easing.OutCubic } }
    // O que está na tela: copia o jogo só depois do fade de saída.
    property string logoExibido: ""
    property string nomeExibido: ""
    // Escondido, nada é lido nem decodificado: a página de detalhes do modo normal também mexe em `detalhes`.
    readonly property string logoDoJogo: bigPicture.visivel ? detalhes.logo : ""
    readonly property string nomeDoJogo: bigPicture.visivel ? detalhes.nome : ""

    width: Math.min(conteudo.width, parent ? parent.width * (naColuna ? 0.5 : 0.8) : conteudo.width)
    height: altura
    x: posicao === "coluna" ? (parent ? parent.width * 0.42 : 0) : (parent ? (parent.width - width) / 2 : 0)
    y: !parent ? 0 : posicao === "alto" ? parent.height * 0.05 : posicao === "relogio" ? parent.height * 0.18 : parent.height * 0.12
    Behavior on x { enabled: logo.animar; NumberAnimation { duration: 800; easing.type: Easing.OutCubic } }
    Behavior on y { enabled: logo.animar; NumberAnimation { duration: 800; easing.type: Easing.OutCubic } }

    function copiar() {
        logoExibido = logoDoJogo
        nomeExibido = nomeDoJogo
    }
    Component.onCompleted: copiar()
    onLogoDoJogoChanged: trocar()
    onNomeDoJogoChanged: trocar()
    function trocar() {
        if (logoDoJogo === logoExibido && nomeDoJogo === nomeExibido) return
        if (animar && visible) troca.restart()
        else { troca.stop(); copiar(); conteudo.opacity = 1 }
    }
    SequentialAnimation {
        id: troca
        NumberAnimation { target: conteudo; property: "opacity"; to: 0; duration: 120 }
        ScriptAction { script: logo.copiar() }
        NumberAnimation { target: conteudo; property: "opacity"; to: 1; duration: 220 }
    }

    Item {
        id: conteudo
        width: imagem.visible ? imagem.width : texto.width
        height: parent.height
        Image {
            id: imagem
            objectName: "logoDoJogoNoBigPicture"
            visible: logo.logoExibido !== "" && status === Image.Ready
            source: logo.logoExibido
            height: logo.altura
            width: implicitHeight > 0 ? height * implicitWidth / implicitHeight : 0
            fillMode: Image.PreserveAspectFit
            asynchronous: false
            sourceSize.height: 110 * Screen.devicePixelRatio
        }
        Text {
            id: texto
            objectName: "nomeDoLogoDoBigPicture"
            visible: !imagem.visible && text !== ""
            width: Math.min(implicitWidth, logo.parent ? logo.parent.width * 0.8 : implicitWidth)
            anchors.verticalCenter: parent.verticalCenter
            text: logo.nomeExibido
            textFormat: Text.PlainText
            color: "white"
            elide: Text.ElideRight
            font { family: Tema.fonte; pixelSize: Tema.titulo1; weight: Tema.pesoTitulo1 }
        }
    }
}
