import QtQuick

// O logo de um jogo do carrossel (ou o nome, sem logo). Anda entre as posições do Big Picture e, num passo, acompanha a capa dele.
Item {
    id: logo
    objectName: emCentro ? "logoDoBigPicture" : "logoVizinhoDoBigPicture"

    property var jogo: null
    property bool emCentro: true
    property real deslocamento: 0  // a distância horizontal da capa dele ao centro; não anima: já vem do passo das capas
    property string posicao: "alto"  // "alto", "coluna" ou "relogio"
    property bool animar: true
    // A faixa livre acima da capa central, que varia com a resolução: no alto o logo ocupa 60% dela, mais perto da capa do que do topo.
    property real espacoNoAlto: 137
    property real alturaNaColuna: 72
    property real alturaDecodificada: 110  // a mesma do preparo dos vizinhos: o cache do Qt Quick só acerta com o mesmo `sourceSize`

    property bool emPe: false  // monitor em pé: na "coluna" o logo fica centrado sob a capa, e não à direita dela
    readonly property bool naColuna: posicao === "coluna"
    // A altura anda junto com x e y; a imagem é decodificada uma vez, na maior (`sourceSize` fixo).
    property real altura: naColuna ? alturaNaColuna : posicao === "alto" ? espacoNoAlto * 0.6 : 110
    Behavior on altura { enabled: logo.animar; NumberAnimation { duration: 800; easing.type: Easing.OutCubic } }
    // O `detalhes` traz o logo recém-baixado do jogo central; o resto vem do disco. Sem jogo, nada é lido nem decodificado.
    readonly property string logoDoJogo: !jogo ? ""
        : detalhes.jogoId === jogo.jogoId && detalhes.logo !== "" ? detalhes.logo : bigPicture.logoDe(jogo.jogoId)

    readonly property real larguraMaxima: parent ? parent.width * (naColuna && !emPe ? 0.5 : 0.8) : Infinity
    width: Math.min(conteudo.width, larguraMaxima)
    height: altura
    // Só o caminho até a coluna anima: cada logo tem uma largura, e recentrar com animação faria todos deslizarem para o mesmo lado.
    property real fracaoDaColuna: naColuna && !emPe ? 1 : 0
    Behavior on fracaoDaColuna { enabled: logo.animar; NumberAnimation { duration: 800; easing.type: Easing.OutCubic } }
    x: !parent ? 0 : (parent.width - width) / 2 + (parent.width * 0.42 - (parent.width - width) / 2) * fracaoDaColuna
    y: !parent ? 0 : posicao === "alto" ? espacoNoAlto * 0.25 : posicao === "relogio" ? parent.height * 0.18 : parent.height * (emPe ? 0.50 : 0.14)
    Behavior on y { enabled: logo.animar; NumberAnimation { duration: 800; easing.type: Easing.OutCubic } }
    transform: Translate { x: logo.deslocamento }

    Item {
        id: conteudo
        width: imagem.visible ? imagem.width : texto.width
        height: parent.height
        Image {
            id: imagem
            objectName: logo.emCentro ? "logoDoJogoNoBigPicture" : ""
            visible: status === Image.Ready
            source: logo.logoDoJogo
            height: logo.altura
            // Um logo largo numa tela em pé encolhe para caber (o `PreserveAspectFit` o centra na altura) em vez de vazar.
            width: implicitHeight > 0 ? Math.min(height * implicitWidth / implicitHeight, logo.larguraMaxima) : 0
            fillMode: Image.PreserveAspectFit
            asynchronous: true  // arquivo em disco, sem provedor Python: segurar o direcional não trava o passo
            sourceSize.height: logo.alturaDecodificada
        }
        Text {
            id: texto
            objectName: logo.emCentro ? "nomeDoLogoDoBigPicture" : "nomeDoLogoVizinhoDoBigPicture"
            visible: text !== "" && (logo.logoDoJogo === "" || imagem.status === Image.Error)
            width: Math.min(implicitWidth, logo.parent ? logo.parent.width * 0.8 : implicitWidth)
            anchors.verticalCenter: parent.verticalCenter
            text: logo.jogo ? logo.jogo.nome : ""
            textFormat: Text.PlainText
            color: "white"
            elide: Text.ElideRight
            font { family: Tema.fonte; pixelSize: Tema.titulo1; weight: Tema.pesoTitulo1 }
        }
    }
}
