import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import QtQuick.Window

// As Preferências: a lista das seções à esquerda (com a busca) e, à direita, o cabeçalho da seção com o X e a página dela. Só
// desenha: o estado é do `preferencias` (cartridges/modelos/preferencias.py).
MolduraDoDialogo {
    id: dialogo
    objectName: "dialogoDePreferencias"

    readonly property var secoes: [
        { id: "geral", titulo: "Geral", subtitulo: "Comportamento do aplicativo ao jogar", icone: "preferences-system" },
        { id: "controle", titulo: "Controle", subtitulo: "Navegação com controle e Big Picture", icone: "input-gaming" },
        { id: "monitores", titulo: "Monitores", subtitulo: "Segundo monitor e papel de parede", icone: "video-joined-displays" },
        { id: "iluminacao", titulo: "Iluminação", subtitulo: "Iluminação inteligente da Tuya", icone: "display-brightness" },
        { id: "importacao", titulo: "Importação", subtitulo: "Como os jogos entram na biblioteca", icone: "folder-download" },
        { id: "metadados", titulo: "Metadados e capas", subtitulo: "Informações e imagens dos jogos", icone: "image-x-generic" },
        { id: "conquistas", titulo: "Conquistas", subtitulo: "Exibição e aviso durante o jogo", icone: "trofeu" },
        { id: "contas", titulo: "Contas", subtitulo: "Lojas conectadas ao Kyron", icone: "avatar-default" },
        { id: "backup", titulo: "Backup", subtitulo: "Cópia da biblioteca e dos saves", icone: "drive-harddisk" },
        { id: "aplicativo", titulo: "Aplicativo", subtitulo: "Atualizações e redefinição", icone: "software-update-available" }
    ]
    readonly property var rotulosDasSecoes: secoes.map(a => a.titulo)
    property string secao: "geral"
    readonly property int indiceDaSecao: Math.max(0, secoes.findIndex(a => a.id === secao))
    // Durante a busca a direita mostra os resultados, e o cabeçalho deixa de falar da seção.
    readonly property var secaoAtual: secoes[indiceDaSecao]
    property alias filtro: lista.texto
    readonly property bool buscando: filtro !== ""
    property var resultados: []
    property bool avisoAberto: false
    // Muda a cada alteração das preferências: refaz a conta dos contadores da lista.
    property int _versaoDosContadores: 0
    readonly property Item botaoFechar: cabecalho.botaoFechar

    aberto: preferencias.aberto
    largura: 860
    altura: 2000  // sem teto próprio: a janela limita
    nomeAcessivel: "Preferências"
    onFecharPedido: preferencias.fechar()

    onFiltroChanged: {
        rolagem.contentY = 0
        procurar()
    }
    onAbertoChanged: if (aberto) {
        secao = secoes.some(a => a.id === preferencias.pagina) ? preferencias.pagina : "geral"
        rolagem.contentY = 0
        filtro = ""
        // O foco começa no X: o primeiro Tab vai à primeira linha habilitada da página, e não pela lista.
        focoInicial = cabecalho.botaoFechar
    } else {
        confirmacaoDosMetadados.aberto = false
        filtro = ""
    }

    function mostrar(item) {
        var topo = item.mapToItem(rolagem.contentItem, 0, 0).y
        var base = topo + item.height
        if (topo < rolagem.contentY) rolagem.contentY = Math.max(0, topo - 8)
        else if (base > rolagem.contentY + rolagem.height) rolagem.contentY = base - rolagem.height + 8
    }
    function contem(pai, item) {
        for (var p = item; p; p = p.parent)
            if (p === pai) return true
        return false
    }

    function entrarNaBusca() {
        lista.campo.forceActiveFocus(Qt.ShortcutFocusReason)
    }
    // Esc na busca: apaga o texto e o foco volta ao item da seção atual.
    function sairDaBusca() {
        filtro = ""
        lista.focarSecao(secao)
    }
    function entrarNasLinhas() {
        focarLinha(paginas.children[indiceDaSecao])
    }
    function contagem(id: string): int {
        _versaoDosContadores  // só para o contador reavaliar quando algo mudar
        return linhasBuscaveis(id).length
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
        var k = secoes.findIndex(a => a.id === id)
        if (k >= 0) andar(paginas.children[k])
        return achadas
    }

    function procurar() {
        var achados = []
        if (filtro === "") { resultados = achados; return }
        for (var k = 0; k < secoes.length; ++k) {
            var pagina = secoes[k]
            var linhas = linhasBuscaveis(pagina.id)
            for (var j = 0; j < linhas.length; ++j) {
                var linha = linhas[j]
                if (!preferencias.corresponde(linha.titulo + " " + (linha.subtitulo || ""), filtro)) continue
                var grupo = linha.parent
                while (grupo && !(grupo.itens !== undefined && grupo.separada !== undefined)) grupo = grupo.parent
                var dono = grupo ? grupo.parent : null
                var tituloDoGrupo = dono ? (dono.titulo !== undefined ? dono.titulo : (dono.contas ? dono.contas.titulo : "")) : ""
                achados.push({
                    linha: linha, titulo: linha.titulo, secao: pagina.id,
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
        secao = resultado.secao
        filtro = ""
        Qt.callLater(() => focarLinha(resultado.linha))
    }

    Connections {
        target: preferencias
        function onAlterado() {
            // Adiado: as linhas só mudam de `aparece` depois que o estado novo chega.
            Qt.callLater(() => { dialogo._versaoDosContadores++ })
            if (dialogo.filtro !== "") Qt.callLater(dialogo.procurar)
        }
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
            lista.campo.insert(lista.campo.length, event.text)
            event.accepted = true
        }

        RowLayout {
            anchors.fill: parent
            spacing: 0

            ListaDeSecoes {
                id: lista
                Layout.fillHeight: true
                Layout.preferredWidth: compacta ? 160 : 210
                secoes: dialogo.secoes
                secao: dialogo.secao
                compacta: raiz.width < 620
                contagem: dialogo.contagem
                raio: dialogo.raio
                onBuscaEncerrada: dialogo.sairDaBusca()
                onEscolhida: id => dialogo.secao = id
                onEntrarNasLinhas: dialogo.entrarNasLinhas()
            }

            ColumnLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 0

                CabecalhoDoDialogo {
                    id: cabecalho
                    objectName: "cabecalhoDaSecao"
                    implicitHeight: 64
                    comTitulo: false
                    sombra: rolagem.contentY > 0
                    onFechar: preferencias.fechar()
                    inicio: [
                        Row {
                            leftPadding: 14
                            spacing: 12
                            Rectangle {
                                width: 36
                                height: 36
                                radius: 9
                                color: Tema.planoLigado
                                Icone {
                                    anchors.centerIn: parent
                                    tamanho: 20
                                    nome: dialogo.buscando ? "edit-find" : dialogo.secaoAtual.icone
                                }
                            }
                            Column {
                                anchors.verticalCenter: parent.verticalCenter
                                width: Math.max(0, cabecalho.width - 14 - 36 - 12 - 60)
                                Text {
                                    objectName: "tituloDaSecao"
                                    width: parent.width
                                    elide: Text.ElideRight
                                    text: dialogo.buscando ? "Resultados da busca" : dialogo.secaoAtual.titulo
                                    textFormat: Text.PlainText
                                    color: Tema.texto
                                    font { family: Tema.fonte; pixelSize: Tema.corpo + 2; weight: Tema.pesoForte }
                                    Accessible.role: Accessible.Heading
                                    Accessible.name: text
                                }
                                Text {
                                    objectName: "subtituloDaSecao"
                                    width: parent.width
                                    elide: Text.ElideRight
                                    visible: text !== ""
                                    text: dialogo.buscando ? "" : dialogo.secaoAtual.subtitulo
                                    textFormat: Text.PlainText
                                    color: Tema.textoSecundario
                                    font { family: Tema.fonte; pixelSize: Tema.legenda + 1 }
                                }
                            }
                        }
                    ]
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

                        PaginaGeral { visible: dialogo.secao === "geral" }
                        PaginaDoControle { visible: dialogo.secao === "controle" }
                        PaginaDosMonitores { visible: dialogo.secao === "monitores" }
                        PaginaDaIluminacao { visible: dialogo.secao === "iluminacao" }
                        PaginaDeImportacao { visible: dialogo.secao === "importacao" }
                        PaginaDosMetadados { visible: dialogo.secao === "metadados" }
                        PaginaDasConquistas { visible: dialogo.secao === "conquistas" }
                        PaginaDasContas { visible: dialogo.secao === "contas" }
                        PaginaDoBackup { visible: dialogo.secao === "backup" }
                        PaginaDoAplicativo { visible: dialogo.secao === "aplicativo" }
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
