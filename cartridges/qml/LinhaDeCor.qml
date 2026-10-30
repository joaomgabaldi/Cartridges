import QtQuick
import QtQuick.Controls.Basic

// Uma linha com título, subtítulo e, à direita, uma amostra de cor que abre o `SeletorDeCor` num balão (como a linha
// da fita do editor). Cada movimento no seletor emite `escolhida`; quem usa grava e devolve a cor em `cor`. Fora do
// padrão (`padrao: false`) aparece o botão de voltar a ele. `aberta` e `fechada` contam do balão (o pulso das
// conquistas mostra a própria cor só enquanto ele está aberto).
Item {
    id: linha

    property string titulo
    property string subtitulo
    property color cor
    property bool padrao: true
    property string dicaDaAmostra

    signal escolhida(color cor)
    signal aberta()
    signal fechada()
    signal voltar()

    width: parent ? parent.width : implicitWidth
    implicitHeight: Math.max(textos.implicitHeight, 34) + 24

    component BotaoDaLinha: Button {
        id: botao
        property string glifo
        property string dica
        focusPolicy: Qt.StrongFocus
        implicitWidth: 34
        implicitHeight: 34
        Accessible.name: dica
        ToolTip.visible: hovered && dica !== ""
        ToolTip.text: dica
        ToolTip.delay: 600
        Keys.onReturnPressed: click()
        Keys.onEnterPressed: click()
        contentItem: Text {
            text: botao.glifo
            textFormat: Text.PlainText
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            color: Tema.texto
            font { family: Tema.fonteDeIcones; pixelSize: 16 }
        }
        background: Rectangle {
            radius: 6
            color: botao.down ? Tema.pressionado : botao.hovered ? Tema.botaoSobre : "transparent"
            border { width: botao.visualFocus ? 2 : 0; color: Tema.destaque }
        }
    }

    Rectangle {
        width: parent.width
        height: 1
        color: Tema.borda
        visible: linha.y > 0
    }

    Column {
        id: textos
        anchors { left: parent.left; leftMargin: 16; right: botoes.left; rightMargin: 12; verticalCenter: parent.verticalCenter }
        spacing: 2
        Text {
            width: parent.width
            text: linha.titulo
            textFormat: Text.PlainText
            wrapMode: Text.Wrap
            color: Tema.texto
            font { family: Tema.fonte; pixelSize: 15 }
        }
        Text {
            width: parent.width
            visible: text !== ""
            text: linha.subtitulo
            textFormat: Text.PlainText
            wrapMode: Text.Wrap
            color: Tema.textoSecundario
            font { family: Tema.fonte; pixelSize: 12 }
        }
    }

    Row {
        id: botoes
        anchors { right: parent.right; rightMargin: 10; verticalCenter: parent.verticalCenter }
        spacing: 4

        BotaoDaLinha {
            objectName: linha.objectName + "Voltar"
            visible: !linha.padrao
            glifo: ""  // desfazer
            dica: "Voltar à cor padrão"
            onClicked: linha.voltar()
        }
        BotaoDaLinha {
            id: amostra
            objectName: linha.objectName + "Amostra"
            dica: linha.dicaDaAmostra
            onClicked: balao.opened ? balao.close() : balao.open()
            // A amostra de 22x22, em círculo.
            Rectangle {
                anchors.centerIn: parent
                width: 22
                height: 22
                radius: 11
                color: linha.cor
                border { width: 1; color: Tema.borda }
            }
            Popup {
                id: balao
                objectName: linha.objectName + "Balao"
                x: amostra.width - width
                y: amostra.height + 4
                padding: 12
                margins: 8  // o balão não sai da janela, mesmo com a linha no pé da rolagem
                closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
                // O seletor parte da cor que a linha mostra agora; depois disso quem manda nele é a mão.
                onAboutToShow: {
                    seletor.matiz = Math.max(0, linha.cor.hsvHue) * 360
                    seletor.saturacao = Math.round(linha.cor.hsvSaturation * 1000)
                }
                onOpened: {
                    seletor.forceActiveFocus(Qt.TabFocusReason)
                    linha.aberta()
                }
                onClosed: {
                    amostra.forceActiveFocus(Qt.TabFocusReason)
                    linha.fechada()
                }
                background: Rectangle { color: Tema.superficie; border.color: Tema.borda; radius: 8 }
                contentItem: SeletorDeCor {
                    id: seletor
                    objectName: linha.objectName + "Seletor"
                    onEscolhida: cor => linha.escolhida(cor)
                }
            }
        }
    }
}
