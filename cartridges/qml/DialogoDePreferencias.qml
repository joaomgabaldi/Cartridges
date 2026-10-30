import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Window

// As Preferências: um modal dentro da janela, com abas no topo e uma página por aba. Só desenha: o que ele mostra e
// grava é o `preferencias` (cartridges/modelos/preferencias.py). Modal para o mouse, o teclado e o controle, como o de
// edição; o foco volta a quem o abriu.
Rectangle {
    id: dialogo
    objectName: "dialogoDePreferencias"

    Accessible.role: Accessible.Dialog
    Accessible.name: "Preferências"

    // shortcut: faltam as abas "Personalização" (Task 4 do plano 7) e "Conquistas" (Task 8); entram na ordem da `main`: Geral, Personalização, Importação, SteamGridDB, Conquistas. Sem página, a aba não aparece (nada de aba morta).
    readonly property var abas: [
        { id: "general", titulo: "Geral", glifo: "" },
        { id: "import", titulo: "Importação", glifo: "" },
        { id: "sgdb", titulo: "SteamGridDB", glifo: "" }
    ]
    readonly property var rotulosDasAbas: abas.map(a => a.titulo)
    // A aba à vista; abre na que o `preferencias` pediu, se ela existe.
    property string aba: "general"
    // Quem tinha o foco ao abrir.
    property Item retorno: null

    signal retornoPerdido()

    function dentro(item) {
        for (var p = item; p; p = p.parentItem)
            if (p === dialogo) return true
        return false
    }
    // O item com o foco fica à vista na rolagem.
    function mostrar(item) {
        var topo = item.mapToItem(rolagem.contentItem, 0, 0).y
        var base = topo + item.height
        if (topo < rolagem.contentY) rolagem.contentY = Math.max(0, topo - 8)
        else if (base > rolagem.contentY + rolagem.height) rolagem.contentY = base - rolagem.height + 8
    }
    // Depois da reação das outras bindings ao `aberto` (a página de trás volta a ficar habilitada).
    function devolverAoRetorno() {
        if (visible) return
        if (retorno && retorno.visible && retorno.enabled) retorno.forceActiveFocus(Qt.TabFocusReason)
        else dialogo.retornoPerdido()
    }

    anchors.fill: parent
    visible: preferencias.aberto
    color: "#80000000"
    Keys.onEscapePressed: preferencias.fechar()
    // Modal para o teclado e o controle: nenhuma tecla chega à página de trás.
    Keys.onPressed: event => event.accepted = true

    onVisibleChanged: {
        if (visible) {
            retorno = Window.window ? Window.window.activeFocusItem : null
            aba = abas.some(a => a.id === preferencias.pagina) ? preferencias.pagina : "general"
            rolagem.contentY = 0
            // O foco começa na aba à vista.
            for (var i = 0; i < abasLinha.children.length; ++i)
                if (abasLinha.children[i].atual === true) abasLinha.children[i].forceActiveFocus(Qt.TabFocusReason)
        } else {
            confirmacaoDosMetadados.visible = false
            Qt.callLater(devolverAoRetorno)
        }
    }

    Connections {
        target: dialogo.Window.window
        function onActiveFocusItemChanged() {
            var foco = dialogo.Window.window.activeFocusItem
            if (!dialogo.visible || !foco || !dialogo.dentro(foco) || !dialogo.contem(rolagem.contentItem, foco)) return
            dialogo.mostrar(foco)
        }
    }
    function contem(pai, item) {
        for (var p = item; p; p = p.parentItem)
            if (p === pai) return true
        return false
    }

    MouseArea { anchors.fill: parent } // o que está embaixo não recebe cliques

    component BotaoDaAba: Button {
        id: botao
        property string glifo
        property bool atual: false
        focusPolicy: Qt.StrongFocus
        implicitHeight: 34
        leftPadding: 12
        rightPadding: 12
        checkable: false
        Accessible.role: Accessible.PageTab
        Accessible.name: text
        contentItem: Row {
            spacing: 6
            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: botao.glifo
                textFormat: Text.PlainText
                color: botao.atual ? "white" : Tema.texto
                font { family: Tema.fonteDeIcones; pixelSize: 14 }
            }
            Text {
                anchors.verticalCenter: parent.verticalCenter
                text: botao.text
                textFormat: Text.PlainText
                color: botao.atual ? "white" : Tema.texto
                font { family: Tema.fonte; pixelSize: 14 }
            }
        }
        background: Rectangle {
            radius: 6
            color: botao.atual ? Tema.destaque : botao.down ? Tema.pressionado : botao.hovered ? Tema.botaoSobre : "transparent"
            border { width: botao.visualFocus ? 2 : 0; color: Tema.texto }
        }
    }

    Rectangle {
        id: cartao
        objectName: "cartaoDasPreferencias"
        anchors.centerIn: parent
        width: Math.min(640, parent.width - 48)
        height: Math.min(620, parent.height - 48)
        radius: 8
        color: Tema.fundo
        border.color: Tema.botaoSobre
        clip: true

        Item {
            id: cabecalho
            width: parent.width
            height: 56

            Row {
                id: abasLinha
                anchors { left: parent.left; leftMargin: 12; verticalCenter: parent.verticalCenter }
                spacing: 4
                Repeater {
                    model: dialogo.abas
                    BotaoDaAba {
                        required property var modelData
                        objectName: "aba-" + modelData.id
                        text: modelData.titulo
                        glifo: modelData.glifo
                        atual: dialogo.aba === modelData.id
                        onClicked: dialogo.aba = modelData.id
                    }
                }
            }

            Button {
                id: botaoFechar
                objectName: "botaoFecharPreferencias"
                anchors { right: parent.right; rightMargin: 12; verticalCenter: parent.verticalCenter }
                focusPolicy: Qt.StrongFocus
                implicitWidth: 34
                implicitHeight: 34
                Accessible.name: "Fechar"
                ToolTip.visible: hovered
                ToolTip.text: "Fechar"
                ToolTip.delay: 600
                onClicked: preferencias.fechar()
                contentItem: Text {
                    text: ""  // fechar
                    textFormat: Text.PlainText
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    color: Tema.texto
                    font { family: Tema.fonteDeIcones; pixelSize: 14 }
                }
                background: Rectangle {
                    radius: 6
                    color: botaoFechar.down ? Tema.pressionado : botaoFechar.hovered ? Tema.botaoSobre : "transparent"
                    border { width: botaoFechar.visualFocus ? 2 : 0; color: Tema.destaque }
                }
            }

            Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Tema.borda }
        }

        Flickable {
            id: rolagem
            anchors { left: parent.left; right: parent.right; top: cabecalho.bottom; bottom: parent.bottom }
            contentWidth: width
            contentHeight: paginas.implicitHeight + 32
            boundsBehavior: Flickable.StopAtBounds
            clip: true
            ScrollBar.vertical: BarraDeRolagem {}

            Column {
                id: paginas
                x: 16
                y: 16
                width: rolagem.width - 32

                PaginaGeral { visible: dialogo.aba === "general" }
                PaginaDeImportacao { visible: dialogo.aba === "import" }
                PaginaDoSteamGridDB { visible: dialogo.aba === "sgdb" }
            }
        }
    }

    // O escopo da atualização de metadados: a pergunta chega do `preferencias.biblioteca`.
    DialogoDeConfirmacao {
        id: confirmacaoDosMetadados
        objectName: "dialogoDosMetadados"
        titulo: "Atualizar metadados"
        rotuloConfirmar: "Buscar o que falta"
        rotuloAlternativo: "Buscar tudo"
        onConfirmado: preferencias.biblioteca.buscarMetadados(true)
        onAlternativo: preferencias.biblioteca.buscarMetadados(false)
    }
    Connections {
        target: preferencias.biblioteca
        function onPerguntar(corpo) {
            confirmacaoDosMetadados.corpo = corpo
            confirmacaoDosMetadados.abrir()
        }
    }
}
