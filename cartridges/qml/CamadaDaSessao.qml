import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// A tela da sessão (D49): cobre a janela inteira, barra de título incluída, enquanto o jogo roda.
// Lê só o `sessao` (cartridges/modelos/sessao.py); o texto do jogo é sempre texto puro.
Rectangle {
    id: raiz
    objectName: "camadaDaSessao"
    color: "#EB000000"  // rgba(0, 0, 0, 0.92), como na `main`

    // Quem está embaixo não recebe mouse nem roda.
    MouseArea {
        anchors.fill: parent
        hoverEnabled: true
        acceptedButtons: Qt.AllButtons
        onWheel: wheel => wheel.accepted = true
    }

    // Esconder fecha o balão aberto (e é esse fechamento que grava a anotação), como na `main`.
    onVisibleChanged: if (visible) botaoTerminei.forceActiveFocus(Qt.TabFocusReason); else balao.close()

    // A coluna do jogo e, abaixo dela, o cartão de conquistas, que pode ser mais largo que ela.
    ColumnLayout {
        objectName: "colunaDaSessao"
        anchors.centerIn: parent
        spacing: 18

        ColumnLayout {
            objectName: "colunaDoJogo"
            Layout.alignment: Qt.AlignHCenter
            Layout.fillWidth: false  // um layout dentro de outro estica por padrão: aqui fica nos 640
            Layout.preferredWidth: Math.min(raiz.width - 48, 640)
            spacing: 18

            // O logo (640×140 no máximo) ou o nome, nunca os dois.
            Item {
                Layout.fillWidth: true
                Layout.bottomMargin: 12
                implicitHeight: logoVisivel ? logo.height : nome.implicitHeight
                readonly property bool logoVisivel: sessao.logo !== "" && logo.status === Image.Ready

                Image {
                    id: logo
                    objectName: "logoDaSessao"
                    visible: parent.logoVisivel
                    anchors.horizontalCenter: parent.horizontalCenter
                    source: sessao.logo
                    width: Math.min(sessao.larguraDoLogo, parent.width)
                    height: implicitWidth > 0 ? width * implicitHeight / implicitWidth : 0
                    fillMode: Image.PreserveAspectFit
                    asynchronous: false
                    sourceSize.width: width * Screen.devicePixelRatio
                }
                Text {
                    id: nome
                    objectName: "nomeDaSessao"
                    visible: !parent.logoVisivel
                    width: parent.width
                    text: sessao.nome
                    textFormat: Text.PlainText
                    wrapMode: Text.Wrap
                    horizontalAlignment: Text.AlignHCenter
                    color: "white"
                    font { family: Tema.fonte; pixelSize: 28; weight: Font.Bold }
                }
            }

            Text {
                objectName: "relogioDaSessao"
                Layout.alignment: Qt.AlignHCenter
                visible: sessao.relogioVisivel
                text: sessao.relogio
                textFormat: Text.PlainText
                color: "white"
                font { family: Tema.fonte; pixelSize: 40; weight: Font.Light; features: { "tnum": 1 } }
            }

            Button {
                id: botaoTerminei
                objectName: "botaoJaTerminei"
                Layout.alignment: Qt.AlignHCenter
                focusPolicy: Qt.StrongFocus
                text: "Já terminei de jogar"
                implicitHeight: 44
                leftPadding: 28
                rightPadding: 28
                onClicked: sessao.terminar()
                contentItem: Text {
                    text: botaoTerminei.text
                    textFormat: Text.PlainText
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    color: "white"
                    font { family: Tema.fonte; pixelSize: 16; weight: Font.DemiBold }
                }
                background: Rectangle {
                    radius: height / 2
                    color: Tema.destaque
                    opacity: botaoTerminei.down ? 0.7 : botaoTerminei.hovered ? 0.85 : 1
                    border { width: botaoTerminei.visualFocus ? 2 : 0; color: "white" }
                }
            }

            Button {
                id: botaoAnotacao
                objectName: "botaoAnotacaoDaSessao"
                Layout.alignment: Qt.AlignHCenter
                focusPolicy: Qt.StrongFocus
                text: "Onde eu parei"
                implicitHeight: 34
                leftPadding: 12
                rightPadding: 12
                Accessible.description: ToolTip.text
                ToolTip.visible: hovered
                ToolTip.text: "Anotar onde você parou neste jogo"
                ToolTip.delay: 600
                onClicked: balao.opened ? balao.close() : balao.open()
                contentItem: Text {
                    text: botaoAnotacao.text
                    textFormat: Text.PlainText
                    verticalAlignment: Text.AlignVCenter
                    color: "white"
                    font { family: Tema.fonte; pixelSize: 14 }
                }
                background: Rectangle {
                    radius: 6
                    color: botaoAnotacao.down ? "#40ffffff" : botaoAnotacao.hovered ? "#26ffffff" : "transparent"
                    border { width: botaoAnotacao.visualFocus ? 2 : 0; color: "white" }
                }
                BalaoDaAnotacao {
                    id: balao
                    objectName: "balaoDaSessao"
                    y: parent.height + 4
                    texto: sessao.anotacao
                    onGravar: texto => sessao.gravarAnotacao(texto)
                }
            }
        }

        // Escondido sem conquistas, e aí não ocupa espaço: a tela fica como era.
        ConquistasDaSessao {
            Layout.alignment: Qt.AlignHCenter
            Layout.topMargin: 12
            larguraMaxima: raiz.width - 48
            visible: conquistasDoJogo.sessao.visivel === true
        }
    }
}
