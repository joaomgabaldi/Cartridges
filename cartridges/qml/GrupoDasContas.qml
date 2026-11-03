import QtQuick
import QtQuick.Controls.Basic

// O grupo "Contas" (Microsoft, Epic e EA): o título, a descrição e uma linha por conta com o botão à direita.
// Só desenha: o que ele mostra e faz é o `contas` (um `ContasDasLojas`, cartridges/modelos/contas.py). As janelas de login
// (`JanelaDeLogin.qml`) ficam ao lado, cobrindo a janela inteira: quem hospeda o grupo as monta (`contas.loginEpic`,
// `contas.loginEa`). O nome da conta é texto de terceiros: sempre PlainText.
Column {
    id: grupo
    objectName: "grupoDasContas"

    property var contas
    // O título e a descrição; o assistente da primeira abertura os esconde (a página dele já explica as contas).
    property bool comCabecalho: true

    width: parent ? parent.width : implicitWidth
    // preferencesgroup > box: 6 entre o cabeçalho e o cartão; a descrição leva mais 6 embaixo.
    spacing: 6

    Text {
        objectName: "tituloDoGrupoDasContas"
        visible: grupo.comCabecalho
        width: parent.width
        text: grupo.contas.titulo
        textFormat: Text.PlainText
        color: Tema.texto
        font { family: Tema.fonte; pixelSize: Tema.corpo; weight: Tema.pesoForte }  // .heading
        Accessible.role: Accessible.Heading
        Accessible.name: text
    }
    Text {
        objectName: "descricaoDoGrupoDasContas"
        visible: grupo.comCabecalho
        width: parent.width
        bottomPadding: 6
        text: grupo.contas.descricao
        textFormat: Text.PlainText
        wrapMode: Text.Wrap
        color: Tema.textoSecundario
        font { family: Tema.fonte; pixelSize: Tema.corpo }
    }

    // Uma conta (`Adw.ActionRow` com o botão como sufixo): o nome em cima, o estado embaixo e o botão à direita. O nome
    // da conta quebra a linha, em vez de ser cortado: a altura acompanha o conteúdo.
    component LinhaDaConta: LinhaDoGrupo {
        id: linha
        property string chave
        property var dados
        titulo: dados.titulo
        subtitulo: dados.subtitulo
        buscavel: true
        signal clicado()

        comTextos: false
        alturaMinima: Math.max(50, colunaDaConta.implicitHeight + 12)

        Column {
            id: colunaDaConta
            anchors {
                left: parent.left; leftMargin: 14
                right: botao.left; rightMargin: 12
                verticalCenter: parent.verticalCenter; verticalCenterOffset: linha._separador / 2
            }
            spacing: 3
            Text {
                objectName: "tituloDaConta_" + linha.chave
                width: parent.width
                text: linha.dados.titulo
                textFormat: Text.PlainText
                wrapMode: Text.Wrap
                lineHeightMode: Text.FixedHeight
                lineHeight: Tema.alturaDoCorpo
                color: Tema.texto
                font { family: Tema.fonte; pixelSize: Tema.corpo }
            }
            Text {
                objectName: "subtituloDaConta_" + linha.chave
                width: parent.width
                text: linha.dados.subtitulo
                textFormat: Text.PlainText
                wrapMode: Text.Wrap
                lineHeightMode: Text.FixedHeight
                lineHeight: Tema.alturaDaLegenda
                color: Tema.textoSecundario
                font { family: Tema.fonte; pixelSize: Tema.legenda }
            }
        }

        Botao {
            id: botao
            objectName: "botaoDaConta_" + linha.chave
            anchors { right: parent.right; rightMargin: 14; verticalCenter: parent.verticalCenter; verticalCenterOffset: linha._separador / 2 }
            text: linha.dados.botao
            Accessible.name: linha.dados.botao + ", " + linha.dados.titulo
            onClicked: linha.clicado()
        }
    }

    GrupoDeLinhas {
        width: parent.width
        LinhaDaConta { chave: "microsoft"; dados: grupo.contas.microsoft; onClicado: grupo.contas.clicarMicrosoft() }
        LinhaDaConta { chave: "epic"; dados: grupo.contas.epic; onClicado: grupo.contas.clicarEpic() }
        LinhaDaConta { chave: "ea"; dados: grupo.contas.ea; onClicado: grupo.contas.clicarEa() }
    }
}
