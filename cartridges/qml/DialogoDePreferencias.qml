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

    readonly property var abas: [
        { id: "general", titulo: "Geral", glifo: "" },
        { id: "session", titulo: "Personalização", glifo: "" },
        { id: "import", titulo: "Importação", glifo: "" },
        { id: "sgdb", titulo: "SteamGridDB", glifo: "" },
        { id: "conquistas", titulo: "Conquistas", glifo: "\ue734" }
    ]
    readonly property var rotulosDasAbas: abas.map(a => a.titulo)
    // A aba à vista; abre na que o `preferencias` pediu, se ela existe.
    property string aba: "general"
    // Quem tinha o foco ao abrir.
    property Item retorno: null
    // O texto da busca; com ele as abas somem e as cinco páginas aparecem juntas, só com as linhas que casam (D69).
    property alias filtro: campoDeBusca.text
    readonly property bool buscando: filtro !== ""
    // (Um grupo `soTemOutros`, sem linha buscável, não conta: hoje nenhum grupo das cinco páginas é assim.)
    // Quantos grupos têm linha à mostra (pela contagem de cada grupo, não pela altura: ela só se atualiza com o layout).
    readonly property int gruposAMostrar: {
        var n = 0
        for (var i = 0; i < paginas.children.length; ++i)
            for (var j = 0; j < paginas.children[i].children.length; ++j)
                if (paginas.children[i].children[j].linhasAMostrar > 0) ++n
        return n
    }
    // O texto vai ao singleton só depois de as páginas ficarem à vista: o `Column` só se reorganiza quando a
    // visibilidade efetiva de um filho muda, e uma linha escondida enquanto a página ainda estava escondida deixaria
    // a altura velha (rolagem com vazio no fim).
    onFiltroChanged: {
        rolagem.contentY = 0
        Qt.callLater(() => BuscaDasPreferencias.texto = filtro)
    }

    signal retornoPerdido()

    function dentro(item) {
        for (var p = item; p; p = p.parent) // `parent`: o `parentItem` do C++ não existe no QML
            if (p === dialogo) return true
        return false
    }
    function irParaAba(indice) {
        if (indice < 0 || indice >= abas.length) return
        aba = abas[indice].id
        repetidorDeAbas.itemAt(indice).forceActiveFocus(Qt.TabFocusReason)
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
            filtro = ""
            // O foco começa na aba à vista.
            for (var i = 0; i < abasLinha.children.length; ++i)
                if (abasLinha.children[i].atual === true) abasLinha.children[i].forceActiveFocus(Qt.TabFocusReason)
        } else {
            confirmacaoDosMetadados.visible = false
            filtro = ""
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
        for (var p = item; p; p = p.parent) // `parent`: o `parentItem` do C++ não existe no QML
            if (p === pai) return true
        return false
    }

    // Ctrl+F leva ao campo de busca (não com um modal por cima, nem com um aviso da camada dos avisos).
    property bool avisoAberto: false
    Shortcut {
        sequences: [StandardKey.Find] // Ctrl+F e a tecla Find do padrão; `sequence` ligaria só a primeira (aviso do Qt)
        enabled: dialogo.visible && cartao.enabled && !confirmacaoDosMetadados.visible && !dialogo.avisoAberto
        onActivated: campoDeBusca.forceActiveFocus(Qt.ShortcutFocusReason)
    }

    MouseArea { anchors.fill: parent } // o que está embaixo não recebe cliques

    component BotaoDaAba: Button {
        id: botao
        property string glifo
        property bool atual: false
        focusPolicy: Qt.StrongFocus
        Keys.onReturnPressed: click()
        Keys.onEnterPressed: click()
        implicitHeight: 34
        leftPadding: 8
        rightPadding: 8
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
        // Com o brilho por dispositivo ou o assistente das fitas por cima, o Tab não volta para cá.
        enabled: preferencias.brilhoPorDispositivo === null && preferencias.configuracaoDasFitas === null
            && preferencias.calibracao === null && !loginEpic.visible && !loginEa.visible

        Item {
            id: cabecalho
            width: parent.width
            // O campo de busca no alto; as abas abaixo dele, que somem durante a busca.
            height: dialogo.buscando ? 56 : 104

            TextField {
                id: campoDeBusca
                objectName: "campoDeBuscaDasPreferencias"
                anchors { left: parent.left; leftMargin: 12; right: botaoFechar.left; rightMargin: 8; top: parent.top; topMargin: 11 }
                height: 34
                leftPadding: 34
                placeholderText: "Buscar nas Preferências"
                placeholderTextColor: Tema.textoSecundario
                color: Tema.texto
                selectByMouse: true
                font { family: Tema.fonte; pixelSize: 14 }
                Accessible.name: "Buscar nas Preferências"
                // Esc com texto limpa a busca; sem texto, sobe ao diálogo e fecha.
                Keys.onEscapePressed: event => {
                    event.accepted = text !== ""
                    if (event.accepted) text = ""
                }
                background: Rectangle {
                    radius: 6
                    color: Tema.superficie
                    border { width: campoDeBusca.activeFocus ? 2 : 1; color: campoDeBusca.activeFocus ? Tema.destaque : Tema.borda }
                }
                Text {
                    anchors { left: parent.left; leftMargin: 10; verticalCenter: parent.verticalCenter }
                    text: ""  // buscar
                    textFormat: Text.PlainText
                    color: Tema.textoSecundario
                    font { family: Tema.fonteDeIcones; pixelSize: 14 }
                }
            }

            Row {
                id: abasLinha
                objectName: "abas"
                visible: !dialogo.buscando
                anchors { left: parent.left; leftMargin: 12; top: parent.top; topMargin: 56 }
                spacing: 4
                Repeater {
                    id: repetidorDeAbas
                    model: dialogo.abas
                    BotaoDaAba {
                        required property var modelData
                        required property int index
                        // As setas trocam de aba e levam o foco junto (sem dar a volta nas pontas).
                        Keys.onLeftPressed: dialogo.irParaAba(index - 1)
                        Keys.onRightPressed: dialogo.irParaAba(index + 1)
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
                anchors { right: parent.right; rightMargin: 12; top: parent.top; topMargin: 11 }
                focusPolicy: Qt.StrongFocus
                implicitWidth: 34
                implicitHeight: 34
                Keys.onReturnPressed: click()
                Keys.onEnterPressed: click()
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
            objectName: "rolagemDasPreferencias"
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

                PaginaGeral { visible: dialogo.buscando || dialogo.aba === "general" }
                PaginaDePersonalizacao { visible: dialogo.buscando || dialogo.aba === "session" }
                PaginaDeImportacao { visible: dialogo.buscando || dialogo.aba === "import" }
                PaginaDoSteamGridDB { visible: dialogo.buscando || dialogo.aba === "sgdb" }
                PaginaDasConquistas { visible: dialogo.buscando || dialogo.aba === "conquistas" }
            }
        }

        // Sem linha à vista, as páginas ficam com altura zero (cada grupo sem linha some).
        EstadoVazio {
            objectName: "estadoSemResultadoDasPreferencias"
            anchors { left: parent.left; right: parent.right; top: cabecalho.bottom; bottom: parent.bottom }
            visible: dialogo.buscando && dialogo.gruposAMostrar === 0
            glifo: ""
            titulo: "Nenhum resultado encontrado"
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
    BrilhoPorDispositivo {}
    ConfiguracaoDasFitas {}
    AssistenteDeCalibracao {}
    // As janelas de login das contas, por cima das Preferências (que ficam apagadas enquanto uma está aberta).
    JanelaDeLogin {
        id: loginEpic
        objectName: "janelaDeLoginEpic"
        login: preferencias.contas ? preferencias.contas.loginEpic : null
    }
    JanelaDeLogin {
        id: loginEa
        objectName: "janelaDeLoginEa"
        login: preferencias.contas ? preferencias.contas.loginEa : null
    }

    Connections {
        target: preferencias.biblioteca
        function onPerguntar(corpo) {
            confirmacaoDosMetadados.corpo = corpo
            confirmacaoDosMetadados.abrir()
        }
    }
}
