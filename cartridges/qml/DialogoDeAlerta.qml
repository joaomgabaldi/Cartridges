import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// O Adw.AlertDialog: título .title-2 e corpo centrados, o que for declarado dentro abaixo deles, tudo rolando junto, e os
// botões embaixo, em partes iguais (empilhados quando não cabem). Largura natural entre 300 e 372 (medido na `main`);
// `largo` (`prefer-wide-layout`): se os botões não couberem lado a lado em 372, alarga até 600 em vez de empilhar.
// `respostas`: [{ id, rotulo, aparencia: "normal"|"sugestao"|"destrutivo", objeto }]. Os textos vão em PlainText.
MolduraDoDialogo {
    id: alerta

    property string titulo
    property string corpo
    property bool largo: false
    property var respostas: []
    // A resposta do Esc; o foco inicial vai à `respostaInicial` e, sem ela, à primeira, como o AdwAlertDialog.
    property string respostaDeEscape: ""
    property string respostaInicial: ""
    // Falso: quem usa manda no `aberto` (uma pergunta que continua aberta depois de respondida).
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

    // O que os botões pedem lado a lado, e o que o texto pede sem quebrar.
    readonly property real _larguraDosBotoes: {
        var maior = 0
        for (var i = 0; i < botoes.count; ++i)
            if (botoes.itemAt(i)) maior = Math.max(maior, botoes.itemAt(i).implicitWidth)
        return botoes.count * maior + 12 * (botoes.count - 1) + 48
    }
    readonly property real _larguraDoTexto: mensagem._temExtra ? 372 : Math.max(textoDoTitulo.implicitWidth, textoDoCorpo.implicitWidth) + 48

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
        interactive: contentHeight > height
        ScrollBar.vertical: BarraDeRolagem {}

        // .message-area: 32 em cima, 9 embaixo, 24 dos lados; 10 entre título e corpo; +8 antes do conteúdo extra.
        // Posições à mão: um Column escondido não se reorganiza, e o texto trocado antes de abrir deixaria a altura velha.
        Item {
            id: mensagem
            width: rolagem.width
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

    // .response-area: 12 em cima, 24 nos outros lados, 12 entre os botões. Empilhados, o primeiro fica embaixo.
    Item {
        id: area
        objectName: "respostasDoAlerta"
        Layout.fillWidth: true
        readonly property int quantos: botoes.count
        readonly property real larguraDeCada: quantos > 0 ? (width - 48 - 12 * (quantos - 1)) / quantos : 0
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
                // Setas e Tab circulam entre as respostas.
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
