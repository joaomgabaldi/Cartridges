import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// O cartão de conquistas da página do jogo, logo abaixo do HowLongToBeat: as duas respondem a "quanto do jogo já foi
// feito", uma em horas, a outra em metas. Só desenha `conquistasDoJogo.pagina`; o clique abre a lista completa.
ColumnLayout {
    id: bloco
    objectName: "blocoDeConquistas"

    // O botão-cartão, para a página incluí-lo na navegação por setas e pelo controle.
    readonly property alias botao: cartao
    readonly property var dados: conquistasDoJogo.pagina

    visible: dados.visivel === true
    spacing: 6

    Text {
        Layout.leftMargin: 3
        text: "Conquistas"
        textFormat: Text.PlainText
        color: Tema.textoSecundario
        font { family: Tema.fonte; pixelSize: 12; weight: Font.DemiBold }
    }

    Button {
        id: cartao
        objectName: "cartaoDeConquistas"
        focusPolicy: Qt.StrongFocus
        leftPadding: 16
        rightPadding: 16
        topPadding: 12
        bottomPadding: 12
        implicitWidth: Math.max(260, leftPadding + contentItem.implicitWidth + rightPadding)
        Accessible.name: "Conquistas, " + (bloco.dados.contagem || "")
        ToolTip.visible: hovered
        ToolTip.text: "Ver todas as conquistas"
        ToolTip.delay: 600
        // O Enter também abre (o Espaço e o clique já são do botão).
        Keys.onReturnPressed: clicked()
        Keys.onEnterPressed: clicked()
        onClicked: conquistasDoJogo.abrir(detalhes.jogoId)

        contentItem: ColumnLayout {
            spacing: 8

            RowLayout {
                Layout.fillWidth: true
                Text {
                    objectName: "contagemDeConquistas"
                    Layout.fillWidth: true
                    text: bloco.dados.contagem || ""
                    textFormat: Text.PlainText
                    color: Tema.texto
                    font { family: Tema.fonte; pixelSize: 17; weight: Font.Bold }
                }
                Text {
                    objectName: "porcentagemDeConquistas"
                    text: bloco.dados.porcentagem || ""
                    textFormat: Text.PlainText
                    color: Tema.textoSecundario
                    font { family: Tema.fonte; pixelSize: 14 }
                }
            }

            BarraDeProgresso {
                objectName: "barraDeConquistas"
                Layout.fillWidth: true
                value: bloco.dados.fracao || 0
            }

            RowLayout {
                objectName: "iconesDeConquistas"
                visible: (bloco.dados.icones || []).length > 0
                spacing: 6
                Repeater {
                    model: bloco.dados.icones || []
                    delegate: IconeDaConquista {
                        required property var modelData
                        tamanho: 32
                        url: modelData.url
                        cinza: modelData.cinza
                        oculta: modelData.oculta
                    }
                }
                Text {
                    objectName: "restoDeConquistas"
                    visible: text !== ""
                    text: bloco.dados.resto || ""
                    textFormat: Text.PlainText
                    color: Tema.textoSecundario
                    font { family: Tema.fonte; pixelSize: 14 }
                }
            }
        }

        background: Rectangle {
            radius: 12
            color: cartao.down ? Tema.pressionado : cartao.hovered ? Tema.botaoSobre : Tema.superficie
            border { width: cartao.visualFocus ? 2 : 1; color: cartao.visualFocus ? Tema.destaque : Tema.borda }
        }
    }
}
