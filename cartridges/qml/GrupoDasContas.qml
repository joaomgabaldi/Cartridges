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
    // Quantas contas passam na busca; o grupo some sem nenhuma (como `GrupoDePreferencias.linhasAMostrar`).
    readonly property int linhasAMostrar: [contas.microsoft, contas.epic, contas.ea]
        .filter(d => BuscaDasPreferencias.passa(d.titulo, d.subtitulo)).length
    visible: linhasAMostrar > 0

    width: parent ? parent.width : implicitWidth
    spacing: 8

    Text {
        objectName: "tituloDoGrupoDasContas"
        width: parent.width
        leftPadding: 4
        text: grupo.contas.titulo
        textFormat: Text.PlainText
        color: Tema.texto
        font { family: Tema.fonte; pixelSize: 14; weight: Font.Bold }
        Accessible.role: Accessible.Heading
        Accessible.name: text
    }
    Text {
        objectName: "descricaoDoGrupoDasContas"
        width: parent.width
        leftPadding: 4
        text: grupo.contas.descricao
        textFormat: Text.PlainText
        wrapMode: Text.Wrap
        color: Tema.textoSecundario
        font { family: Tema.fonte; pixelSize: 13 }
    }

    // Uma conta: o nome da conta em cima, o estado embaixo e o botão à direita.
    component LinhaDaConta: Item {
        id: linha
        property string chave
        property var dados
        visible: BuscaDasPreferencias.passa(dados.titulo, dados.subtitulo)
        signal clicado()

        width: parent.width
        height: 58

        Rectangle { width: parent.width; height: 1; color: Tema.borda; visible: linha.y > 0 }

        Column {
            anchors { left: parent.left; leftMargin: 16; right: botao.left; rightMargin: 12; verticalCenter: parent.verticalCenter }
            Text {
                objectName: "tituloDaConta_" + linha.chave
                width: parent.width
                text: linha.dados.titulo
                textFormat: Text.PlainText
                elide: Text.ElideRight
                color: Tema.texto
                font { family: Tema.fonte; pixelSize: 15 }
            }
            Text {
                objectName: "subtituloDaConta_" + linha.chave
                width: parent.width
                text: linha.dados.subtitulo
                textFormat: Text.PlainText
                elide: Text.ElideRight
                color: Tema.textoSecundario
                font { family: Tema.fonte; pixelSize: 12 }
            }
        }

        Button {
            id: botao
            objectName: "botaoDaConta_" + linha.chave
            anchors { right: parent.right; rightMargin: 12; verticalCenter: parent.verticalCenter }
            text: linha.dados.botao
            focusPolicy: Qt.StrongFocus
            implicitHeight: 34
            leftPadding: 18
            rightPadding: 18
            Accessible.name: linha.dados.botao + ", " + linha.dados.titulo
            onClicked: linha.clicado()
            contentItem: Text {
                text: botao.text
                textFormat: Text.PlainText
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
                color: Tema.texto
                font { family: Tema.fonte; pixelSize: 14 }
            }
            background: Rectangle {
                radius: 6
                color: botao.down ? Tema.pressionado : botao.hovered ? Tema.botaoSobre : Tema.superficie
                border { width: botao.visualFocus ? 2 : 1; color: botao.visualFocus ? Tema.texto : Tema.borda }
            }
        }
    }

    GrupoDeLinhas {
        width: parent.width
        LinhaDaConta { chave: "microsoft"; dados: grupo.contas.microsoft; onClicado: grupo.contas.clicarMicrosoft() }
        LinhaDaConta { chave: "epic"; dados: grupo.contas.epic; onClicado: grupo.contas.clicarEpic() }
        LinhaDaConta { chave: "ea"; dados: grupo.contas.ea; onClicado: grupo.contas.clicarEa() }
    }
}
