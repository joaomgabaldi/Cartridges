import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import QtQuick.Window

// A janela de login da EA e da Epic: os passos, o campo onde se cola o que a loja mostrou, o erro e os botões. Só desenha:
// o que ela mostra e faz é o `login` (um `LoginDaLoja`, cartridges/modelos/contas.py); sem `login`, ela some.
// Modal para o mouse e o teclado, como os outros diálogos (D38); cobre o item pai. Esc e "Cancelar" fecham; Enter no
// campo de uma linha conecta. O que a loja devolve e o texto colado são de terceiros: sempre PlainText.
Rectangle {
    id: janela

    property var login: null
    // Quem tinha o foco ao abrir.
    property Item retorno: null
    readonly property Item campoAtual: login !== null && login.multilinha ? campoDeVariasLinhas : campoDeUmaLinha

    anchors.fill: parent
    z: 10
    visible: login !== null && login.aberto
    color: "#80000000"
    Keys.onEscapePressed: janela.login.fechar()
    // Modal para o teclado: nenhuma tecla chega à tela de trás.
    Keys.onPressed: event => event.accepted = true

    onVisibleChanged: {
        if (visible) {
            retorno = Window.window ? Window.window.activeFocusItem : null
            campoAtual.forceActiveFocus(Qt.TabFocusReason)
        } else {
            Qt.callLater(devolverAoRetorno)
        }
    }
    function devolverAoRetorno() {
        if (!visible && retorno && retorno.visible && retorno.enabled) retorno.forceActiveFocus(Qt.TabFocusReason)
    }

    // O texto do modelo (a recusa o limpa) e o do campo andam juntos.
    Connections {
        target: janela.login
        function onMudou() {
            if (janela.login.texto !== campoDeUmaLinha.text) campoDeUmaLinha.text = janela.login.texto
            if (janela.login.texto !== campoDeVariasLinhas.text) campoDeVariasLinhas.text = janela.login.texto
        }
    }

    MouseArea { anchors.fill: parent } // o que está embaixo não recebe cliques

    component BotaoDoLogin: Button {
        id: botao
        property bool destaque: false
        focusPolicy: Qt.StrongFocus
        implicitHeight: 34
        leftPadding: 18
        rightPadding: 18
        contentItem: Text {
            text: botao.text
            textFormat: Text.PlainText
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            color: botao.destaque ? "white" : Tema.texto
            opacity: botao.enabled ? 1 : 0.5
            font { family: Tema.fonte; pixelSize: 14 }
        }
        background: Rectangle {
            radius: 6
            color: botao.destaque ? Tema.destaque : Tema.superficie
            opacity: !botao.enabled ? 0.5 : botao.down ? 0.75 : botao.hovered ? 0.9 : 1
            border { width: botao.visualFocus ? 2 : 1; color: botao.visualFocus ? Tema.texto : Tema.borda }
        }
    }

    Rectangle {
        anchors.centerIn: parent
        width: Math.min(460, parent.width - 48)
        height: coluna.implicitHeight + 48
        radius: 8
        color: Tema.fundo
        border.color: Tema.botaoSobre

        ColumnLayout {
            id: coluna
            anchors { left: parent.left; right: parent.right; top: parent.top; margins: 24 }
            spacing: 14

            Text {
                objectName: "tituloDoLogin"
                Layout.fillWidth: true
                text: janela.login ? janela.login.titulo : ""
                textFormat: Text.PlainText
                wrapMode: Text.Wrap
                color: Tema.texto
                font { family: Tema.fonte; pixelSize: 18; weight: Font.DemiBold }
                Accessible.role: Accessible.Heading
                Accessible.name: text
            }
            Text {
                objectName: "passosDoLogin"
                Layout.fillWidth: true
                text: janela.login ? janela.login.passos.join("\n") : ""
                textFormat: Text.PlainText
                wrapMode: Text.Wrap
                color: Tema.texto
                font { family: Tema.fonte; pixelSize: 14 }
            }
            Text {
                objectName: "rotuloDoCampoDoLogin"
                Layout.fillWidth: true
                text: janela.login ? janela.login.rotuloDoCampo : ""
                textFormat: Text.PlainText
                color: Tema.texto
                font { family: Tema.fonte; pixelSize: 14; weight: Font.Bold }
            }

            // O campo de uma linha (o código da Epic): Enter conecta.
            TextField {
                id: campoDeUmaLinha
                objectName: "campoDeUmaLinha"
                Layout.fillWidth: true
                visible: janela.login !== null && !janela.login.multilinha
                enabled: janela.login !== null && !janela.login.ocupada
                selectByMouse: true
                color: Tema.texto
                selectionColor: Tema.destaque
                selectedTextColor: "white"
                font { family: Tema.fonte; pixelSize: 15 }
                leftPadding: 10
                rightPadding: 10
                implicitHeight: 38
                Accessible.name: janela.login ? janela.login.rotuloDoCampo : ""
                onTextChanged: if (janela.login && janela.login.texto !== text) janela.login.texto = text
                onAccepted: if (janela.login) janela.login.conectar()
                background: Rectangle {
                    radius: 6
                    color: Tema.superficie
                    border { width: campoDeUmaLinha.activeFocus ? 2 : 1; color: campoDeUmaLinha.activeFocus ? Tema.destaque : Tema.borda }
                }
            }

            // O campo de várias linhas (o pedido copiado do navegador): rolagem de pelo menos 160 de altura.
            Rectangle {
                objectName: "rolagemDoLogin"
                Layout.fillWidth: true
                Layout.minimumHeight: 160
                Layout.preferredHeight: 160
                visible: janela.login !== null && janela.login.multilinha
                radius: 6
                color: Tema.superficie
                border { width: campoDeVariasLinhas.activeFocus ? 2 : 1; color: campoDeVariasLinhas.activeFocus ? Tema.destaque : Tema.borda }
                clip: true

                Flickable {
                    id: rolagem
                    anchors { fill: parent; margins: 2 }
                    contentWidth: width
                    contentHeight: campoDeVariasLinhas.implicitHeight
                    boundsBehavior: Flickable.StopAtBounds
                    clip: true
                    ScrollBar.vertical: BarraDeRolagem {}

                    TextArea.flickable: TextArea {
                        id: campoDeVariasLinhas
                        objectName: "campoDeVariasLinhas"
                        enabled: janela.login !== null && !janela.login.ocupada
                        wrapMode: TextArea.WrapAnywhere
                        selectByMouse: true
                        padding: 8
                        color: Tema.texto
                        selectionColor: Tema.destaque
                        selectedTextColor: "white"
                        font { family: Tema.fonte; pixelSize: 14 }
                        background: null
                        Accessible.name: janela.login ? janela.login.rotuloDoCampo : ""
                        onTextChanged: if (janela.login && janela.login.texto !== text) janela.login.texto = text
                    }
                }
            }

            Text {
                objectName: "erroDoLogin"
                Layout.fillWidth: true
                visible: text !== ""
                text: janela.login ? janela.login.erro : ""
                textFormat: Text.PlainText
                wrapMode: Text.Wrap
                color: Tema.erro
                font { family: Tema.fonte; pixelSize: 14 }
                Accessible.role: Accessible.AlertMessage
                Accessible.name: text
            }
            // Sem navegador, o código só aparece na página de redirecionamento: o endereço fica à mostra e selecionável.
            TextEdit {
                objectName: "enderecoDoLogin"
                Layout.fillWidth: true
                visible: janela.login !== null && janela.login.enderecoVisivel
                text: janela.login ? janela.login.endereco : ""
                textFormat: TextEdit.PlainText
                readOnly: true
                selectByMouse: true
                wrapMode: TextEdit.WrapAnywhere
                color: Tema.textoSecundario
                selectionColor: Tema.destaque
                selectedTextColor: "white"
                font { family: Tema.fonte; pixelSize: 12 }
                Accessible.name: text
            }

            RowLayout {
                Layout.alignment: Qt.AlignRight
                spacing: 12

                BusyIndicator {
                    objectName: "indicadorDoLogin"
                    visible: janela.login !== null && janela.login.ocupada
                    running: visible
                    implicitWidth: 24
                    implicitHeight: 24
                    Accessible.name: "Conectando"
                }
                BotaoDoLogin {
                    objectName: "botaoDaPaginaDoLogin"
                    text: janela.login ? janela.login.botaoDaPagina : ""
                    enabled: janela.login !== null && !janela.login.ocupada
                    onClicked: janela.login.abrirPagina()
                }
                BotaoDoLogin {
                    objectName: "botaoCancelarLogin"
                    text: "Cancelar"
                    onClicked: janela.login.fechar()
                }
                BotaoDoLogin {
                    objectName: "botaoConectarLogin"
                    text: "Conectar"
                    destaque: true
                    enabled: janela.login !== null && janela.login.podeConectar
                    onClicked: janela.login.conectar()
                }
            }
        }
    }
}
