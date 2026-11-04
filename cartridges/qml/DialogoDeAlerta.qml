import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Diálogo de alerta: título e corpo centrados, botões embaixo em partes iguais (empilhados quando não cabem).
// `respostas`: [{ id, rotulo, aparencia: "normal"|"sugestao"|"destrutivo", objeto }]. Textos em PlainText.
MolduraDoDialogo {
    id: alerta

    property string titulo
    property string corpo
    property bool largo: false
    property var respostas: []
    property string respostaDeEscape: ""
    property string respostaInicial: ""
    property bool fechaAoResponder: true
    property alias objetoDoTitulo: textoDoTitulo.objectName
    property alias objetoDoCorpo: textoDoCorpo.objectName
    default property alias extra: colunaExtra.data

    signal respondido(string resposta)

    function botaoDe(id) {
        for (var i = 0; i < botoes.count; ++i)
            if (botoes.itemAt(i) && botoes.itemAt(i).modelData.id === id) return botoes.itemAt(i)
        return botoes.count > 0 ? botoes.itemAt(0) : null
    }
    function responder(id) {
        if (!aberto) return
        if (fechaAoResponder) aberto = false
        respondido(id)
    }

    readonly property real _larguraDosBotoes: {
        var maior = 0
        for (var i = 0; i < botoes.count; ++i)
            if (botoes.itemAt(i)) maior = Math.max(maior, botoes.itemAt(i).implicitWidth)
        return botoes.count * maior + 12 * (botoes.count - 1) + 48
    }
    // A largura que cada texto pediria sem quebrar (os gêmeos escondidos): a do `Text` de verdade segue a do cartão.
    readonly property real _larguraDoTexto: mensagem._temExtra ? 372 : Math.max(gemeoDoTitulo.implicitWidth, gemeoDoCorpo.implicitWidth) + 48
    Text { id: gemeoDoTitulo; visible: false; text: alerta.titulo; textFormat: Text.PlainText; font: textoDoTitulo.font }
    Text { id: gemeoDoCorpo; visible: false; text: alerta.corpo; textFormat: Text.PlainText; font: textoDoCorpo.font }

    raio: 18
    cor: Tema.dialogo
    podeSerFolha: false
    // Pela soma, e não pelo `implicitHeight` do layout, que não desce quando o texto muda com o diálogo escondido.
    altura: mensagem.implicitHeight + area.implicitHeight
    largura: largo && _larguraDosBotoes > 372 ? Math.min(600, _larguraDosBotoes)
        : Math.max(300, Math.min(372, Math.max(_larguraDoTexto, _larguraDosBotoes)))
    nomeAcessivel: titulo
    focoInicial: botoes.count > 0 ? botaoDe(respostaInicial) : null
    onFecharPedido: responder(respostaDeEscape)

    Flickable {
        id: rolagem
        objectName: "rolagemDoAlerta"
        Layout.fillWidth: true
        Layout.fillHeight: true
        Layout.preferredHeight: mensagem.implicitHeight
        contentWidth: width
        contentHeight: mensagem.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        RolagemDaRoda { alvo: rolagem }
        interactive: contentHeight > height
        ScrollBar.vertical: BarraDeRolagem {}

        // Posições à mão: um Column escondido não se reorganiza, e o texto trocado antes de abrir deixaria a altura
        // velha.
        Item {
            id: mensagem
            // A largura do cartão, e não a da `rolagem`: a do layout muda depois da altura pedida, que depende deste
            // texto (laço).
            width: alerta.cartao.width
            // Pelo conteúdo, nunca pelo `visible`: com o diálogo escondido ele é sempre falso.
            readonly property real _fimDoTexto: alerta.corpo !== "" ? textoDoCorpo.y + textoDoCorpo.height : textoDoTitulo.y + textoDoTitulo.height
            readonly property bool _temExtra: colunaExtra.implicitHeight > colunaExtra.topPadding
            implicitHeight: _fimDoTexto + (_temExtra ? 10 + colunaExtra.implicitHeight : 0) + 9

            Text {
                id: textoDoTitulo
                objectName: "tituloDoDialogo"
                x: 24
                y: 32
                width: parent.width - 48
                text: alerta.titulo
                textFormat: Text.PlainText
                wrapMode: Text.Wrap
                horizontalAlignment: Text.AlignHCenter
                lineHeightMode: Text.FixedHeight
                lineHeight: Tema.alturaDoTitulo2
                color: Tema.texto
                font { family: Tema.fonte; pixelSize: Tema.titulo2; weight: Tema.pesoTitulo2 }
                Accessible.role: Accessible.Heading
                Accessible.name: text
            }
            Text {
                id: textoDoCorpo
                objectName: "corpoDoDialogo"
                x: 24
                y: textoDoTitulo.y + textoDoTitulo.height + 10
                width: parent.width - 48
                visible: text !== ""
                text: alerta.corpo
                textFormat: Text.PlainText
                wrapMode: Text.Wrap
                horizontalAlignment: Text.AlignHCenter
                lineHeightMode: Text.FixedHeight
                lineHeight: Tema.alturaDoCorpo
                color: Tema.texto
                font { family: Tema.fonte; pixelSize: Tema.corpo }
            }
            Column {
                id: colunaExtra
                x: 24
                y: mensagem._fimDoTexto + 10
                width: parent.width - 48
                spacing: 6
                topPadding: 8
            }
        }
    }

    Item {
        id: area
        objectName: "respostasDoAlerta"
        Layout.fillWidth: true
        readonly property int quantos: botoes.count
        readonly property real larguraDeCada: quantos > 0 ? (alerta.cartao.width - 48 - 12 * (quantos - 1)) / quantos : 0
        readonly property bool empilhado: {
            for (var i = 0; i < botoes.count; ++i)
                if (botoes.itemAt(i) && botoes.itemAt(i).implicitWidth > larguraDeCada) return true
            return false
        }
        implicitHeight: 12 + 24 + (empilhado ? quantos * 44 + (quantos - 1) * 12 : 44)

        Repeater {
            id: botoes
            model: alerta.respostas
            delegate: Botao {
                id: botao
                required property var modelData
                required property int index
                objectName: modelData.objeto || ""
                text: modelData.rotulo
                estilo: modelData.aparencia || "normal"
                x: area.empilhado ? 24 : 24 + index * (width + 12)
                y: 12 + (area.empilhado ? (area.quantos - 1 - index) * 56 : 0)
                width: area.empilhado ? area.width - 48 : area.larguraDeCada
                height: 44
                implicitWidth: contentItem.implicitWidth + 40
                leftPadding: 20
                rightPadding: 20
                raio: 12
                cortarRotulo: true
                readonly property Item proximo: botoes.itemAt((index + 1) % area.quantos)
                readonly property Item anterior: botoes.itemAt((index + area.quantos - 1) % area.quantos)
                Keys.onRightPressed: proximo.forceActiveFocus(Qt.TabFocusReason)
                Keys.onTabPressed: proximo.forceActiveFocus(Qt.TabFocusReason)
                Keys.onLeftPressed: anterior.forceActiveFocus(Qt.BacktabFocusReason)
                Keys.onBacktabPressed: anterior.forceActiveFocus(Qt.BacktabFocusReason)
                onClicked: alerta.responder(modelData.id)
            }
        }
    }
}
