import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import QtQuick.Window

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

    // O anel de foco só vem se o teclado (ou o controle) já estava em uso quando o jogo foi aberto: na `main` o `grab_focus`
    // depois de um clique deixa o `focus-visible` falso. Lembrado enquanto a camada está escondida, porque ao abrir a página
    // de trás já foi desabilitada e o foco dela já saiu.
    property bool _tecladoEmUso: false
    Connections {
        target: raiz.Window.window
        enabled: !raiz.visible
        function onActiveFocusItemChanged() {
            const foco = raiz.Window.window.activeFocusItem
            if (!foco || foco === raiz.Window.window.contentItem) return
            // A grade sabe se o último gesto foi do teclado (`porTeclado`); os controles, pelo `visualFocus`.
            let teclado = false
            for (let p = foco; p; p = p.parent)
                if (p.porTeclado === true || p.visualFocus === true) { teclado = true; break }
            raiz._tecladoEmUso = teclado
        }
    }

    // Esconder fecha o balão aberto (e é esse fechamento que grava a anotação), como na `main`.
    onVisibleChanged: {
        if (visible) {
            botaoTerminei.forceActiveFocus(_tecladoEmUso ? Qt.TabFocusReason : Qt.OtherFocusReason)
        } else {
            balao.close()
            _tecladoEmUso = false
        }
    }

    // A coluna do jogo e, abaixo dela, o cartão de conquistas, que pode ser mais largo que ela.
    ColumnLayout {
        objectName: "colunaDaSessao"
        anchors.centerIn: parent
        spacing: 18

        // A largura natural do nome, até a da janela menos 48: só o logo é limitado a 640 (`window.py:79-80`).
        ColumnLayout {
            objectName: "colunaDoJogo"
            Layout.alignment: Qt.AlignHCenter
            Layout.fillWidth: false  // um layout dentro de outro estica por padrão
            Layout.maximumWidth: raiz.width - 48
            spacing: 18

            // O logo (640×140 no máximo) ou o nome, nunca os dois.
            Item {
                Layout.fillWidth: true
                Layout.bottomMargin: 12
                implicitWidth: logoVisivel ? Math.min(sessao.larguraDoLogo, 640) : medida.advanceWidth
                implicitHeight: logoVisivel ? logo.height : nome.implicitHeight
                readonly property bool logoVisivel: sessao.logo !== "" && logo.status === Image.Ready

                TextMetrics { id: medida; font: nome.font; text: sessao.nome }
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
                    font { family: Tema.fonte; pixelSize: Tema.titulo1; weight: Tema.pesoTitulo1 }  // .title-1
                }
            }

            Text {
                objectName: "relogioDaSessao"
                Layout.alignment: Qt.AlignHCenter
                visible: sessao.relogioVisivel
                text: sessao.relogio
                textFormat: Text.PlainText
                color: "white"
                font { family: Tema.fonte; pixelSize: Tema.titulo1; weight: Tema.pesoTitulo1; features: { "tnum": 1 } }  // title-1 numeric
            }

            Botao {
                id: botaoTerminei
                objectName: "botaoJaTerminei"
                Layout.alignment: Qt.AlignHCenter
                estilo: "sugestao"
                pilula: true
                text: "Já terminei de jogar"
                onClicked: sessao.terminar()
            }

            // O `MenuButton` plano da `main`: o texto e a seta para baixo. Sobre a camada escura o branco vale nos dois
            // temas (o `currentColor` da `main` seria o texto do tema, e o hover sumiria no tema claro).
            Botao {
                id: botaoAnotacao
                objectName: "botaoAnotacaoDaSessao"
                Layout.alignment: Qt.AlignHCenter
                estilo: "plano"
                corDoTexto: "white"
                text: "Onde eu parei"
                dica: "Anotar onde você parou neste jogo"
                dicaAtiva: hovered
                dicaSomeAoClicar: false
                checked: balao.opened
                leftPadding: 10
                rightPadding: 10
                Accessible.description: dica
                onClicked: balao.opened ? balao.close() : balao.open()
                contentItem: Row {
                    spacing: 6
                    Text {
                        anchors.verticalCenter: parent.verticalCenter
                        text: botaoAnotacao.text
                        textFormat: Text.PlainText
                        color: botaoAnotacao.corDoTexto
                        font { family: Tema.fonte; pixelSize: Tema.corpo; weight: Tema.pesoForte }
                    }
                    Icone { anchors.verticalCenter: parent.verticalCenter; nome: "pan-down"; cor: botaoAnotacao.corDoTexto }
                }
                BalaoDaAnotacao {
                    id: balao
                    objectName: "balaoDaSessao"
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
