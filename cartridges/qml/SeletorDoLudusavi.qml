import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Window

// O seletor do jogo do Ludusavi: "Nenhum (desliga o backup)", um campo de busca e a lista de jogos do manifesto.
// Só desenha: a leitura da lista e o filtro são do `seletor` (SeletorDoLudusavi, cartridges/modelos/seletores.py).
// Modal para o mouse, o teclado e o controle (abre por cima do diálogo de edição, que fica desabilitado);
// o foco volta ao botão que o abriu.
Rectangle {
    id: seletorDoLudusavi

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
        else seletorDoLudusavi.retornoPerdido()
    }

    // A seta numa linha leva o foco à vizinha; para cima da primeira, ao botão "Nenhum".
    function moverFoco(indice) {
        if (indice < 0) { botaoNenhum.forceActiveFocus(Qt.BacktabFocusReason); return }
        if (indice >= lista.count) return
        lista.positionViewAtIndex(indice, ListView.Contain)
        var item = lista.itemAtIndex(indice)
        if (item) item.forceActiveFocus(Qt.TabFocusReason)
    }

    // O jogo que já estava escolhido aparece à vista quando a lista chega.
    Connections {
        target: seletorDoLudusavi.seletor
        function onEstadoChanged() {
            if (!seletorDoLudusavi.seletor.carregando && seletorDoLudusavi.seletor.busca === "" && seletorDoLudusavi.seletor.indiceAtual >= 0)
                lista.positionViewAtIndex(seletorDoLudusavi.seletor.indiceAtual, ListView.Center)
        }
    }

    MouseArea { anchors.fill: parent } // o que está embaixo não recebe cliques

    Rectangle {
        anchors.centerIn: parent
        width: Math.min(480, parent.width - 48)
        height: Math.min(560, parent.height - 48)
        radius: 8
        color: Tema.fundo
        border.color: Tema.botaoSobre
        clip: true

        // O cabeçalho vem primeiro: a ordem do Tab é "Fechar", o campo, "Nenhum" e as linhas.
        Rectangle {
            id: cabecalho
            anchors { left: parent.left; right: parent.right; top: parent.top }
            height: 56
            color: Tema.fundo

            Button {
                id: botaoFechar
                objectName: seletorDoLudusavi.objectName + "Fechar"
                anchors { left: parent.left; leftMargin: 12; verticalCenter: parent.verticalCenter }
                text: "Fechar"
                focusPolicy: Qt.StrongFocus
                implicitHeight: 34
                leftPadding: 18
                rightPadding: 18
                Keys.onReturnPressed: click()
                Keys.onEnterPressed: click()
                onClicked: seletorDoLudusavi.seletor.fechar()
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
                objectName: seletorDoLudusavi.objectName + "Titulo"
                anchors { left: botaoFechar.right; right: parent.right; leftMargin: 8; rightMargin: 12 + botaoFechar.width + 8; verticalCenter: parent.verticalCenter }
                text: "Jogo no Ludusavi"
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
                objectName: seletorDoLudusavi.objectName + "Campo"
                anchors { fill: parent; leftMargin: 12; rightMargin: 12 }
                selectByMouse: true
                placeholderText: "Buscar jogo"
                placeholderTextColor: Tema.textoSecundario
                color: Tema.texto
                selectionColor: Tema.destaque
                selectedTextColor: "white"
                font { family: Tema.fonte; pixelSize: 15 }
                background: null
                verticalAlignment: TextInput.AlignVCenter
                text: seletorDoLudusavi.seletor.busca
                Accessible.name: "Buscar jogo"
                onTextEdited: seletorDoLudusavi.seletor.busca = text
                Keys.onDownPressed: botaoNenhum.forceActiveFocus(Qt.TabFocusReason)
            }
        }

        Button {
            id: botaoNenhum
            objectName: seletorDoLudusavi.objectName + "Nenhum"
            anchors { left: parent.left; right: parent.right; top: campo.bottom; leftMargin: 12; rightMargin: 12; topMargin: 8 }
            implicitHeight: 48
            focusPolicy: Qt.StrongFocus
            text: "Nenhum (desliga o backup)"
            Accessible.name: text
            Keys.onReturnPressed: click()
            Keys.onEnterPressed: click()
            Keys.onUpPressed: campoDeBusca.forceActiveFocus(Qt.BacktabFocusReason)
            Keys.onDownPressed: seletorDoLudusavi.moverFoco(0)
            onClicked: seletorDoLudusavi.seletor.escolherNenhum()
            background: Rectangle {
                radius: 8
                color: botaoNenhum.down ? Tema.pressionado : botaoNenhum.hovered ? Tema.botaoSobre : Tema.superficie
                border { width: botaoNenhum.visualFocus ? 2 : 1; color: botaoNenhum.visualFocus ? Tema.destaque : Tema.borda }
            }
            contentItem: Text {
                leftPadding: 8
                text: botaoNenhum.text
                textFormat: Text.PlainText
                verticalAlignment: Text.AlignVCenter
                color: Tema.texto
                font { family: Tema.fonte; pixelSize: 15 }
            }
        }

        Item {
            anchors { left: parent.left; right: parent.right; top: botaoNenhum.bottom; bottom: parent.bottom; topMargin: 8 }

            BusyIndicator {
                objectName: seletorDoLudusavi.objectName + "Carregando"
                anchors.centerIn: parent
                width: 32
                height: 32
                running: visible
                visible: seletorDoLudusavi.seletor.carregando
            }

            EstadoVazio {
                objectName: seletorDoLudusavi.objectName + "Vazio"
                anchors.fill: parent
                visible: seletorDoLudusavi.seletor.erro || seletorDoLudusavi.seletor.vazio
                glifo: seletorDoLudusavi.seletor.erro ? "\uE7BA" : "\uE721"  // aviso ou buscar
                titulo: seletorDoLudusavi.seletor.tituloDoEstado
            }

            ListView {
                id: lista
                objectName: seletorDoLudusavi.objectName + "Lista"
                anchors { fill: parent; leftMargin: 12; rightMargin: 12 }
                visible: !seletorDoLudusavi.seletor.carregando && !seletorDoLudusavi.seletor.erro
                model: seletorDoLudusavi.seletor
                clip: true
                reuseItems: true
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: BarraDeRolagem {}

                delegate: Button {
                    id: linha
                    required property int index
                    required property string nome
                    objectName: seletorDoLudusavi.objectName + "Linha" + index
                    width: lista.width
                    implicitHeight: 40
                    focusPolicy: Qt.StrongFocus
                    Accessible.name: nome
                    Accessible.role: Accessible.Button
                    Keys.onReturnPressed: click()
                    Keys.onEnterPressed: click()
                    Keys.onDownPressed: seletorDoLudusavi.moverFoco(index + 1)
                    Keys.onUpPressed: seletorDoLudusavi.moverFoco(index - 1)
                    onClicked: seletorDoLudusavi.seletor.escolher(index)

                    background: Rectangle {
                        radius: 6
                        color: linha.down ? Tema.pressionado : linha.hovered ? Tema.botaoSobre : "transparent"
                        border { width: linha.visualFocus ? 2 : 0; color: Tema.destaque }
                    }
                    contentItem: Text {
                        leftPadding: 8
                        rightPadding: 8
                        text: linha.nome
                        textFormat: Text.PlainText
                        elide: Text.ElideRight
                        verticalAlignment: Text.AlignVCenter
                        // O jogo já escolhido fica em destaque.
                        color: linha.index === seletorDoLudusavi.seletor.indiceAtual ? Tema.destaque : Tema.texto
                        font { family: Tema.fonte; pixelSize: 15; weight: linha.index === seletorDoLudusavi.seletor.indiceAtual ? Font.DemiBold : Font.Normal }
                    }
                }
            }
        }
    }
}
