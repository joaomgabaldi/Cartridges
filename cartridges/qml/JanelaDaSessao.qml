import QtQuick
import QtQuick.Controls.Basic

// A janela "Jogando {nome}" da sessão manual (D50): moldura nativa do Windows, 300×150, tamanho fixo.
// Fechar pela moldura e o botão fazem o mesmo: encerrar a sessão com registro. Posta pelo Python.
Window {
    id: raiz
    objectName: "janelaDaSessao"
    title: sessao.tituloDaJanela
    width: 300
    height: 150
    minimumWidth: width
    maximumWidth: width
    minimumHeight: height
    maximumHeight: height
    color: Tema.fundo
    transientParent: null  // solta: não some junto com a janela principal
    flags: Qt.Window | Qt.WindowTitleHint | Qt.WindowSystemMenuHint | Qt.WindowCloseButtonHint
    visible: true

    onVisibleChanged: if (visible) sessao.posicionarJanelaManual(raiz)
    onClosing: sessao.janelaManualFechada()

    Button {
        id: botao
        objectName: "botaoTermineiDaJanela"
        anchors.centerIn: parent
        focus: true
        text: "Já terminei de jogar"
        implicitHeight: 44
        leftPadding: 28
        rightPadding: 28
        onClicked: sessao.janelaManualFechada()
        contentItem: Text {
            text: botao.text
            textFormat: Text.PlainText
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            color: "white"
            font { family: Tema.fonte; pixelSize: 16; weight: Font.DemiBold }
        }
        background: Rectangle {
            radius: height / 2
            color: Tema.destaque
            opacity: botao.down ? 0.7 : botao.hovered ? 0.85 : 1
            border { width: botao.visualFocus ? 2 : 0; color: Tema.texto }
        }
    }
}
