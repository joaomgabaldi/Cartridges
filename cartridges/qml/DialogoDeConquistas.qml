import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import QtQuick.Window

// A lista completa de conquistas de um jogo: o logo (ou o nome), o resumo e a barra no topo, e os grupos
// "Desbloqueadas" (da mais recente para a mais antiga) e "Bloqueadas", apagadas. Só desenha: o que ele mostra e faz é o
// `conquistasDoJogo` (cartridges/modelos/conquistas.py).
// Modal para o mouse, o teclado e o controle, como o histórico; o foco volta a quem o abriu. Sem título visível: o logo
// (ou o nome) é a manchete, e o título só vive no nome acessível. Todo texto de conquista é de terceiros: texto puro.
Rectangle {
    id: dialogo
    objectName: "dialogoDeConquistas"

    Accessible.role: Accessible.Dialog
    Accessible.name: "Conquistas"
    // Quem tinha o foco ao abrir.
    property Item retorno: null

    anchors.fill: parent
    visible: conquistasDoJogo.aberto
    color: "#80000000"
    Keys.onEscapePressed: conquistasDoJogo.fechar()
    // Modal para o teclado e o controle: nenhuma tecla chega à página de trás; as setas rolam a lista.
    Keys.onPressed: event => {
        var passo = event.key === Qt.Key_Up ? -48 : event.key === Qt.Key_Down ? 48
            : event.key === Qt.Key_PageUp ? -rolagem.height : event.key === Qt.Key_PageDown ? rolagem.height : 0
        if (passo !== 0)
            rolagem.contentY = Math.max(0, Math.min(rolagem.contentHeight - rolagem.height, rolagem.contentY + passo))
        event.accepted = true
    }

    onVisibleChanged: {
        if (visible) {
            retorno = Window.window ? Window.window.activeFocusItem : null
            rolagem.contentY = 0
            botaoFechar.forceActiveFocus(Qt.TabFocusReason)
        } else {
            // Depois da reação das outras bindings ao `aberto` (a página de trás volta a ficar habilitada).
            Qt.callLater(devolverAoRetorno)
        }
    }
    function devolverAoRetorno() {
        if (visible) return
        if (retorno && retorno.visible && retorno.enabled) retorno.forceActiveFocus(Qt.TabFocusReason)
        // Fechado sozinho (o cartão que o abriu sumiu): o foco vai à página à vista, como no diálogo de edição.
        else if (Window.window && Window.window.paginaDoControle) Window.window.paginaDoControle.focarGrade()
    }

    MouseArea { anchors.fill: parent } // o que está embaixo não recebe cliques

    component TituloDoGrupo: Text {
        textFormat: Text.PlainText
        color: Tema.texto
        font { family: Tema.fonte; pixelSize: 14; weight: Font.Bold }
    }

    // Um grupo de fileiras: o título e a superfície com as linhas; some quando não há linha.
    component Secao: ColumnLayout {
        id: secao
        property string titulo
        property var fileiras: []
        visible: fileiras.length > 0
        spacing: 8

        TituloDoGrupo { text: secao.titulo; Layout.leftMargin: 4 }
        GrupoDeLinhas {
            Layout.fillWidth: true
            // A seção já some sem linhas; o grupo escondido pela altura zero nunca mediria as que o Repeater cria.
            visible: true
            Repeater {
                model: secao.fileiras
                delegate: Item {
                    id: fileira
                    objectName: "fileiraDeConquista"
                    required property var modelData
                    required property int index
                    width: parent.width
                    height: linha.implicitHeight + 24
                    // A bloqueada fica apagada, como o `dim-label` da `main`.
                    opacity: modelData.desbloqueada ? 1 : 0.55

                    Rectangle { width: parent.width; height: 1; color: Tema.borda; visible: fileira.index > 0 }

                    RowLayout {
                        id: linha
                        anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; margins: 12 }
                        spacing: 12

                        IconeDaConquista {
                            Layout.alignment: Qt.AlignVCenter
                            tamanho: 36
                            interrogacao: 24
                            url: fileira.modelData.icone.url
                            cinza: fileira.modelData.icone.cinza
                            oculta: fileira.modelData.icone.oculta
                        }
                        ColumnLayout {
                            Layout.fillWidth: true
                            Layout.alignment: Qt.AlignVCenter
                            spacing: 2
                            Text {
                                objectName: "tituloDaConquista"
                                Layout.fillWidth: true
                                text: fileira.modelData.titulo
                                textFormat: Text.PlainText
                                wrapMode: Text.Wrap
                                color: Tema.texto
                                font { family: Tema.fonte; pixelSize: 15 }
                            }
                            Text {
                                objectName: "subtituloDaConquista"
                                Layout.fillWidth: true
                                visible: text !== ""
                                text: fileira.modelData.subtitulo
                                textFormat: Text.PlainText
                                wrapMode: Text.Wrap
                                color: Tema.textoSecundario
                                font { family: Tema.fonte; pixelSize: 12 }
                            }
                        }
                        ColumnLayout {
                            Layout.alignment: Qt.AlignVCenter
                            spacing: 0
                            Text {
                                objectName: "dataDaConquista"
                                Layout.alignment: Qt.AlignRight
                                visible: text !== ""
                                text: fileira.modelData.data
                                textFormat: Text.PlainText
                                color: Tema.textoSecundario
                                font { family: Tema.fonte; pixelSize: 14 }
                            }
                            Text {
                                objectName: "porcentagemDaConquista"
                                Layout.alignment: Qt.AlignRight
                                visible: text !== ""
                                text: fileira.modelData.porcentagem
                                textFormat: Text.PlainText
                                color: fileira.modelData.rara ? "#e5a50a" : Tema.textoSecundario
                                font { family: Tema.fonte; pixelSize: 14; weight: fileira.modelData.rara ? Font.Bold : Font.Normal }
                            }
                        }
                    }
                }
            }
        }
    }

    Rectangle {
        id: cartao
        objectName: "caixaDeConquistas"
        anchors.centerIn: parent
        width: Math.min(520, parent.width - 48)
        height: Math.min(640, parent.height - 48)
        radius: 8
        color: Tema.fundo
        border.color: Tema.botaoSobre
        clip: true

        // A faixa de cima: só o botão de fechar, à direita (o `Adw.HeaderBar(show_title=False)` da `main`).
        Item {
            id: faixa
            anchors { left: parent.left; right: parent.right; top: parent.top }
            height: 40
            Button {
                id: botaoFechar
                objectName: "botaoFecharConquistas"
                anchors { right: parent.right; rightMargin: 8; verticalCenter: parent.verticalCenter }
                focusPolicy: Qt.StrongFocus
                implicitWidth: 34
                implicitHeight: 34
                Accessible.name: "Fechar"
                ToolTip.visible: hovered
                ToolTip.text: "Fechar"
                ToolTip.delay: 600
                onClicked: conquistasDoJogo.fechar()
                contentItem: Text {
                    text: ""  // fechar
                    textFormat: Text.PlainText
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    color: Tema.texto
                    font { family: Tema.fonteDeIcones; pixelSize: 16 }
                }
                background: Rectangle {
                    radius: 6
                    color: botaoFechar.down ? Tema.pressionado : botaoFechar.hovered ? Tema.botaoSobre : "transparent"
                    border { width: botaoFechar.visualFocus ? 2 : 0; color: Tema.destaque }
                }
            }
        }

        Flickable {
            id: rolagem
            objectName: "rolagemDeConquistas"
            anchors { left: parent.left; right: parent.right; top: faixa.bottom; bottom: parent.bottom }
            contentWidth: width
            contentHeight: conteudo.implicitHeight + 24
            boundsBehavior: Flickable.StopAtBounds
            clip: true
            ScrollBar.vertical: BarraDeRolagem {}

            ColumnLayout {
                id: conteudo
                x: 24
                width: rolagem.width - 48
                spacing: 12

                CabecalhoDoJogo {
                    Layout.fillWidth: true
                    logo: conquistasDoJogo.logo
                    larguraDoLogo: conquistasDoJogo.larguraDoLogo
                    nome: conquistasDoJogo.nome
                    nomeDoLogo: "logoDasConquistas"
                    nomeDoTexto: "nomeDasConquistas"
                }
                Text {
                    objectName: "resumoDasConquistas"
                    Layout.fillWidth: true
                    text: conquistasDoJogo.resumo
                    textFormat: Text.PlainText
                    wrapMode: Text.Wrap
                    horizontalAlignment: Text.AlignHCenter
                    color: Tema.textoSecundario
                    font { family: Tema.fonte; pixelSize: 14 }
                }
                BarraDeProgresso {
                    objectName: "barraDasConquistas"
                    Layout.fillWidth: true
                    value: conquistasDoJogo.fracao
                }
                Secao {
                    objectName: "secaoDesbloqueadas"
                    Layout.fillWidth: true
                    Layout.topMargin: 12
                    titulo: "Desbloqueadas"
                    fileiras: conquistasDoJogo.desbloqueadas
                }
                Secao {
                    objectName: "secaoBloqueadas"
                    Layout.fillWidth: true
                    Layout.topMargin: 12
                    titulo: "Bloqueadas"
                    fileiras: conquistasDoJogo.bloqueadas
                }
            }
        }
    }
}
