import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import QtQuick.Window

// As Preferências: cabeçalho com lupa, título e X, uma página por aba e a barra das abas no pé. Só desenha: o estado é do
// `preferencias` (cartridges/modelos/preferencias.py).
MolduraDoDialogo {
    id: dialogo
    objectName: "dialogoDePreferencias"

    readonly property var abas: [
        { id: "geral", titulo: "Geral", icone: "user-home" },
        { id: "controle", titulo: "Controle", icone: "input-gaming" },
        { id: "monitores", titulo: "Monitores", icone: "video-joined-displays" },
        { id: "iluminacao", titulo: "Iluminação", icone: "applications-engineering" },
        { id: "importacao", titulo: "Importação", icone: "document-save" },
        { id: "metadados", titulo: "Metadados e capas", icone: "image-x-generic" },
        { id: "conquistas", titulo: "Conquistas", icone: "starred" },
        { id: "contas", titulo: "Contas", icone: "user-home" },
        { id: "backup", titulo: "Backup", icone: "document-save" },
        { id: "aplicativo", titulo: "Aplicativo", icone: "applications-engineering" }
    ]
    readonly property var rotulosDasAbas: abas.map(a => a.titulo)
    property string aba: "geral"
    readonly property int indiceDaAba: Math.max(0, abas.findIndex(a => a.id === aba))
    property bool buscaAtiva: false
    property alias filtro: campoDeBusca.text
    readonly property bool buscando: filtro !== ""
    property var resultados: []
    property bool avisoAberto: false
    readonly property Item botaoFechar: cabecalho.botaoFechar

    aberto: preferencias.aberto
    largura: 640
    altura: 2000  // sem teto próprio: a janela limita
    nomeAcessivel: "Preferências"
    onFecharPedido: preferencias.fechar()

    onFiltroChanged: {
        rolagem.contentY = 0
        if (filtro !== "") buscaAtiva = true
        procurar()
    }
    onAbertoChanged: if (aberto) {
        aba = abas.some(a => a.id === preferencias.pagina) ? preferencias.pagina : "geral"
        rolagem.contentY = 0
        filtro = ""
        buscaAtiva = false
        // O foco começa no X: o primeiro Tab vai à primeira linha habilitada da página, e não pelas abas.
        focoInicial = cabecalho.botaoFechar
    } else {
        confirmacaoDosMetadados.aberto = false
        filtro = ""
        buscaAtiva = false
    }

    function mostrar(item) {
        var topo = item.mapToItem(rolagem.contentItem, 0, 0).y
        var base = topo + item.height
        if (topo < rolagem.contentY) rolagem.contentY = Math.max(0, topo - 8)
        else if (base > rolagem.contentY + rolagem.height) rolagem.contentY = base - rolagem.height + 8
    }
    function irParaAba(indice) {
        if (indice < 0 || indice >= abas.length) return
        aba = abas[indice].id
        repetidorDeAbas.itemAt(indice).forceActiveFocus(Qt.TabFocusReason)
    }
    function contem(pai, item) {
        for (var p = item; p; p = p.parent)
            if (p === pai) return true
        return false
    }

    function entrarNaBusca() {
        buscaAtiva = true
        campoDeBusca.forceActiveFocus(Qt.ShortcutFocusReason)
    }
    function sairDaBusca() {
        filtro = ""
        buscaAtiva = false
        botaoDaLupa.forceActiveFocus(Qt.TabFocusReason)
    }

    // As linhas buscáveis e visíveis de uma seção, na ordem da tela (uma por entrada de `itens` dos grupos).
    function linhasBuscaveis(id: string): list<Item> {
        var achadas = []
        function andar(item) {
            for (var i = 0; i < item.children.length; ++i) {
                var c = item.children[i]
                if (c.itens !== undefined && c.separada !== undefined) {
                    for (var j = 0; j < c.itens.length; ++j) {
                        var linha = c.itens[j]
                        if (linha.buscavel === true && linha.aparece && linha.titulo) achadas.push(linha)
                    }
                } else andar(c)
            }
        }
        var k = abas.findIndex(a => a.id === id)
        if (k >= 0) andar(paginas.children[k])
        return achadas
    }

    function procurar() {
        var achados = []
        if (filtro === "") { resultados = achados; return }
        for (var k = 0; k < abas.length; ++k) {
            var pagina = abas[k]
            var linhas = linhasBuscaveis(pagina.id)
            for (var j = 0; j < linhas.length; ++j) {
                var linha = linhas[j]
                if (!preferencias.corresponde(linha.titulo + " " + (linha.subtitulo || ""), filtro)) continue
                var grupo = linha.parent
                while (grupo && !(grupo.itens !== undefined && grupo.separada !== undefined)) grupo = grupo.parent
                var dono = grupo ? grupo.parent : null
                var tituloDoGrupo = dono ? (dono.titulo !== undefined ? dono.titulo : (dono.contas ? dono.contas.titulo : "")) : ""
                achados.push({
                    linha: linha, titulo: linha.titulo, aba: pagina.id,
                    local: tituloDoGrupo ? pagina.titulo + " → " + tituloDoGrupo : pagina.titulo
                })
            }
        }
        resultados = achados
    }
    function focarLinha(linha) {
        function achar(item) {
            if (item.visible && item.enabled && item.activeFocusOnTab) return item
            for (var i = 0; i < item.children.length; ++i) {
                var r = achar(item.children[i])
                if (r) return r
            }
            return null
        }
        var alvo = achar(linha)
        if (alvo) alvo.forceActiveFocus(Qt.TabFocusReason)
        else linha.forceActiveFocus(Qt.TabFocusReason)
    }
    function abrirResultado(resultado) {
        aba = resultado.aba
        filtro = ""
        buscaAtiva = false
        Qt.callLater(() => focarLinha(resultado.linha))
    }

    Connections {
        target: preferencias
        function onAlterado() { if (dialogo.filtro !== "") Qt.callLater(dialogo.procurar) }
    }

    Connections {
        target: dialogo.Window.window
        function onActiveFocusItemChanged() {
            var foco = dialogo.Window.window.activeFocusItem
            if (!dialogo.visible || !foco || !dialogo.contem(rolagem.contentItem, foco)) return
            dialogo.mostrar(foco)
        }
    }

    Shortcut {
        sequences: [StandardKey.Find]  // Ctrl+F e a tecla Find; `sequence` ligaria só a primeira (aviso do Qt)
        enabled: dialogo.aberto && raiz.enabled && !dialogo.avisoAberto
        onActivated: dialogo.entrarNaBusca()
    }

    Binding { target: botaoDaLupa; property: "checked"; value: dialogo.buscaAtiva }

    Item {
        id: raiz
        objectName: "cartaoDasPreferencias"
        Layout.fillWidth: true
        Layout.fillHeight: true
        enabled: preferencias.brilhoPorDispositivo === null && preferencias.configuracaoDasFitas === null
            && preferencias.calibracao === null && !loginEpic.aberto && !loginEa.aberto && !confirmacaoDosMetadados.aberto

        Keys.onPressed: event => {
            if (event.text === "" || event.text.charCodeAt(0) < 32 || event.text.charCodeAt(0) === 127) return
            if (event.modifiers & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier)) return
            dialogo.entrarNaBusca()
            campoDeBusca.insert(campoDeBusca.length, event.text)
            event.accepted = true
        }

        ColumnLayout {
            anchors.fill: parent
            spacing: 0

            CabecalhoDoDialogo {
                id: cabecalho
                titulo: "Preferências"
                sombra: rolagem.contentY > 0
                opacidadeDoTitulo: dialogo.buscaAtiva ? 0 : 1
                onFechar: preferencias.fechar()
                inicio: [
                    Botao {
                        id: botaoDaLupa
                        objectName: "botaoDeBuscaDasPreferencias"
                        estilo: "plano"
                        icone: "system-search"
                        dica: "Buscar nas Preferências"
                        checkable: true
                        onClicked: if (dialogo.buscaAtiva) dialogo.sairDaBusca(); else dialogo.entrarNaBusca()
                    }
                ]

                CampoDeBusca {
                    id: campoDeBusca
                    objectName: "campoDeBuscaDasPreferencias"
                    anchors { centerIn: parent; verticalCenterOffset: -0.5 }
                    width: Math.max(0, Math.min(400, parent.width - 2 * 52))
                    visible: opacity > 0
                    opacity: dialogo.buscaAtiva ? 1 : 0
                    enabled: dialogo.buscaAtiva
                    placeholderText: "Buscar nas Preferências"
                    Accessible.name: "Buscar nas Preferências"
                    Behavior on opacity { enabled: Tema.animacoes; NumberAnimation { duration: Tema.duracaoCurta } }
                    Keys.onEscapePressed: dialogo.sairDaBusca()
                }
            }

            Flickable {
                id: rolagem
                objectName: "rolagemDasPreferencias"
                Layout.fillWidth: true
                Layout.fillHeight: true
                contentWidth: width
                contentHeight: !dialogo.buscando ? paginas.implicitHeight + 48
                    : dialogo.resultados.length > 0 ? resultadosDaBusca.implicitHeight + 48 : height
                boundsBehavior: Flickable.StopAtBounds
                RolagemPorMola { objectName: "molaDasPreferencias"; alvo: rolagem; ativa: Tema.animacoes }
                RolagemDaRoda { alvo: rolagem; ativa: !Tema.animacoes }
                clip: true
                ScrollBar.vertical: BarraDeRolagem {}

                readonly property real larguraDoConteudo: Math.min(width, 556) - 24

                Column {
                    id: paginas
                    x: (rolagem.width - width) / 2
                    y: 24
                    width: rolagem.larguraDoConteudo
                    visible: !dialogo.buscando

                    PaginaGeral { visible: dialogo.aba === "geral" }
                    PaginaDoControle { visible: dialogo.aba === "controle" }
                    PaginaDosMonitores { visible: dialogo.aba === "monitores" }
                    PaginaDaIluminacao { visible: dialogo.aba === "iluminacao" }
                    PaginaDeImportacao { visible: dialogo.aba === "importacao" }
                    PaginaDosMetadados { visible: dialogo.aba === "metadados" }
                    PaginaDasConquistas { visible: dialogo.aba === "conquistas" }
                    PaginaDasContas { visible: dialogo.aba === "contas" }
                    PaginaDoBackup { visible: dialogo.aba === "backup" }
                    PaginaDoAplicativo { visible: dialogo.aba === "aplicativo" }
                }

                GrupoDeLinhas {
                    id: resultadosDaBusca
                    objectName: "resultadosDaBuscaDasPreferencias"
                    x: (rolagem.width - width) / 2
                    y: 24
                    width: rolagem.larguraDoConteudo
                    visible: dialogo.buscando && dialogo.resultados.length > 0

                    Repeater {
                        model: dialogo.buscando ? dialogo.resultados : []
                        LinhaDeAcao {
                            required property var modelData
                            required property int index
                            objectName: "resultadoDaBusca-" + index
                            titulo: modelData.titulo
                            subtitulo: modelData.local
                            onAcionada: dialogo.abrirResultado(modelData)
                        }
                    }
                }

                EstadoVazio {
                    id: semResultado
                    objectName: "estadoSemResultadoDasPreferencias"
                    width: rolagem.width
                    height: Math.max(rolagem.height, implicitHeight)
                    visible: dialogo.buscando && dialogo.resultados.length === 0
                    icone: "edit-find"
                    titulo: "Nenhum resultado encontrado"
                    descricao: "Tente uma busca diferente."
                }
            }

            Item {
                id: barraDeAbas
                objectName: "abas"
                Layout.fillWidth: true
                implicitHeight: 47
                visible: !dialogo.buscando

                Rectangle {
                    width: parent.width
                    height: 1
                    color: Tema.sombraDaBarra
                    visible: rolagem.contentY + rolagem.height < rolagem.contentHeight - 1
                }
                Row {
                    anchors { horizontalCenter: parent.horizontalCenter; top: parent.top; topMargin: 4 }
                    spacing: 3
                    Repeater {
                        id: repetidorDeAbas
                        model: dialogo.abas
                        Button {
                            id: botao
                            required property var modelData
                            required property int index
                            readonly property bool atual: dialogo.aba === modelData.id
                            objectName: "aba-" + modelData.id
                            text: modelData.titulo
                            width: Math.min(100, (barraDeAbas.width - (dialogo.abas.length - 1) * 3) / dialogo.abas.length)
                            height: 40
                            padding: 0
                            hoverEnabled: true
                            focusPolicy: Qt.StrongFocus
                            Accessible.role: Accessible.PageTab
                            Accessible.name: text
                            Keys.onReturnPressed: click()
                            Keys.onEnterPressed: click()
                            Keys.onLeftPressed: dialogo.irParaAba(index - 1)
                            Keys.onRightPressed: dialogo.irParaAba(index + 1)
                            onClicked: dialogo.aba = modelData.id
                            contentItem: Item {
                                Icone {
                                    anchors { horizontalCenter: parent.horizontalCenter; top: parent.top; topMargin: 4 }
                                    nome: botao.modelData.icone
                                }
                                Text {
                                    anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 4 }
                                    width: parent.width
                                    horizontalAlignment: Text.AlignHCenter
                                    elide: Text.ElideRight
                                    text: botao.text
                                    textFormat: Text.PlainText
                                    color: Tema.texto
                                    font { family: Tema.fonte; pixelSize: Tema.legenda; weight: Tema.pesoForte }
                                }
                            }
                            background: Rectangle {
                                radius: 9
                                color: botao.down ? Tema.planoPressionado : botao.atual ? Tema.planoLigado : botao.hovered ? Tema.planoSobre : "transparent"
                                Behavior on color { ColorAnimation { duration: Tema.duracaoCurta } }
                                AnelDeFoco { ativo: botao.visualFocus; raio: 9; afastamento: -2 }
                            }
                        }
                    }
                }
            }
        }
    }

    // Filhos diretos do cartão, não do layout: o `z` só ordena irmãos, e assim o véu e o cartão deles ficam acima do
    // aviso (`z` 100) e do contorno (`z` 20).
    Item {
        parent: dialogo.cartao
        z: 200
        width: 0
        height: 0

        DialogoDeConfirmacao {
            id: confirmacaoDosMetadados
            objectName: "dialogoDosMetadados"
            titulo: "Atualizar metadados"
            rotuloConfirmar: "Buscar o que falta"
            rotuloAlternativo: "Buscar tudo"
            respostaInicial: "confirmar"
            onConfirmado: preferencias.biblioteca.buscarMetadados(true)
            onAlternativo: preferencias.biblioteca.buscarMetadados(false)
            onCancelado: preferencias.biblioteca.descartarPergunta()
            onRetornoPerdido: dialogo.focarInicial()
        }
        BrilhoPorDispositivo { onRetornoPerdido: dialogo.focarInicial() }
        ConfiguracaoDasFitas { onRetornoPerdido: dialogo.focarInicial() }
        AssistenteDeCalibracao { onRetornoPerdido: dialogo.focarInicial() }
        JanelaDeLogin {
            id: loginEpic
            objectName: "janelaDeLoginEpic"
            login: preferencias.contas ? preferencias.contas.loginEpic : null
            onRetornoPerdido: dialogo.focarInicial()
        }
        JanelaDeLogin {
            id: loginEa
            objectName: "janelaDeLoginEa"
            login: preferencias.contas ? preferencias.contas.loginEa : null
            onRetornoPerdido: dialogo.focarInicial()
        }
    }

    Connections {
        target: preferencias.biblioteca
        function onPerguntar(corpo) {
            confirmacaoDosMetadados.corpo = corpo
            confirmacaoDosMetadados.abrir()
        }
    }
}
