import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// "Jogos sem atalho": os jogos restaurados cujo atalho não foi achado; só desenha, a lista e as ações são do
// `restauracao`.
ModalDaRestauracao {
    id: dialogo
    objectName: "dialogoDosPendentes"

    aberto: restauracao.pendentesAbertos
    titulo: "Jogos sem atalho"
    largura: 560
    inicial: botaoDepois
    onSaiu: restauracao.lembrarDepois()

    Text {
        objectName: "textoDosPendentes"
        width: parent.width
        text: "Os atalhos dos jogos abaixo não foram encontrados."
        textFormat: Text.PlainText
        wrapMode: Text.Wrap
        horizontalAlignment: Text.AlignHCenter
        color: Tema.texto
        font { family: Tema.fonte; pixelSize: Tema.corpo }
    }
    Row {
        width: parent.width
        spacing: 10
        Icone {
            id: iconeDaNota
            nome: "dialog-information"
            cor: Tema.textoSecundario
        }
        Text {
            objectName: "recomendacaoDosPendentes"
            width: parent.width - iconeDaNota.width - parent.spacing
            text: "Escolha o atalho de cada jogo por esta janela. Um atalho importado de outra forma pode entrar como um jogo novo, sem o tempo de jogo e o histórico de sessões do backup."
            textFormat: Text.PlainText
            wrapMode: Text.Wrap
            color: Tema.textoSecundario
            font { family: Tema.fonte; pixelSize: Tema.corpo }
        }
    }
    Flickable {
        id: lista
        objectName: "listaDosPendentes"
        width: parent.width
        height: Math.min(grupo.implicitHeight, 420)
        enabled: !restauracao.listaTravada
        contentHeight: grupo.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        RolagemDaRoda { alvo: lista }
        ScrollBar.vertical: BarraDeRolagem {}
        Connections {
            target: lista.Window.window
            function onActiveFocusItemChanged() {
                const foco = lista.Window.window.activeFocusItem
                if (!foco) return
                let dentro = false
                for (var q = foco; q; q = q.parent) if (q === lista.contentItem) { dentro = true; break }
                if (!dentro) return
                const topo = foco.mapToItem(lista.contentItem, 0, 0).y
                const base = topo + foco.height
                if (topo < lista.contentY) lista.contentY = Math.max(0, topo - 8)
                else if (base > lista.contentY + lista.height) lista.contentY = Math.max(0, Math.min(lista.contentHeight - lista.height, base - lista.height + 8))
            }
        }

        GrupoDeLinhas {
            id: grupo
            width: lista.width
            visible: true  // criado com o diálogo escondido, mediria zero para sempre
            Repeater {
                model: restauracao.pendentes
                delegate: LinhaDoGrupo {
                    id: linha
                    required property var modelData
                    objectName: "pendente-" + modelData.id
                    comTextos: false
                    alturaMinima: Math.max(50, conteudo.implicitHeight + 12)

                    RowLayout {
                        id: conteudo
                        anchors {
                            left: parent.left; leftMargin: 14
                            right: parent.right; rightMargin: 14
                            verticalCenter: parent.verticalCenter; verticalCenterOffset: linha._separador / 2
                        }
                        spacing: 12

                        ModalDaRestauracao.Capa {
                            Layout.alignment: Qt.AlignVCenter
                            fonte: linha.modelData.capa
                        }
                        ColumnLayout {
                            Layout.fillWidth: true
                            Layout.alignment: Qt.AlignVCenter
                            spacing: 3
                            Text {
                                objectName: "nomeDoPendente"
                                Layout.fillWidth: true
                                text: linha.modelData.nome
                                textFormat: Text.PlainText
                                wrapMode: Text.Wrap
                                lineHeightMode: Text.FixedHeight
                                lineHeight: Tema.alturaDoCorpo
                                color: Tema.texto
                                font { family: Tema.fonte; pixelSize: Tema.corpo }
                            }
                            Text {
                                objectName: "tempoDoPendente"
                                Layout.fillWidth: true
                                text: linha.modelData.tempo
                                textFormat: Text.PlainText
                                wrapMode: Text.Wrap
                                lineHeightMode: Text.FixedHeight
                                lineHeight: Tema.alturaDaLegenda
                                color: Tema.textoSecundario
                                font { family: Tema.fonte; pixelSize: Tema.legenda }
                            }
                        }
                        Botao {
                            objectName: "botaoEscolherAtalho"
                            Layout.alignment: Qt.AlignVCenter
                            text: "Escolher atalho…"
                            onClicked: restauracao.escolherAtalho(linha.modelData.id)
                        }
                        Botao {
                            objectName: "botaoExcluirPendente"
                            Layout.alignment: Qt.AlignVCenter
                            text: "Excluir"
                            estilo: "destrutivo"
                            onClicked: restauracao.excluir(linha.modelData.id)
                        }
                    }
                }
            }
        }
    }
    Item {
        width: parent.width
        height: botaoDepois.height
        BotaoDoModal {
            id: botaoDepois
            objectName: "botaoLembrarDepois"
            anchors.horizontalCenter: parent.horizontalCenter
            text: "Lembrar mais tarde"
            onClicked: restauracao.lembrarDepois()
        }
    }
}
