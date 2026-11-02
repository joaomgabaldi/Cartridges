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

    // `caption-heading dim-label`.
    Text {
        Layout.leftMargin: 3
        text: "Conquistas"
        textFormat: Text.PlainText
        color: Tema.textoSecundario
        font { family: Tema.fonte; pixelSize: Tema.legenda; weight: Tema.pesoForte }
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
        hoverEnabled: true
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
                    font { family: Tema.fonte; pixelSize: Tema.titulo4; weight: Tema.pesoTitulo4 }
                }
                Text {
                    objectName: "porcentagemDeConquistas"
                    text: bloco.dados.porcentagem || ""
                    textFormat: Text.PlainText
                    color: Tema.textoSecundario
                    font { family: Tema.fonte; pixelSize: Tema.corpo }
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

        // `button.card`: o cartão, mais 4% do texto ao passar e 8% ao apertar.
        background: Rectangle {
            radius: 12
            color: Tema.cartao
            Sombra { camadas: Tema.sombraCartao; raio: 12 }
            Rectangle {
                anchors.fill: parent
                radius: parent.radius
                color: cartao.down ? Tema.linhaPressionada : cartao.hovered ? Tema.linhaSobre : "transparent"
            }
            AnelDeFoco { ativo: cartao.visualFocus; raio: 12; afastamento: -2 }
        }
        Dica { texto: "Ver todas as conquistas"; ativa: cartao.hovered }
    }
}
