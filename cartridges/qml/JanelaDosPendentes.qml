import QtQuick
import QtQuick.Controls.Basic

// "Jogos sem atalho": a lista dos jogos restaurados cujo atalho não foi achado, com "Escolher atalho…" e "Excluir" em
// cada um (D81). Só desenha: a lista e as ações são do `restauracao`. Esc vale "Lembrar mais tarde".
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
        color: Tema.texto
        font { family: Tema.fonte; pixelSize: 14 }
    }
    Row {
        width: parent.width
        spacing: 10
        Text {
            id: iconeDaNota
            text: ""  // informação
            textFormat: Text.PlainText
            color: Tema.textoSecundario
            font { family: Tema.fonteDeIcones; pixelSize: 16 }
        }
        Text {
            objectName: "recomendacaoDosPendentes"
            width: parent.width - iconeDaNota.width - parent.spacing
            text: "Escolha o atalho de cada jogo por esta janela. Um atalho importado de outra forma pode entrar como um jogo novo, sem o tempo de jogo e o histórico de sessões do backup."
            textFormat: Text.PlainText
            wrapMode: Text.Wrap
            color: Tema.textoSecundario
            font { family: Tema.fonte; pixelSize: 13 }
        }
    }
    ListView {
        id: lista
        objectName: "listaDosPendentes"
        width: parent.width
        height: Math.min(contentHeight, 420)
        // Travada enquanto a importação de uma escolha de atalho roda.
        enabled: !restauracao.listaTravada
        model: restauracao.pendentes
        spacing: 6
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: BarraDeRolagem {}

        delegate: Rectangle {
            id: linha
            required property var modelData
            objectName: "pendente-" + modelData.id
            width: ListView.view.width
            height: 72
            radius: 6
            color: Tema.superficie
            border.color: Tema.borda

            Rectangle {
                id: capa
                anchors { left: parent.left; leftMargin: 12; verticalCenter: parent.verticalCenter }
                width: 32
                height: 48
                radius: 4
                color: Tema.botaoSobre
                clip: true
                Image {
                    anchors.fill: parent
                    source: linha.modelData.capa
                    fillMode: Image.PreserveAspectCrop
                    asynchronous: true
                    sourceSize: Qt.size(64, 96)
                }
            }
            Column {
                anchors {
                    left: capa.right; leftMargin: 12; right: botoes.left; rightMargin: 12
                    verticalCenter: parent.verticalCenter
                }
                spacing: 2
                Text {
                    objectName: "nomeDoPendente"
                    width: parent.width
                    text: linha.modelData.nome
                    textFormat: Text.PlainText
                    elide: Text.ElideRight
                    color: Tema.texto
                    font { family: Tema.fonte; pixelSize: 14 }
                }
                Text {
                    objectName: "tempoDoPendente"
                    width: parent.width
                    text: linha.modelData.tempo
                    textFormat: Text.PlainText
                    elide: Text.ElideRight
                    color: Tema.textoSecundario
                    font { family: Tema.fonte; pixelSize: 12 }
                }
            }
            Row {
                id: botoes
                anchors { right: parent.right; rightMargin: 12; verticalCenter: parent.verticalCenter }
                spacing: 8
                BotaoDoModal {
                    objectName: "botaoEscolherAtalho"
                    text: "Escolher atalho…"
                    onClicked: restauracao.escolherAtalho(linha.modelData.id)
                }
                BotaoDoModal {
                    objectName: "botaoExcluirPendente"
                    text: "Excluir"
                    perigo: true
                    onClicked: restauracao.excluir(linha.modelData.id)
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
