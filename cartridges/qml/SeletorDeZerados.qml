import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Window

// "Adicionar a Jogos Zerados" (D85): um campo de busca na Steam e a lista dos desinstalados (ou dos resultados), num
// modal de 460×520. Só desenha: as regras, a busca e a escolha são do `modelo` (o `SeletorDeZerados`,
// cartridges/modelos/zerados_manuais.py). Nome de jogo e aviso, texto de terceiros, em PlainText. Modal para o mouse, o
// teclado e o controle (o fundo fica desabilitado); Esc fecha e o foco volta a quem abriu.
Rectangle {
    id: seletor
    objectName: "seletorDeZerados"

    property QtObject modelo
    // Quem tinha o foco ao abrir: volta a tê-lo ao fechar.
    property Item retorno: null
    signal retornoPerdido()

    Accessible.role: Accessible.Dialog
    Accessible.name: "Adicionar a Jogos Zerados"

    anchors.fill: parent
    z: 5
    visible: !!modelo && modelo.aberto
    color: "#80000000"
    Keys.onEscapePressed: modelo.fechar()
    // Modal para o teclado e o controle: nenhuma tecla chega à página de trás. O Tab passa, para circular.
    Keys.onPressed: event => event.accepted = event.key !== Qt.Key_Tab && event.key !== Qt.Key_Backtab

    function focarInicial() {
        if (visible) campoDeBusca.forceActiveFocus(Qt.TabFocusReason)
    }
    function devolverAoRetorno() {
        if (visible) return
        // Quem abriu pode ter perdido o foco para a janela quando o fundo ficou desabilitado: o foco vai à página à vista.
        if (retorno && retorno !== Window.contentItem && retorno.visible && retorno.enabled) retorno.forceActiveFocus(Qt.TabFocusReason)
        else seletor.retornoPerdido()
    }
    // A seta numa linha leva o foco à vizinha; para cima da primeira, ao campo de busca.
    function moverFoco(indice) {
        if (indice < 0) { campoDeBusca.forceActiveFocus(Qt.BacktabFocusReason); return }
        if (indice >= lista.count) return
        lista.positionViewAtIndex(indice, ListView.Contain)
        var item = lista.itemAtIndex(indice)
        if (item) item.forceActiveFocus(Qt.TabFocusReason)
    }

    onVisibleChanged: {
        if (visible) {
            retorno = Window.window ? Window.window.activeFocusItem : null
            campoDeBusca.text = ""
            // Adiado: o item acabou de ficar visível e só então aceita o foco.
            Qt.callLater(focarInicial)
        } else {
            // Depois de a página de trás voltar a ficar habilitada.
            Qt.callLater(devolverAoRetorno)
        }
    }

    MouseArea { anchors.fill: parent } // o que está embaixo não recebe cliques

    Rectangle {
        anchors.centerIn: parent
        width: Math.min(460, parent.width - 48)
        height: Math.min(520, parent.height - 48)
        radius: 8
        color: Tema.fundo
        border.color: Tema.botaoSobre
        clip: true

        // O cabeçalho vem primeiro: a ordem do Tab é "Fechar", o campo e as linhas.
        Rectangle {
            id: cabecalho
            anchors { left: parent.left; right: parent.right; top: parent.top }
            height: 56
            color: Tema.fundo

            Button {
                id: botaoFechar
                objectName: "zeradosFechar"
                anchors { left: parent.left; leftMargin: 12; verticalCenter: parent.verticalCenter }
                text: "Fechar"
                focusPolicy: Qt.StrongFocus
                implicitHeight: 34
                leftPadding: 18
                rightPadding: 18
                Keys.onReturnPressed: click()
                Keys.onEnterPressed: click()
                onClicked: seletor.modelo.fechar()
                contentItem: Text {
                    text: botaoFechar.text
                    textFormat: Text.PlainText
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    color: Tema.texto
                    font { family: Tema.fonte; pixelSize: 14 }
                }
                background: Rectangle {
                    radius: 6
                    color: Tema.superficie
                    opacity: botaoFechar.down ? 0.75 : botaoFechar.hovered ? 0.9 : 1
                    border { width: botaoFechar.visualFocus ? 2 : 1; color: botaoFechar.visualFocus ? Tema.texto : Tema.borda }
                }
            }
            Text {
                objectName: "zeradosTitulo"
                anchors { left: botaoFechar.right; right: parent.right; leftMargin: 8; rightMargin: 12 + botaoFechar.width + 8; verticalCenter: parent.verticalCenter }
                text: "Adicionar a Jogos Zerados"
                textFormat: Text.PlainText
                horizontalAlignment: Text.AlignHCenter
                elide: Text.ElideRight
                color: Tema.texto
                font { family: Tema.fonte; pixelSize: 16; weight: Font.DemiBold }
                Accessible.role: Accessible.Heading
                Accessible.name: text
            }
        }

        Rectangle {
            id: campo
            anchors { left: parent.left; right: parent.right; top: cabecalho.bottom; margins: 12; topMargin: 0 }
            height: 40
            radius: 8
            color: Tema.superficie
            border { width: campoDeBusca.activeFocus ? 2 : 1; color: campoDeBusca.activeFocus ? Tema.destaque : Tema.borda }

            TextField {
                id: campoDeBusca
                objectName: "zeradosCampo"
                anchors { fill: parent; leftMargin: 12; rightMargin: 12 }
                selectByMouse: true
                placeholderText: "Buscar na Steam"
                placeholderTextColor: Tema.textoSecundario
                color: Tema.texto
                selectionColor: Tema.destaque
                selectedTextColor: "white"
                font { family: Tema.fonte; pixelSize: 15 }
                background: null
                verticalAlignment: TextInput.AlignVCenter
                Accessible.name: "Buscar na Steam"
                // A busca na Steam só começa com Enter (a loja limita as requisições); apagar o campo volta aos desinstalados.
                onTextEdited: seletor.modelo.mudouBusca(text)
                onAccepted: seletor.modelo.buscar(text)
                Keys.onDownPressed: seletor.moverFoco(0)
            }
        }

        Text {
            id: aviso
            objectName: "zeradosAviso"
            anchors { left: parent.left; right: parent.right; top: campo.bottom; leftMargin: 16; rightMargin: 16; topMargin: 8 }
            visible: !!seletor.modelo && seletor.modelo.aviso !== ""
            height: visible ? implicitHeight : 0
            text: seletor.modelo ? seletor.modelo.aviso : ""
            textFormat: Text.PlainText
            wrapMode: Text.Wrap
            color: Tema.textoSecundario
            font { family: Tema.fonte; pixelSize: 13 }
        }

        Item {
            anchors { left: parent.left; right: parent.right; top: aviso.bottom; bottom: parent.bottom; topMargin: 8 }

            BusyIndicator {
                objectName: "zeradosCarregando"
                anchors.centerIn: parent
                width: 32
                height: 32
                running: visible
                visible: !!seletor.modelo && seletor.modelo.estado === "carregando"
            }

            EstadoVazio {
                objectName: "zeradosVazio"
                anchors.fill: parent
                visible: !!seletor.modelo && seletor.modelo.estado === "vazio"
                glifo: ""  // marca de seleção
                titulo: "Nenhum jogo disponível"
                descricao: "Busque um jogo na Steam para adicioná-lo."
            }

            ListView {
                id: lista
                objectName: "zeradosLista"
                anchors { fill: parent; leftMargin: 12; rightMargin: 12; bottomMargin: 12 }
                visible: !!seletor.modelo && seletor.modelo.estado === "lista"
                model: seletor.modelo ? seletor.modelo.linhas : []
                clip: true
                spacing: 4
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: BarraDeRolagem {}

                // Uma linha inativa continua alcançável pelas setas (o motivo é lido pelo leitor de tela), mas não age.
                delegate: Button {
                    id: linha
                    required property int index
                    required property var modelData
                    objectName: "zeradosLinha" + index
                    width: lista.width
                    implicitHeight: 58
                    focusPolicy: Qt.StrongFocus
                    opacity: modelData.ativa ? 1 : 0.5
                    Accessible.name: modelData.titulo
                    Accessible.description: modelData.subtitulo
                    Accessible.role: Accessible.Button
                    Keys.onReturnPressed: click()
                    Keys.onEnterPressed: click()
                    Keys.onDownPressed: seletor.moverFoco(index + 1)
                    Keys.onUpPressed: seletor.moverFoco(index - 1)
                    onClicked: if (modelData.ativa) seletor.modelo.escolher(modelData.chave)

                    background: Rectangle {
                        radius: 8
                        color: linha.down && linha.modelData.ativa ? Tema.pressionado : linha.hovered && linha.modelData.ativa ? Tema.botaoSobre : Tema.superficie
                        border { width: linha.visualFocus ? 2 : 1; color: linha.visualFocus ? Tema.destaque : Tema.borda }
                    }
                    contentItem: Item {
                        Column {
                            anchors { left: parent.left; leftMargin: 8; right: mais.left; rightMargin: 8; verticalCenter: parent.verticalCenter }
                            Text {
                                objectName: "zeradosLinha" + linha.index + "Titulo"
                                width: parent.width
                                text: linha.modelData.titulo
                                textFormat: Text.PlainText
                                elide: Text.ElideRight
                                color: Tema.texto
                                font { family: Tema.fonte; pixelSize: 15 }
                            }
                            Text {
                                objectName: "zeradosLinha" + linha.index + "Subtitulo"
                                width: parent.width
                                visible: text !== ""
                                text: linha.modelData.subtitulo
                                textFormat: Text.PlainText
                                elide: Text.ElideRight
                                color: Tema.textoSecundario
                                font { family: Tema.fonte; pixelSize: 12 }
                            }
                        }
                        Text {
                            id: mais
                            anchors { right: parent.right; rightMargin: 8; verticalCenter: parent.verticalCenter }
                            visible: linha.modelData.ativa
                            text: ""  // adicionar
                            textFormat: Text.PlainText
                            color: Tema.textoSecundario
                            font { family: Tema.fonteDeIcones; pixelSize: 14 }
                        }
                    }
                }
            }
        }
    }
}
