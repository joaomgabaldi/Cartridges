import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Window

// A pergunta da versão nova e o "Baixando atualização…" (D82), na camada dos avisos: acima das Preferências.
// `atualizador` é o AppUpdater (cartridges/utils/app_updater.py). As notas vão em RichText porque o `notes_to_markup`
// as entrega só com <b>, <tt> e <br> (o resto do texto da release é escapado); o corpo e os rótulos, em PlainText.
// Atualizar destacado, mas não como padrão: a caixa aparece sem ser pedida, e um Enter perdido (digitando na busca)
// não pode começar o download. O foco inicial fica em "Agora não"; Esc vale "Agora não" (e "Cancelar" no download).
Rectangle {
    id: dialogo

    property QtObject atualizador
    // Um diálogo da fila da D72 (confirmação, erros) na tela: o da atualização espera escondido, para que o teclado e o
    // Esc sejam sempre do que se vê; ao fechar o outro, ele volta e retoma o foco.
    property bool outroAberto: false
    readonly property var pergunta: atualizador ? atualizador.pergunta : ({})
    readonly property bool baixando: !!atualizador && atualizador.baixando
    readonly property bool perguntando: !baixando && pergunta.versao !== undefined

    // Quem tinha o foco ao abrir: volta a tê-lo ao fechar.
    property Item retorno: null
    signal retornoPerdido()

    // Depois de a página de trás voltar a ficar habilitada; sem para onde voltar, o foco vai à página à vista.
    function devolverAoRetorno() {
        if (visible || outroAberto) return // escondido para dar lugar a outro diálogo: o foco é dele
        if (retorno && retorno !== Window.contentItem && retorno.visible && retorno.enabled) retorno.forceActiveFocus(Qt.TabFocusReason)
        else dialogo.retornoPerdido()
        retorno = null
    }

    function recusar() {
        if (baixando) atualizador.cancelar()
        else if (perguntando) atualizador.responder(false)
    }

    anchors.fill: parent
    z: 10
    visible: (baixando || perguntando) && !outroAberto
    color: "#80000000"
    focus: visible
    Keys.onEscapePressed: recusar()
    // Modal para o teclado e o controle: nenhuma tecla chega à página de trás.
    Keys.onPressed: event => event.accepted = true

    onVisibleChanged: {
        if (visible) {
            retorno = Window.window ? Window.window.activeFocusItem : null
            // Adiado: o item acabou de ficar visível e só então aceita o foco.
            Qt.callLater(() => { if (dialogo.visible) (dialogo.baixando ? botaoCancelar : botaoAgoraNao).forceActiveFocus(Qt.TabFocusReason) })
        } else {
            Qt.callLater(devolverAoRetorno)
        }
    }
    // Da pergunta ao download o diálogo segue aberto: o foco vai ao botão que sobrou.
    onBaixandoChanged: if (visible) Qt.callLater(() => { if (dialogo.visible) (dialogo.baixando ? botaoCancelar : botaoAgoraNao).forceActiveFocus(Qt.TabFocusReason) })

    MouseArea { anchors.fill: parent } // o que está embaixo não recebe cliques

    Rectangle {
        anchors.centerIn: parent
        width: Math.min(460, parent.width - 48)
        height: coluna.implicitHeight + 48
        radius: 8
        color: Tema.fundo
        border.color: Tema.botaoSobre

        Column {
            id: coluna
            anchors { left: parent.left; right: parent.right; top: parent.top; margins: 24 }
            spacing: 16

            Text {
                objectName: "tituloDaAtualizacao"
                width: parent.width
                text: dialogo.baixando ? "Baixando atualização…" : "Nova versão disponível: " + (dialogo.pergunta.versao || "")
                textFormat: Text.PlainText
                wrapMode: Text.Wrap
                color: Tema.texto
                font { family: Tema.fonte; pixelSize: 18; weight: Font.DemiBold }
                Accessible.role: Accessible.Heading
                Accessible.name: text
            }
            Text {
                objectName: "corpoDaAtualizacao"
                width: parent.width
                visible: !dialogo.baixando
                text: "Deseja baixar e instalar a atualização agora? O aplicativo será fechado durante a instalação."
                textFormat: Text.PlainText
                wrapMode: Text.Wrap
                color: Tema.texto
                font { family: Tema.fonte; pixelSize: 14 }
            }

            Flickable {
                id: rolagem
                objectName: "rolagemDasNotas"
                visible: !dialogo.baixando && notas.text !== ""
                width: parent.width
                height: Math.min(contentHeight, 360)
                contentWidth: width
                contentHeight: notas.implicitHeight
                clip: true
                interactive: contentHeight > height
                ScrollBar.vertical: BarraDeRolagem {}

                Text {
                    id: notas
                    objectName: "notasDaAtualizacao"
                    width: rolagem.width - 12
                    text: dialogo.pergunta.notas || ""
                    textFormat: Text.RichText
                    wrapMode: Text.Wrap
                    color: Tema.texto
                    font { family: Tema.fonte; pixelSize: 14 }
                }
            }

            Column {
                width: parent.width
                spacing: 6
                visible: dialogo.baixando

                BarraDeProgresso {
                    objectName: "barraDaAtualizacao"
                    width: parent.width
                    value: dialogo.atualizador ? dialogo.atualizador.progresso : 0
                    corDaTrilha: Tema.botaoSobre
                }
                Text {
                    objectName: "porcentagemDaAtualizacao"
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: Math.round((dialogo.atualizador ? dialogo.atualizador.progresso : 0) * 100) + "%"
                    textFormat: Text.PlainText
                    color: Tema.textoSecundario
                    font { family: Tema.fonte; pixelSize: 13 }
                }
            }

            Row {
                anchors.right: parent.right
                spacing: 8

                component BotaoDoDialogo: Button {
                    id: botao
                    property color cor: Tema.superficie
                    property color corDoTexto: Tema.texto
                    // Tab e Shift+Tab circulam entre os botões visíveis (com um só, ele mesmo).
                    property Item anterior
                    property Item proximo
                    focusPolicy: Qt.StrongFocus
                    implicitHeight: 36
                    leftPadding: 20
                    rightPadding: 20
                    Keys.onTabPressed: proximo.forceActiveFocus(Qt.TabFocusReason)
                    Keys.onBacktabPressed: anterior.forceActiveFocus(Qt.BacktabFocusReason)
                    Keys.onLeftPressed: anterior.forceActiveFocus(Qt.BacktabFocusReason)
                    Keys.onRightPressed: proximo.forceActiveFocus(Qt.TabFocusReason)
                    Keys.onReturnPressed: click()
                    Keys.onEnterPressed: click()
                    contentItem: Text {
                        text: botao.text
                        textFormat: Text.PlainText
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                        color: botao.corDoTexto
                        font { family: Tema.fonte; pixelSize: 14 }
                    }
                    background: Rectangle {
                        radius: 6
                        color: botao.cor
                        opacity: botao.down ? 0.75 : botao.hovered ? 0.9 : 1
                        border { width: botao.visualFocus ? 2 : 1; color: botao.visualFocus ? Tema.texto : Tema.borda }
                    }
                }

                BotaoDoDialogo {
                    id: botaoAgoraNao
                    objectName: "botaoAgoraNao"
                    visible: !dialogo.baixando
                    anterior: botaoAtualizar
                    proximo: botaoAtualizar
                    text: "Agora não"
                    onClicked: dialogo.atualizador.responder(false)
                }
                BotaoDoDialogo {
                    id: botaoAtualizar
                    objectName: "botaoAtualizar"
                    visible: !dialogo.baixando
                    anterior: botaoAgoraNao
                    proximo: botaoAgoraNao
                    text: "Atualizar"
                    cor: Tema.destaque
                    corDoTexto: "white"
                    onClicked: dialogo.atualizador.responder(true)
                }
                BotaoDoDialogo {
                    id: botaoCancelar
                    objectName: "botaoCancelarAtualizacao"
                    visible: dialogo.baixando
                    anterior: botaoCancelar
                    proximo: botaoCancelar
                    text: "Cancelar"
                    onClicked: dialogo.atualizador.cancelar()
                }
            }
        }
    }
}
