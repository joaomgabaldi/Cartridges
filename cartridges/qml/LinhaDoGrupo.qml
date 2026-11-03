import QtQuick

// A base das linhas (AdwPreferencesRow em `list.boxed-list`): título e subtítulo à esquerda, o sufixo à direita, separador
// em cima, hover e opacidade de desabilitada. Sozinha, é a `Adw.ActionRow` sem ação. Medidas: 50 de altura mínima + 2 de
// respiro em cima e embaixo; 14 das laterais; título em 12 px e subtítulo em 10 px apagado, 3 entre eles.
//
// Quem herda declara o sufixo como filho, ancorado à direita com margem 14, põe `reservaADireita` (a largura do sufixo)
// e, se a linha inteira aciona, liga `sobre` e `pressionada`.
FocusScope {
    id: linha

    // `aparece` é a regra de cada linha (ex.: só com um interruptor ligado).
    // O grupo conta por ela, não pelo `visible` efetivo (que depende do próprio grupo: laço, D58).
    property bool aparece: true
    // Só as linhas das Preferências são buscáveis (`buscavel: true`); as dos assistentes e do editor ignoram a busca.
    // Nas Preferências use `aparece` para a regra da linha, nunca `visible` (um `visible:` de instância foge da contagem do grupo).
    property bool buscavel: false
    visible: aparece

    property string titulo
    property string subtitulo
    property int quebraDoSubtitulo: Text.Wrap
    // `.property`: o título pequeno e apagado, o valor (o subtítulo) no tamanho e na cor do texto.
    property bool propriedade: false
    property real alturaMinima: 50
    property real reservaADireita: 0
    property bool sobre: false
    property bool pressionada: false
    property bool foco: false
    // O título e o subtítulo somem da base (a `LinhaDeBotao` e a `LinhaDeTexto` desenham os seus).
    property bool comTextos: true
    property alias textos: colunaDeTextos

    // O grupo com `separada`: cada linha é um cartão.
    readonly property bool separada: parent && parent.separada === true
    readonly property bool primeira: y <= 0
    readonly property bool ultima: parent ? y + height >= parent.height - 1 : true
    readonly property real raioDaLinha: separada || (primeira && ultima) ? 12 : 0
    readonly property int _separador: !separada && !primeira ? 1 : 0

    width: parent ? parent.width : implicitWidth
    implicitHeight: Math.max(alturaMinima, comTextos ? colunaDeTextos.implicitHeight + 12 : 0) + 4 + _separador
    // disabled-opacity: a linha e tudo nela.
    opacity: enabled ? 1 : Tema.opacidadeDesabilitado

    Rectangle {
        anchors.fill: parent
        visible: linha.separada
        radius: 12
        color: Tema.cartao
        Sombra { camadas: Tema.sombraCartao; raio: 12 }
    }
    Rectangle {
        anchors { fill: parent; topMargin: linha._separador }
        topLeftRadius: linha.separada || linha.primeira ? 12 : 0
        topRightRadius: topLeftRadius
        bottomLeftRadius: linha.separada || linha.ultima ? 12 : 0
        bottomRightRadius: bottomLeftRadius
        color: linha.pressionada ? Tema.linhaPressionada : linha.sobre ? Tema.linhaSobre : "transparent"
    }
    Rectangle {
        width: parent.width
        height: 1
        color: Tema.sombraDoCartao
        visible: linha._separador > 0
    }

    Column {
        id: colunaDeTextos
        visible: linha.comTextos
        anchors {
            left: parent.left; leftMargin: 14
            right: parent.right; rightMargin: 14 + (linha.reservaADireita > 0 ? linha.reservaADireita + 12 : 0)
            verticalCenter: parent.verticalCenter; verticalCenterOffset: linha._separador / 2
        }
        spacing: 3
        Text {
            objectName: linha.objectName + "Titulo"
            width: parent.width
            text: linha.titulo
            textFormat: Text.PlainText
            wrapMode: Text.Wrap
            lineHeightMode: Text.FixedHeight
            lineHeight: linha.propriedade ? Tema.alturaDaLegenda : Tema.alturaDoCorpo
            color: linha.propriedade ? Tema.textoSecundario : Tema.texto
            font { family: Tema.fonte; pixelSize: linha.propriedade ? Tema.legenda : Tema.corpo }
        }
        Text {
            objectName: linha.objectName + "Subtitulo"
            width: parent.width
            visible: text !== ""
            text: linha.subtitulo
            textFormat: Text.PlainText
            wrapMode: linha.quebraDoSubtitulo
            lineHeightMode: Text.FixedHeight
            lineHeight: linha.propriedade ? Tema.alturaDoCorpo : Tema.alturaDaLegenda
            color: linha.propriedade ? Tema.texto : Tema.textoSecundario
            font { family: Tema.fonte; pixelSize: linha.propriedade ? Tema.corpo : Tema.legenda }
        }
    }

    AnelDeFoco { ativo: linha.foco; raio: linha.raioDaLinha; afastamento: -2 }
}
