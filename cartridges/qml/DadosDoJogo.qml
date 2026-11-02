import QtQuick

// "Dados do jogo": o conflito entre o backup e os dados locais do mesmo jogo (D81). Dois cartões, "Backup" e "Este PC",
// e a escolha de qual manter ou mesclar. Só desenha: os números e a decisão são do `restauracao`. Esc fecha sem decidir.
ModalDaRestauracao {
    id: dialogo
    objectName: "dialogoDosDadosDoJogo"

    aberto: restauracao.conflitoAberto
    titulo: "Dados do jogo"
    largura: 620
    inicial: botaoBackup
    onSaiu: restauracao.cancelarConflito()

    Row {
        anchors.horizontalCenter: parent.horizontalCenter
        spacing: 14
        Rectangle {
            width: 44
            height: 66
            radius: 4
            color: Tema.botaoSobre
            clip: true
            Image {
                anchors.fill: parent
                source: restauracao.conflito.capa || ""
                fillMode: Image.PreserveAspectCrop
                asynchronous: true
                sourceSize: Qt.size(88, 132)
            }
        }
        Text {
            objectName: "nomeDoConflito"
            anchors.verticalCenter: parent.verticalCenter
            text: restauracao.conflito.nome || ""
            textFormat: Text.PlainText
            color: Tema.texto
            font { family: Tema.fonte; pixelSize: Tema.titulo2; weight: Tema.pesoTitulo2 }  // title-2
        }
    }

    component Cartao: Rectangle {
        id: cartao
        property string rotulo
        property string objeto  // "Backup" ou "EstePc"
        property string icone
        property var dados: ({})
        width: (parent.width - 24 - 2 * parent.spacing) / 2  // 24: o aviso entre os dois
        height: dentro.implicitHeight + 28
        // `.card`: raio 12 e a sombra do cartão.
        radius: 12
        color: Tema.cartao
        Sombra { camadas: Tema.sombraCartao; raio: 12 }
        Icone {
            anchors { left: parent.left; leftMargin: 14; top: parent.top; topMargin: 14 }
            nome: cartao.icone
            tamanho: 24
        }
        Column {
            id: dentro
            anchors { left: parent.left; leftMargin: 52; right: parent.right; rightMargin: 14; top: parent.top; topMargin: 14 }
            spacing: 2
            Text {
                objectName: "rotuloDoCartao" + cartao.objeto
                text: cartao.rotulo
                textFormat: Text.PlainText
                color: Tema.texto
                font { family: Tema.fonte; pixelSize: Tema.corpo; weight: Tema.pesoForte }  // heading
            }
            Text {
                objectName: "tempoDoCartao" + cartao.objeto
                text: cartao.dados.tempo || ""
                textFormat: Text.PlainText
                color: Tema.textoSecundario
                font { family: Tema.fonte; pixelSize: Tema.corpo }
            }
            Text {
                objectName: "sessoesDoCartao" + cartao.objeto
                text: cartao.dados.sessoes || ""
                textFormat: Text.PlainText
                color: Tema.textoSecundario
                font { family: Tema.fonte; pixelSize: Tema.corpo }
            }
            Text {
                objectName: "ultimaDoCartao" + cartao.objeto
                visible: text !== ""
                text: cartao.dados.ultima || ""
                textFormat: Text.PlainText
                color: Tema.textoSecundario
                font { family: Tema.fonte; pixelSize: Tema.corpo }
            }
        }
    }
    Row {
        width: parent.width
        spacing: 12
        Cartao { rotulo: "Backup"; objeto: "Backup"; icone: "drive-harddisk"; dados: restauracao.conflito.backup || ({}) }
        Item {
            width: 24
            height: 24
            anchors.verticalCenter: parent.verticalCenter
            // `warning_color` do tema (a classe `.warning` do GTK), e não um amarelo fixo.
            Icone { anchors.centerIn: parent; nome: "dialog-warning"; cor: Tema.derivada(Tema.escuro ? "#cd9309" : "#e5a50a") }
        }
        Cartao { rotulo: "Este PC"; objeto: "EstePc"; icone: "computer"; dados: restauracao.conflito.estePc || ({}) }
    }
    Text {
        objectName: "textoDoConflito"
        width: parent.width
        text: "Este jogo já possui dados locais. Escolha qual versão deseja manter ou mescle as duas fontes."
        textFormat: Text.PlainText
        wrapMode: Text.Wrap
        horizontalAlignment: Text.AlignHCenter
        color: Tema.texto
        font { family: Tema.fonte; pixelSize: Tema.corpo }
    }
    Row {
        anchors.horizontalCenter: parent.horizontalCenter
        spacing: 10
        BotaoDoModal {
            id: botaoBackup
            objectName: "botaoManterBackup"
            text: "Manter backup"
            onClicked: restauracao.decidir("backup")
        }
        BotaoDoModal {
            objectName: "botaoMesclar"
            text: "Mesclar dados"
            onClicked: restauracao.decidir("mesclar")
        }
        BotaoDoModal {
            objectName: "botaoManterEstePc"
            text: "Manter este PC"
            onClicked: restauracao.decidir("este_pc")
        }
    }
    Text {
        objectName: "dicaDoConflito"
        width: parent.width
        text: restauracao.conflito.dica || ""
        textFormat: Text.PlainText
        horizontalAlignment: Text.AlignHCenter
        color: Tema.textoSecundario
        font { family: Tema.fonte; pixelSize: Tema.legenda }  // caption dim-label
    }
}
