import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Window

// O seletor do jogo da Steam: um campo de busca e a lista de candidatos da loja.
// Só desenha: a busca e a escolha são do `seletor` (SeletorDaSteam, cartridges/modelos/seletores.py).
// Modal para o mouse, o teclado e o controle (abre por cima do diálogo de edição, que fica desabilitado);
// o foco volta ao botão que o abriu.
Rectangle {
    id: seletorDaSteam

    property QtObject seletor

    // Quem tinha o foco ao abrir: volta a tê-lo ao fechar.
    property Item retorno: null
    signal retornoPerdido()

    anchors.fill: parent
    z: 5
    visible: seletor.aberto
    color: "#80000000"
    Keys.onEscapePressed: seletor.fechar()
    // Modal para o teclado e o controle: nenhuma tecla chega ao diálogo de trás.
    Keys.onPressed: event => event.accepted = true

    onVisibleChanged: {
        if (visible) {
            retorno = Window.window ? Window.window.activeFocusItem : null
            campoDeBusca.forceActiveFocus(Qt.TabFocusReason)
        } else {
            // Depois de o diálogo de trás voltar a ficar habilitado.
            Qt.callLater(devolverAoRetorno)
        }
    }
    function devolverAoRetorno() {
        if (visible) return
        if (retorno && retorno.visible && retorno.enabled) retorno.forceActiveFocus(Qt.TabFocusReason)
        else seletorDaSteam.retornoPerdido()
    }

    // A seta numa linha leva o foco à vizinha; para cima da primeira, ao campo de busca.
    function moverFoco(indice) {
        if (indice < 0) { campoDeBusca.forceActiveFocus(Qt.BacktabFocusReason); return }
        if (indice >= lista.count) return
        lista.positionViewAtIndex(indice, ListView.Contain)
        var item = lista.itemAtIndex(indice)
        if (item) item.forceActiveFocus(Qt.TabFocusReason)
    }

    MouseArea { anchors.fill: parent } // o que está embaixo não recebe cliques

    Rectangle {
        anchors.centerIn: parent
        width: Math.min(560, parent.width - 48)
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
                objectName: seletorDaSteam.objectName + "Fechar"
                anchors { left: parent.left; leftMargin: 12; verticalCenter: parent.verticalCenter }
                text: "Fechar"
                focusPolicy: Qt.StrongFocus
                implicitHeight: 34
                leftPadding: 18
                rightPadding: 18
                Keys.onReturnPressed: click()
                Keys.onEnterPressed: click()
                onClicked: seletorDaSteam.seletor.fechar()
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
                objectName: seletorDaSteam.objectName + "Titulo"
                anchors { left: botaoFechar.right; right: parent.right; leftMargin: 8; rightMargin: 12 + botaoFechar.width + 8; verticalCenter: parent.verticalCenter }
                text: "Escolher jogo na Steam"
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
                objectName: seletorDaSteam.objectName + "Campo"
                anchors { fill: parent; leftMargin: 12; rightMargin: 12 }
                selectByMouse: true
                placeholderText: "Buscar jogo…"
                placeholderTextColor: Tema.textoSecundario
                color: Tema.texto
                selectionColor: Tema.destaque
                selectedTextColor: "white"
                font { family: Tema.fonte; pixelSize: 15 }
                background: null
                verticalAlignment: TextInput.AlignVCenter
                text: seletorDaSteam.seletor.busca
                Accessible.name: "Buscar jogo"
                onTextEdited: seletorDaSteam.seletor.busca = text
                onAccepted: seletorDaSteam.seletor.buscarAgora()
                Keys.onDownPressed: seletorDaSteam.moverFoco(0)
            }
        }

        Item {
            anchors { left: parent.left; right: parent.right; top: campo.bottom; bottom: parent.bottom; topMargin: 8 }

            BusyIndicator {
                objectName: seletorDaSteam.objectName + "Carregando"
                anchors.centerIn: parent
                width: 32
                height: 32
                running: visible
                visible: seletorDaSteam.seletor.buscando && !seletorDaSteam.seletor.vazio
            }

            EstadoVazio {
                objectName: seletorDaSteam.objectName + "Vazio"
                anchors.fill: parent
                visible: seletorDaSteam.seletor.vazio
                glifo: "\uE721"  // buscar
                titulo: seletorDaSteam.seletor.tituloDoEstado
                descricao: seletorDaSteam.seletor.descricaoDoEstado
            }

            ListView {
                id: lista
                objectName: seletorDaSteam.objectName + "Lista"
                anchors { fill: parent; leftMargin: 12; rightMargin: 12 }
                visible: !seletorDaSteam.seletor.vazio && !seletorDaSteam.seletor.buscando
                model: seletorDaSteam.seletor
                clip: true
                spacing: 4
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: BarraDeRolagem {}

                delegate: Button {
                    id: linha
                    required property int index
                    required property string nome
                    required property string appid
                    required property string ano
                    objectName: seletorDaSteam.objectName + "Linha" + index
                    width: lista.width
                    implicitHeight: 58
                    focusPolicy: Qt.StrongFocus
                    Accessible.name: nome
                    Accessible.description: "ID na Steam: " + appid
                    Accessible.role: Accessible.Button
                    Keys.onReturnPressed: click()
                    Keys.onEnterPressed: click()
                    Keys.onDownPressed: seletorDaSteam.moverFoco(index + 1)
                    Keys.onUpPressed: seletorDaSteam.moverFoco(index - 1)
                    onClicked: seletorDaSteam.seletor.escolher(index)

                    background: Rectangle {
                        radius: 8
                        color: linha.down ? Tema.pressionado : linha.hovered ? Tema.botaoSobre : Tema.superficie
                        border { width: linha.visualFocus ? 2 : 1; color: linha.visualFocus ? Tema.destaque : Tema.borda }
                    }
                    contentItem: Item {
                        Column {
                            anchors { left: parent.left; leftMargin: 8; right: seta.left; rightMargin: 8; verticalCenter: parent.verticalCenter }
                            Text {
                                width: parent.width
                                text: linha.nome
                                textFormat: Text.PlainText
                                elide: Text.ElideRight
                                color: Tema.texto
                                font { family: Tema.fonte; pixelSize: 15 }
                            }
                            Text {
                                width: parent.width
                                text: "ID na Steam: " + linha.appid + (linha.ano !== "" ? " (" + linha.ano + ")" : "")
                                textFormat: Text.PlainText
                                elide: Text.ElideRight
                                color: Tema.textoSecundario
                                font { family: Tema.fonte; pixelSize: 12 }
                            }
                        }
                        Text {
                            id: seta
                            anchors { right: parent.right; rightMargin: 8; verticalCenter: parent.verticalCenter }
                            text: "\uE76C"  // seta para a direita
                            textFormat: Text.PlainText
                            color: Tema.textoSecundario
                            font { family: Tema.fonteDeIcones; pixelSize: 12 }
                        }
                    }
                }
            }
        }
    }
}
