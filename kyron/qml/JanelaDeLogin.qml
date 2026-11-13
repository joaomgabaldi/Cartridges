import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// A janela de login da EA e da Epic; só desenha, o estado é do `login` (kyron/modelos/contas.py). O que a loja
// devolve e o texto colado são de terceiros: PlainText.
MolduraDoDialogo {
    id: janela

    property var login: null
    readonly property Item campoAtual: login !== null && login.multilinha ? campoDeVariasLinhas : campoDeUmaLinha

    aberto: !!login && login.aberto
    largura: 460
    focoInicial: campoAtual
    nomeAcessivel: login ? login.titulo : ""
    onFecharPedido: if (login) login.fechar()

    // Só o campo à vista é sincronizado: o de uma linha, escondido, cortaria em 32767 caracteres e devolveria o corte ao
    // modelo.
    Connections {
        target: janela.login
        function onMudou() {
            if (janela.login.texto !== janela.campoAtual.text) janela.campoAtual.text = janela.login.texto
        }
    }

    CabecalhoDoDialogo {
        titulo: janela.login ? janela.login.titulo : ""
        objetoDoTitulo: "tituloDoLogin"
        onFechar: if (janela.login) janela.login.fechar()
    }

    ColumnLayout {
        Layout.fillWidth: true
        Layout.topMargin: 12
        Layout.leftMargin: 24
        Layout.rightMargin: 24
        Layout.bottomMargin: 24
        spacing: janela.login !== null && janela.login.multilinha ? 12 : 18

        Text {
            objectName: "passosDoLogin"
            Layout.fillWidth: true
            text: janela.login ? janela.login.passos.join("\n") : ""
            textFormat: Text.PlainText
            wrapMode: Text.Wrap
            lineHeightMode: Text.FixedHeight
            lineHeight: Tema.alturaDoCorpo
            color: Tema.texto
            font { family: Tema.fonte; pixelSize: Tema.corpo }
        }
        Text {
            objectName: "rotuloDoCampoDoLogin"
            Layout.fillWidth: true
            visible: janela.login !== null && janela.login.multilinha
            text: janela.login ? janela.login.rotuloDoCampo : ""
            textFormat: Text.PlainText
            color: Tema.texto
            font { family: Tema.fonte; pixelSize: Tema.corpo; weight: Tema.pesoForte }
        }

        GrupoDeLinhas {
            Layout.fillWidth: true
            visible: janela.login !== null && !janela.login.multilinha
            LinhaDeTexto {
                id: campoDeUmaLinha
                objectName: "campoDeUmaLinha"
                titulo: janela.login ? janela.login.rotuloDoCampo : ""
                enabled: janela.login !== null && !janela.login.ocupada
                onTextChanged: if (janela.login && janela.campoAtual === campoDeUmaLinha && janela.login.texto !== text) janela.login.texto = text
                onConfirmado: if (janela.login) janela.login.conectar()
            }
        }

        Rectangle {
            objectName: "rolagemDoLogin"
            Layout.fillWidth: true
            Layout.minimumHeight: 160
            Layout.preferredHeight: 160
            visible: janela.login !== null && janela.login.multilinha
            color: Tema.vista
            border { width: 1; color: Tema.borda }
            clip: true

            Flickable {
                id: rolagem
                anchors { fill: parent; margins: 1 }
                contentWidth: width
                contentHeight: campoDeVariasLinhas.implicitHeight
                boundsBehavior: Flickable.StopAtBounds
                RolagemDaRoda { alvo: rolagem }
                clip: true
                ScrollBar.vertical: BarraDeRolagem {}

                TextArea.flickable: TextArea {
                    id: campoDeVariasLinhas
                    objectName: "campoDeVariasLinhas"
                    enabled: janela.login !== null && !janela.login.ocupada
                    wrapMode: TextArea.Wrap
                    selectByMouse: true
                    ContextMenu.menu: MenuDeTexto { campo: campoDeVariasLinhas }
                    padding: 6
                    color: Tema.texto
                    selectionColor: Qt.alpha(Tema.destaque, 0.25)
                    selectedTextColor: Tema.texto
                    font { family: Tema.fonte; pixelSize: Tema.corpo }
                    background: null
                    Accessible.name: janela.login ? janela.login.rotuloDoCampo : ""
                    onTextChanged: if (janela.login && janela.campoAtual === campoDeVariasLinhas && janela.login.texto !== text) janela.login.texto = text
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
            lineHeightMode: Text.FixedHeight
            lineHeight: Tema.alturaDoCorpo
            color: Tema.erro
            font { family: Tema.fonte; pixelSize: Tema.corpo }
            Accessible.role: Accessible.AlertMessage
            Accessible.name: text
        }
        TextEdit {
            objectName: "enderecoDoLogin"
            Layout.fillWidth: true
            visible: janela.login !== null && janela.login.enderecoVisivel
            text: janela.login ? janela.login.endereco : ""
            textFormat: TextEdit.PlainText
            readOnly: true
            selectByMouse: true
            wrapMode: TextEdit.WrapAnywhere
            color: Tema.texto
            selectionColor: Qt.alpha(Tema.destaque, 0.25)
            selectedTextColor: Tema.texto
            font { family: Tema.fonte; pixelSize: Tema.corpo }
            Accessible.name: text
        }

        RowLayout {
            Layout.alignment: Qt.AlignRight
            spacing: 12

            Girador {
                objectName: "indicadorDoLogin"
                Layout.alignment: Qt.AlignVCenter
                visible: janela.login !== null && janela.login.ocupada
                running: visible
                implicitWidth: 16
                implicitHeight: 16
                Accessible.name: "Conectando"
            }
            Botao {
                objectName: "botaoDaPaginaDoLogin"
                text: janela.login ? janela.login.botaoDaPagina : ""
                enabled: janela.login !== null && !janela.login.ocupada
                onClicked: if (janela.login) janela.login.abrirPagina()
            }
            Botao {
                objectName: "botaoCancelarLogin"
                text: "Cancelar"
                onClicked: if (janela.login) janela.login.fechar()
            }
            Botao {
                objectName: "botaoConectarLogin"
                text: "Conectar"
                estilo: "sugestao"
                enabled: janela.login !== null && janela.login.podeConectar
                onClicked: if (janela.login) janela.login.conectar()
            }
        }
    }
}
