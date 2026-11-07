import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Shapes

// A janela do app: as páginas da biblioteca, os botões da barra e as camadas de aviso e confirmação.
Principal {
    id: janela

    // Lido aqui e não nos Avisos: lá o nome da propriedade é o mesmo.
    readonly property QtObject ligacao: ponte
    readonly property QtObject servicoDeAtualizacao: typeof atualizador === "undefined" ? null : atualizador
    readonly property QtObject servicoDoSobre: typeof sobre === "undefined" ? null : sobre
    readonly property bool sobreAberto: servicoDoSobre !== null && servicoDoSobre.aberto
    readonly property QtObject servicoDeZerados: typeof zeradosManuais === "undefined" ? null : zeradosManuais
    readonly property bool zeradosAberto: servicoDeZerados !== null && servicoDeZerados.aberto
    readonly property QtObject servicoDeNovidades: typeof novidades === "undefined" ? null : novidades
    readonly property string paginaAtual: pilha.depth === 0 ? "todos"
        : (pilha.currentItem && pilha.currentItem.objectName === "paginaDoJogo" ? "jogo"
        : (pilha.currentItem && pilha.currentItem.objectName === "paginaDasNovidades" ? "novidades" : "zerados"))

    function abrirDetalhes(jogoId) { abrirDetalhesDe(jogoId, false) }
    function abrirDetalhesDe(jogoId, anotar) {
        if (paginaAtual === "jogo") return
        if (detalhes.mostrar(jogoId)) empurrar(paginaDoJogo, { anotarAoEntrar: anotar })
    }
    function voltarPeloTeclado() {
        const abaixo = pilha.depth > 1 ? pilha.get(pilha.depth - 2) : todos
        if (abaixo && abaixo.marcarTeclado) abaixo.marcarTeclado()
        voltar()
    }
    function voltar() {
        _empurrando = false
        if (paginaAtual === "jogo" && pilha.depth > 1) { detalhes.esquecer(); pilha.pop() }
        else if (paginaAtual !== "todos") sairDaPilha()
    }

    // O `StackView` não anima o primeiro `push` numa pilha vazia nem o `clear` que a esvazia: o deslize e a sombra dessas
    // passagens são à mão.
    property bool _saindoDaPilha: false
    property bool _esquecerAoSair: false
    function _terminarSaida() {
        deslizeDaPagina.stop()
        avancoDaPilha.stop()
        pilha.avanco = 0
        _saindoDaPilha = false
        if (_esquecerAoSair) { _esquecerAoSair = false; detalhes.esquecer() }
        pilha.clear(StackView.Immediate)
    }
    function empurrar(componente, propriedades) {
        // Um push durante a saída animada termina a saída na hora, senão o `onFinished` apagaria a página nova.
        if (_saindoDaPilha) _terminarSaida()
        _empurrando = true
        const vazia = pilha.depth === 0
        pilha.push(componente, propriedades || {})
        if (vazia && Tema.animacoes && pilha.currentItem) {
            deslizeDaPagina.target = pilha.currentItem
            deslizeDaPagina.from = pilha.width
            deslizeDaPagina.to = 0
            avancoDaPilha.from = 0
            avancoDaPilha.to = 1
            deslizeDaPagina.restart()
            avancoDaPilha.restart()
        }
    }
    function sairDaPilha() {
        _empurrando = false
        const jogo = paginaAtual === "jogo"
        if (!Tema.animacoes || pilha.depth !== 1 || !pilha.currentItem) {
            if (jogo) detalhes.esquecer()
            pilha.clear(StackView.PopTransition)
            return
        }
        if (_saindoDaPilha) return
        _saindoDaPilha = true
        _esquecerAoSair = jogo
        deslizeDaPagina.target = pilha.currentItem
        deslizeDaPagina.from = pilha.currentItem.x
        deslizeDaPagina.to = pilha.width
        avancoDaPilha.from = pilha.avanco
        avancoDaPilha.to = 0
        deslizeDaPagina.restart()
        avancoDaPilha.restart()
    }
    NumberAnimation {
        id: deslizeDaPagina
        property: "x"
        duration: 210
        easing.type: Easing.OutCubic
        onFinished: if (janela._saindoDaPilha) janela._terminarSaida()
    }
    NumberAnimation { id: avancoDaPilha; target: pilha; property: "avanco"; duration: 210; easing.type: Easing.OutCubic }

    // O menu da barra abre abaixo dos 47 px dela, fora da área de arrasto do QWindowKit.
    function baseDaBarra(botao) { return botao.height + (alturaDaBarra - botao.height) / 2 }

    telaCheia: bigPicture.visivel || sessao.emAndamento
    barraTrancada: modalAberto

    tituloDaBarra: paginaAtual === "todos" ? "Todos os jogos" : paginaAtual === "zerados" ? "Jogos Zerados"
        : paginaAtual === "novidades" ? "Novidades" : detalhes.nome

    // Depois do setup do QWindowKit (Principal.qml), que roda no onCompleted da base.
    Component.onCompleted: visible = true

    sombraDaBarra: !!paginaDoControle && paginaDoControle.rolado === true
    barraTransparente: paginaAtual === "jogo"
    // O `XAnimator` da página não atualiza o `x` no meio do caminho: o `avanco` da pilha acompanha o deslize.
    readonly property real deslocamentoDoFundo: avancoDaPilha.running || pilha.busy ? Math.round(pilha.width * (1 - pilha.avanco)) : 0
    property bool _empurrando: false
    readonly property bool _barraCongelada: _empurrando && deslocamentoDoFundo > 0
    deslocamentoDaBarra: _barraCongelada ? deslocamentoDoFundo : 0
    fundoDaBarra: [
        Rectangle { x: janela.deslocamentoDoFundo; width: parent.width; height: parent.height; visible: janela.barraTransparente; color: "black" },
        Image {
            x: janela.deslocamentoDoFundo
            width: parent.width
            height: janela.height
            visible: janela.barraTransparente && detalhes.fundo !== ""
            source: visible ? detalhes.fundo : ""
            fillMode: Image.Stretch
            asynchronous: false
            opacity: detalhes.opacidadeDoFundo
        }
    ]

    function capturarNaPagina(event) {
        if (paginaDoControle && typeof paginaDoControle.capturar === "function" && paginaDoControle.capturar(event))
            event.accepted = true
    }
    component BotaoDoApp: BotaoDaBarra {
        Keys.onPressed: event => janela.capturarNaPagina(event)
    }

    readonly property bool podeVoltarPorAtalho: paginaAtual !== "todos" && !modalAberto && !bigPicture.visivel
        && !sessao.emAndamento
    Shortcut {
        sequences: ["Alt+Left", "Back"]
        enabled: janela.podeVoltarPorAtalho
        onActivated: janela.voltarPeloTeclado()
    }
    TapHandler {
        acceptedButtons: Qt.BackButton
        enabled: janela.podeVoltarPorAtalho
        onTapped: janela.voltar()
    }

    inicio: [
        BotaoDoApp {
            id: botaoAdicionar
            objectName: "botaoAdicionar"
            visible: janela.paginaAtual === "todos"
            icone: "list-add"
            dica: "Adicionar jogo"
            onClicked: menuDeAdicionar.opened ? menuDeAdicionar.close() : menuDeAdicionar.open()
            menuAberto: menuDeAdicionar.opened
            MenuDoTema {
                id: menuDeAdicionar
                objectName: "menuDeAdicionar"
                fechamento: Popup.CloseOnEscape | Popup.CloseOnPressOutsideParent
                y: janela.baseDaBarra(parent)
                setaEm: parent.width / 2
                ItemDoMenu { objectName: "itemAdicionarJogo"; text: "Adicionar jogo"; enabled: !aplicativo.importando; onTriggered: edicao.adicionar() }
                SeparadorDoMenu {}
                ItemDoMenu { text: "Importar"; enabled: !aplicativo.importando; onTriggered: aplicativo.importar() }
            }
        },
        BotaoDoApp {
            id: botaoVoltar
            objectName: "botaoVoltar"
            visible: janela.paginaAtual !== "todos"
            icone: "go-previous"
            dica: "Voltar"
            onClicked: janela.voltar()
        },
        BotaoDoApp {
            id: botaoAdicionarZerado
            objectName: "botaoAdicionarZerado"
            visible: janela.paginaAtual === "zerados" && janela.servicoDeZerados !== null
            icone: "list-add"
            dica: "Adicionar a Jogos Zerados"
            onClicked: janela.servicoDeZerados.abrir()
        }
    ]

    fim: [
        BotaoDoApp {
            id: botaoMenu
            objectName: "botaoMenu"
            visible: janela.paginaAtual === "todos" || janela.paginaAtual === "zerados"
            icone: "open-menu"
            dica: "Menu principal"
            onClicked: menuPrincipal.opened ? menuPrincipal.close() : menuPrincipal.open()
            menuAberto: menuPrincipal.opened
            MenuPrincipal {
                id: menuPrincipal
                objectName: "menuPrincipal"
                fechamento: Popup.CloseOnEscape | Popup.CloseOnPressOutsideParent
                servicoDoSobre: janela.servicoDoSobre
                y: janela.baseDaBarra(parent)
                x: parent.width - width
                setaEm: width - parent.width / 2
            }
        },
        BotaoDoApp {
            id: botaoAtualizar
            objectName: "botaoAtualizarNovidades"
            visible: janela.paginaAtual === "novidades"
            icone: "view-refresh"
            dica: "Atualizar"
            onClicked: janela.servicoDeNovidades.atualizar()
        },
        BotaoDoApp {
            id: botaoZerados
            objectName: "botaoZerados"
            visible: janela.paginaAtual === "todos"
            icone: "trofeu"
            dica: "Jogos Zerados"
            onClicked: janela.empurrar(zerados)
        },
        BotaoDoApp {
            id: botaoNovidades
            objectName: "botaoNovidades"
            visible: janela.paginaAtual === "todos" && janela.servicoDeNovidades !== null && janela.servicoDeNovidades.visivel
            icone: "novidades"
            tamanhoDoIcone: 20
            selo: janela.servicoDeNovidades !== null && janela.servicoDeNovidades.naoVistas
            dica: "Novidades"
            onClicked: { janela.servicoDeNovidades.abrir(); janela.empurrar(paginaDasNovidades) }
        },
        BotaoDoApp {
            id: botaoBigPicture
            indisponivel: !bigPicture.disponivel
            objectName: "botaoBigPicture"
            visible: janela.paginaAtual === "todos"
            icone: "video-display"
            dica: bigPicture.disponivel ? "Big Picture" : "Requer uma placa de vídeo com aceleração 3D."
            onClicked: bigPicture.entrar()
        },
        BotaoDoApp {
            id: botaoBusca
            objectName: "botaoBusca"
            visible: janela.paginaAtual === "todos"
            icone: "system-search"
            dica: "Buscar"
            checkable: true
            checked: todos.buscaAberta
            onClicked: todos.alternarBusca()
        }
    ]

    onPaginaAtualChanged: if (paginaAtual === "todos") todos.focarGrade()

    // A ordem de declaração é a ordem das camadas: páginas < diálogos < Big Picture < sessão < avisos (docs/arquitetura.md).
    PaginaDaBiblioteca {
        id: todos
        objectName: "pagina"
        anchors { fill: parent; topMargin: janela.alturaDoTopo }
        pagina: paginaTodos
        comBusca: true
        ativa: pilha.depth === 0 && !bigPicture.visivel && !sessao.emAndamento
        enabled: !camadaDeAvisos.dialogoAberto && !edicao.aberto && !historico.aberto && !conquistasDoJogo.aberto && !preferencias.aberto && !saves.aberto && !restauracao.aberta && !janela.sobreAberto && !janela.zeradosAberto && !bigPicture.visivel && !sessao.emAndamento
        onAbrirDetalhes: id => janela.abrirDetalhes(id)
        onEditar: id => edicao.abrir(id)
    }

    StackView {
        id: pilha
        objectName: "pilha"
        anchors { fill: parent; topMargin: janela.alturaDoTopo }
        visible: depth > 0
        property real avanco: 0
        // A biblioteca fica fora da pilha, embaixo dela: a pilha não a esconde como esconde as próprias páginas.
        // O botão Voltar do mouse passa, para o `TapHandler` da janela.
        background: BloqueioDoFundo { acceptedButtons: Qt.AllButtons & ~Qt.BackButton }
        pushEnter: Transition { ParallelAnimation {
            XAnimator { from: pilha.width; to: 0; duration: Tema.animacoes ? 210 : 0; easing.type: Easing.OutCubic }
            NumberAnimation { target: pilha; property: "avanco"; from: 0; to: 1; duration: Tema.animacoes ? 210 : 0; easing.type: Easing.OutCubic }
        } }
        pushExit: Transition { XAnimator { from: 0; to: -pilha.width / 4; duration: Tema.animacoes ? 210 : 0; easing.type: Easing.OutCubic } }
        popEnter: Transition { XAnimator { from: -pilha.width / 4; to: 0; duration: Tema.animacoes ? 210 : 0; easing.type: Easing.OutCubic } }
        popExit: Transition { ParallelAnimation {
            XAnimator { from: 0; to: pilha.width; duration: Tema.animacoes ? 210 : 0; easing.type: Easing.OutCubic }
            NumberAnimation { target: pilha; property: "avanco"; from: 1; to: 0; duration: Tema.animacoes ? 210 : 0; easing.type: Easing.OutCubic }
        } }
        enabled: !camadaDeAvisos.dialogoAberto && !edicao.aberto && !historico.aberto && !conquistasDoJogo.aberto && !preferencias.aberto && !saves.aberto && !restauracao.aberta && !janela.sobreAberto && !janela.zeradosAberto && !bigPicture.visivel && !sessao.emAndamento
    }

    Item {
        objectName: "barraDeAntes"
        width: janela._barraCongelada ? janela.deslocamentoDoFundo : 0
        height: janela.alturaDaBarra
        visible: !janela.telaCheia
        clip: true
        enabled: false
        ShaderEffectSource {
            objectName: "copiaDaBarra"
            x: pilha.depth > 1 ? Math.round(-pilha.width / 4 * pilha.avanco) : 0
            width: janela.width
            height: janela.alturaDaBarra
            sourceItem: janela.barraDeTitulo
            live: !janela._barraCongelada
        }
    }

    Item {
        objectName: "sombraDaTransicao"
        anchors { fill: parent; topMargin: janela._barraCongelada ? 0 : janela.alturaDoTopo }
        visible: pilha.avanco > 0 && pilha.avanco < 1
        enabled: false
        readonly property real borda: pilha.width * (1 - pilha.avanco)
        Rectangle { x: 0; width: parent.borda; height: parent.height; color: Qt.rgba(0, 0, 6 / 255, 0.2 * pilha.avanco) }
        Rectangle {
            x: parent.borda - width
            width: 32
            height: parent.height
            gradient: Gradient {
                orientation: Gradient.Horizontal
                GradientStop { position: 0; color: "transparent" }
                GradientStop { position: 1; color: Qt.rgba(0, 0, 6 / 255, 0.25 * pilha.avanco) }
            }
        }
    }

    Component {
        id: zerados
        PaginaDaBiblioteca {
            objectName: "paginaDeZerados"
            pagina: paginaZerados
            ativa: StackView.status !== StackView.Inactive && !bigPicture.visivel && !sessao.emAndamento
            onAbrirDetalhes: id => janela.abrirDetalhes(id)
            onEditar: id => edicao.abrir(id)
            onVoltar: janela.voltarPeloTeclado()
            StackView.onActivated: focarGrade()
            Rectangle { anchors.fill: parent; color: Tema.fundo; z: -1 }
        }
    }

    Component {
        id: paginaDasNovidades
        PaginaDasNovidades {
            objectName: "paginaDasNovidades"
            onVoltar: janela.voltar()
        }
    }

    Component {
        id: paginaDoJogo
        PaginaDoJogo {
            objectName: "paginaDoJogo"
            placeholder: paginaTodos.placeholder
            onVoltar: janela.voltarPeloTeclado()
            onJogar: detalhes.jogar()
            onEditar: edicao.abrir(detalhes.jogoId)
            onRemover: detalhes.remover()
            onExcluir: detalhes.excluir()
            onAtualizacaoConfirmada: detalhes.confirmarAtualizacao()
            onAbrirHistorico: historico.abrir(detalhes.jogoId)
        }
    }

    Connections {
        target: detalhes
        function onSair() { if (janela.paginaAtual === "jogo") janela.voltar() }
    }

    BotaoDasTarefas {
        id: botaoDasTarefas
        anchors.fill: parent
        pagina: janela.paginaAtual
        modalAberto: janela.modalAberto
        emBigPicture: bigPicture.visivel
        emSessao: sessao.emAndamento
    }

    Loader {
        objectName: "carregadorDasTarefas"
        active: painelDasTarefas.aberta
        sourceComponent: Component { JanelaDasTarefas { alvo: botaoDasTarefas.alvo; semAgente: janela.semAgente } }
    }

    Item {
        id: baseDoAviso
        anchors.fill: parent
    }

    DialogoDeEdicao {
        id: dialogoDeEdicao
        onRetornoPerdido: janela.paginaDoControle.focarGrade()
    }

    DialogoDoHistorico {
        id: dialogoDoHistorico
    }

    DialogoDeConquistas {
        id: dialogoDeConquistas
    }

    DialogoDePreferencias {
        id: dialogoDePreferencias
        avisoAberto: camadaDeAvisos.dialogoAberto
        onRetornoPerdido: edicao.aberto ? dialogoDeEdicao.devolverFoco() : janela.paginaDoControle.focarGrade()
    }

    DialogoDeVersoes {
        id: dialogoDeVersoes
        onRetornoPerdido: janela.paginaDoControle.focarGrade()
    }

    DialogoSobre {
        id: dialogoSobre
        modelo: janela.servicoDoSobre
        avisoAberto: camadaDeAvisos.dialogoAberto
        onRetornoPerdido: janela.paginaDoControle.focarGrade()
    }

    SeletorDeZerados {
        id: seletorDeZerados
        modelo: janela.servicoDeZerados
        onRetornoPerdido: janela.paginaDoControle.focarGrade()
    }

    DialogoDaPastaDeAtalhos {
        id: dialogoDaPasta
    }
    JanelaDosPendentes {
        id: janelaDosPendentes
        enabled: !restauracao.escolhaAberta && !restauracao.conflitoAberto
        onRetornoPerdido: janela.paginaDoControle.focarGrade()
    }
    EscolhaDoAtalho {
        id: escolhaDoAtalho
        onRetornoPerdido: restauracao.pendentesAbertos ? janelaDosPendentes.focarInicial() : janela.paginaDoControle.focarGrade()
    }
    DadosDoJogo {
        id: dadosDoJogo
        onRetornoPerdido: restauracao.pendentesAbertos ? janelaDosPendentes.focarInicial() : janela.paginaDoControle.focarGrade()
    }

    SeletorDeImagens {
        id: seletorDeCapa
        objectName: "seletorDeCapa"
        seletor: edicao.seletorDeCapa
        titulo: "Escolher capa"
        rotuloDoAtalho: "Animadas"
        dicaDoAtalho: "Mostrar capas animadas"
        atalhoAlterna: true
        onAtalhoClicado: seletor.animadas = !seletor.animadas
        onRetornoPerdido: dialogoDeEdicao.devolverFoco()
    }
    SeletorDeImagens {
        id: seletorDeLogo
        objectName: "seletorDeLogo"
        seletor: edicao.seletorDeLogo
        titulo: "Escolher logo"
        rotuloDoAtalho: "Usar o título"
        dicaDoAtalho: "Não usar logo neste jogo"
        horizontal: true
        onAtalhoClicado: seletor.usarTitulo()
        onRetornoPerdido: dialogoDeEdicao.devolverFoco()
    }

    SeletorDePapelDeParede {
        id: seletorDePapel
        objectName: "seletorDePapel"
        seletor: edicao.seletorDePapelDeParede
        onRetornoPerdido: dialogoDeEdicao.devolverFoco()
    }

    SeletorDaSteam {
        id: seletorDaSteam
        objectName: "seletorDaSteam"
        seletor: edicao.seletorDaSteam
        onRetornoPerdido: dialogoDeEdicao.devolverFoco()
    }
    SeletorDoLudusavi {
        id: seletorDoLudusavi
        objectName: "seletorDoLudusavi"
        seletor: edicao.seletorDoLudusavi
        onRetornoPerdido: dialogoDeEdicao.devolverFoco()
    }

    BigPicture {
        id: camadaDoBigPicture
        anchors.fill: parent
        visible: bigPicture.visivel
        animarPasso: bigPicture.animacoes
        sessaoEmAndamento: sessao.emAndamento
        enabled: !camadaDeAvisos.dialogoAberto && (!sessao.emAndamento || (bigPicture.visivel && bigPicture.etapa === "sessao"))
        onVisibleChanged: if (visible) forceActiveFocus()
        onEnabledChanged: if (enabled && visible) forceActiveFocus()
    }

    Connections {
        target: bigPicture
        function onSaiu(jogoId) { todos.focarJogo(jogoId) }
    }

    property bool _bigPictureVisto: false
    Connections {
        target: bigPicture
        function onAlterado() {
            const visivel = bigPicture.visivel
            if (visivel && !janela._bigPictureVisto) {
                menuPrincipal.close()
                todos.fecharMenuDoJogo()
            }
            janela._bigPictureVisto = visivel
        }
    }

    CamadaDaSessao {
        id: camadaDaSessao
        anchors.fill: parent
        // A etapa da sessão do Big Picture tem a própria tela; em qualquer outra a camada normal cobre.
        visible: sessao.emAndamento && !janela.sessaoNoBigPicture
    }

    onClosing: (fechar) => fechar.accepted = painelDasTarefas.principalFechando()

    Loader {
        objectName: "carregadorDaJanelaManual"
        active: sessao.janelaManual && !janela.sessaoNoBigPicture
        sourceComponent: Component { JanelaDaSessao { semAgente: janela.semAgente } }
    }

    Avisos {
        id: camadaDeAvisos
        objectName: "camadaDeAvisos"
        z: 20
        onRetornoPerdido: janela.paginaDoControle.focarGrade()
        anchors.fill: parent
        ponte: janela.ligacao
        fila: aplicativo.avisos
        app: aplicativo
        atualizador: janela.servicoDeAtualizacao
        lugarDoAviso: preferencias.aberto ? dialogoDePreferencias.cartao : janela.sobreAberto ? dialogoSobre.cartao : janela.telaCheia ? null : baseDoAviso
    }

    DropArea {
        id: alvoDeSoltar
        objectName: "alvoDeSoltar"
        anchors.fill: parent
        // A lista do `modalAberto`, à mão: ligado nele, a ordem dos bindings muda e o foco que volta das Preferências não
        // acha o botão do menu.
        enabled: !camadaDeAvisos.dialogoAberto && !edicao.aberto && !historico.aberto && !conquistasDoJogo.aberto && !preferencias.aberto && !saves.aberto && !restauracao.aberta && !janela.sobreAberto && !janela.zeradosAberto
            && !(janela.paginaDoControle && janela.paginaDoControle.dialogoAberto === true)
        onEntered: (arrasto) => arrasto.accepted = arrasto.hasUrls
        onDropped: (soltou) => {
            if (soltou.hasUrls) aplicativo.soltar(soltou.urls)
        }
    }

    Rectangle {
        id: avisoDeSoltar
        objectName: "avisoDeSoltar"
        anchors.fill: parent
        color: Qt.alpha(Tema.fundo, 0.88)
        opacity: alvoDeSoltar.containsDrag ? 1 : 0
        visible: opacity > 0
        Behavior on opacity { NumberAnimation { duration: 150 } }

        Item {
            id: moldura
            anchors.centerIn: parent
            width: Math.min(420, avisoDeSoltar.width - 48)
            height: coluna.implicitHeight + 88
            Shape {
                anchors.fill: parent
                ShapePath {
                    strokeColor: Qt.alpha(Tema.texto, Tema.texto.a * 0.45)
                    strokeWidth: 2
                    strokeStyle: ShapePath.DashLine
                    dashPattern: [3, 3]
                    fillColor: "transparent"
                    PathRectangle { x: 1; y: 1; width: moldura.width - 2; height: moldura.height - 2; radius: 15 }
                }
            }
            Column {
                id: coluna
                anchors { centerIn: parent }
                spacing: 14
                Icone {
                    anchors.horizontalCenter: parent.horizontalCenter
                    nome: "folder-download"
                    tamanho: 40
                    cor: Tema.texto
                    opacity: 0.8
                }
                Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: "Solte aqui para importar"
                    textFormat: Text.PlainText
                    color: Qt.alpha(Tema.texto, Tema.texto.a * 0.8)
                    font { family: Tema.fonte; pixelSize: Tema.titulo3; weight: Tema.pesoTitulo3 }
                }
            }
        }
    }

    Connections {
        target: sessao
        function onAnotarPedido(jogoId) {
            if (janela.paginaAtual === "jogo" && detalhes.jogoId !== jogoId) janela.voltar()
            if (janela.paginaAtual === "jogo") pilha.currentItem.abrirAnotacao()
            else janela.abrirDetalhesDe(jogoId, true)
        }
    }

    Connections {
        target: janela.ligacao
        function onSairDaFrente() { sessao.minimizar() }
    }

    readonly property var paginaDoControle: pilha.depth === 0 ? todos : pilha.currentItem
    readonly property bool modalAberto: camadaDeAvisos.dialogoAberto || edicao.aberto || historico.aberto || conquistasDoJogo.aberto || preferencias.aberto || saves.aberto || restauracao.aberta || sobreAberto || zeradosAberto
        || (paginaDoControle !== null && paginaDoControle.dialogoAberto === true)
    readonly property bool popupAberto: menuPrincipal.opened || modalAberto
        || (paginaDoControle !== null && paginaDoControle.menuDoJogoAberto)
    property bool ponteiroEscondido: false
    property point posicaoDoPonteiro

    readonly property var botoesDaBarra: [botaoAdicionar, botaoVoltar, botaoAdicionarZerado, botaoZerados, botaoNovidades, botaoAtualizar, botaoBigPicture, botaoBusca, botaoMenu]
    function botaoFocado() {
        for (var i = 0; i < botoesDaBarra.length; ++i)
            if (botoesDaBarra[i].activeFocus) return botoesDaBarra[i]
        return null
    }
    function botaoPerto(x, exceto, sentido) {
        var melhor = null, distancia = 1e9
        for (var i = 0; i < botoesDaBarra.length; ++i) {
            var b = botoesDaBarra[i]
            if (!b.visible || !b.enabled || b.indisponivel === true || b === exceto) continue
            var dx = b.mapToItem(null, b.width / 2, 0).x - x
            if (sentido && dx * sentido <= 0) continue
            var d = Math.abs(dx)
            if (d < distancia) { distancia = d; melhor = b }
        }
        return melhor
    }
    function focarBotao(b) { b.forceActiveFocus(Qt.TabFocusReason) }

    function teclaDoPasso(dx, dy) {
        return dy < 0 ? Qt.Key_Up : dy > 0 ? Qt.Key_Down : dx < 0 ? Qt.Key_Left : Qt.Key_Right
    }

    function escopoDoFoco(foco) {
        for (var p = foco; p; p = p.parent) {
            if (typeof p.dentro === "function" && typeof p.focarInicial === "function") return p
            if (p.parent === Overlay.overlay) return p
        }
        return null
    }
    function descende(item, raiz) {
        for (var p = item; p; p = p.parent)
            if (p === raiz) return true
        return false
    }
    function ehEditor(item) {
        return typeof item.cursorPosition === "number" || typeof item.stepSize === "number"
            || (item.popup !== undefined && typeof item.currentIndex === "number")
    }
    function vizinhoNaDirecao(foco, escopo, dx, dy) {
        var c0 = foco.mapToItem(null, foco.width / 2, foco.height / 2)
        var r0 = foco.mapToItem(null, 0, 0)
        var melhor = null, nota = 1e9, atual = foco
        for (var i = 0; i < 500; ++i) {
            atual = atual.nextItemInFocusChain(true)
            if (!atual || atual === foco) break
            if (!atual.visible || !atual.enabled || !descende(atual, escopo)) continue
            // O candidato tem de se cruzar com o foco no eixo perpendicular, senão o toque lateral saltaria para outra
            // altura do diálogo.
            var r = atual.mapToItem(null, 0, 0)
            var cruza = dx !== 0 ? r.y < r0.y + foco.height && r.y + atual.height > r0.y
                                 : r.x < r0.x + foco.width && r.x + atual.width > r0.x
            if (!cruza) continue
            var c = atual.mapToItem(null, atual.width / 2, atual.height / 2)
            var adiante = (c.x - c0.x) * dx + (c.y - c0.y) * dy
            if (adiante < 1) continue
            var n = adiante + 2 * (dx !== 0 ? Math.abs(c.y - c0.y) : Math.abs(c.x - c0.x))
            if (n < nota) { nota = n; melhor = atual }
        }
        return melhor
    }
    function garantirVisivel(item, escopo) {
        for (var p = item.parent; p && p !== escopo.parent; p = p.parent) {
            if (typeof p.contentY !== "number" || typeof p.contentHeight !== "number" || !p.contentItem) continue
            var topo = item.mapToItem(p.contentItem, 0, 0).y
            var minimo = p.originY - p.topMargin
            var maximo = Math.max(minimo, p.originY + p.contentHeight + p.bottomMargin - p.height)
            if (topo < p.contentY) p.contentY = Math.max(minimo, topo)
            else if (topo + item.height > p.contentY + p.height) p.contentY = Math.min(maximo, topo + item.height - p.height)
        }
    }
    function realcadoEm(raiz) {
        for (var i = 0; i < raiz.children.length; ++i) {
            var filho = raiz.children[i]
            if (filho.highlighted === true) return filho
            var dentro = realcadoEm(filho)
            if (dentro) return dentro
        }
        return null
    }
    function situacaoDoPasso(escopo) {
        var foco = janela.activeFocusItem
        var rolagem = 0
        for (var p = foco; p; p = p.parent)
            if (typeof p.contentY === "number") { rolagem = p.contentY; break }
        return [foco, escopo && escopo.parent === Overlay.overlay ? realcadoEm(escopo) : null, rolagem,
                foco && typeof foco.currentIndex === "number" ? foco.currentIndex : -1,
                foco && typeof foco.highlightedIndex === "number" ? foco.highlightedIndex : -1]
    }
    function passoNosPopups(dx, dy) {
        var foco = janela.activeFocusItem
        var escopo = foco ? escopoDoFoco(foco) : null
        var listaAberta = !!foco && foco.popup !== undefined && foco.popup.visible === true
        // `setasProprias`: o item anda por conta própria (a lista de seções das Preferências tem uma parada só no Tab,
        // então a vizinhança espacial pularia os itens).
        if (escopo && !listaAberta && !(foco && foco.setasProprias === true)) {
            var vizinho = vizinhoNaDirecao(foco, escopo, dx, dy)
            if (vizinho) {
                vizinho.forceActiveFocus(Qt.TabFocusReason)
                garantirVisivel(vizinho, escopo)
                return true
            }
            if (ehEditor(foco)) return false
        }
        var antes = situacaoDoPasso(escopo)
        controle.teclar(teclaDoPasso(dx, dy))
        var depois = situacaoDoPasso(escopo)
        for (var i = 0; i < antes.length; ++i)
            if (antes[i] !== depois[i]) return true
        return false
    }

    readonly property bool sessaoNoBigPicture: bigPicture.visivel && bigPicture.etapa === "sessao"
    readonly property bool bigPictureNaFrente: bigPicture.visivel || bigPicture.ocupada

    Binding { target: controle; property: "modoBigPicture"; value: bigPicture.visivel && !janela.popupAberto }

    Connections {
        target: controle
        enabled: !sessao.emAndamento || (bigPicture.visivel && bigPicture.etapa === "sessao")
        function onMover(dx, dy) {
            if (janela.popupAberto) {
                if (janela.passoNosPopups(dx, dy)) controle.passar()
                else controle.bater()
                return
            }
            if (janela.bigPictureNaFrente) {
                if (bigPicture.etapa !== "carrossel" || bigPicture.ocupada || dx === 0) return
                if (bigPicture.mover(dx)) controle.trocarCapa()
                else controle.bater()
                return
            }
            var focado = janela.botaoFocado()
            if (focado) {
                var x = focado.mapToItem(null, focado.width / 2, 0).x
                if (dy > 0) {
                    janela.paginaDoControle.mostrarSelecao()
                    janela.paginaDoControle.focarGrade()
                    controle.passar()
                } else if (dx !== 0) {
                    var vizinho = janela.botaoPerto(x, focado, dx)
                    if (vizinho) { janela.focarBotao(vizinho); controle.passar() }
                    else controle.bater()
                } else controle.bater()
            } else if (janela.paginaDoControle) {
                if (janela.paginaDoControle.moverSelecao(dx, dy)) {
                    controle.passar()
                } else if (dy < 0) {
                    var botao = janela.botaoPerto(janela.paginaDoControle.xDoAtual(), null, 0)
                    if (botao) { janela.focarBotao(botao); controle.passar() }
                    else controle.bater()
                } else controle.bater()
            }
        }
        function onPular(delta) {
            if (janela.popupAberto || !janela.bigPictureNaFrente || bigPicture.etapa !== "carrossel" || bigPicture.ocupada) return
            if (bigPicture.mover(delta)) controle.saltar()
            else controle.bater()
        }
        function onConectado() {
            bigPicture.controleConectado(janela.paginaAtual === "todos" && !janela.modalAberto)
        }
        function onPresente() {
            if (janela.bigPictureNaFrente) return
            if (!janela.popupAberto && janela.paginaDoControle && janela.paginaDoControle.mostrarSelecao() === true)
                controle.passar()
        }
        function onAtivar() {
            if (janela.popupAberto) {
                var foco = janela.activeFocusItem
                if (!foco || typeof foco.lineCount !== "number") controle.teclar(Qt.Key_Return)
                return
            }
            // Na sessão a página está ocupada, mas o A precisa chegar ao "Já terminei de jogar".
            if (janela.bigPictureNaFrente) { if (bigPicture.etapa === "sessao" || !bigPicture.ocupada) bigPicture.ativar(); return }
            var focado = janela.botaoFocado()
            if (focado) focado.click()
            else if (janela.paginaDoControle) janela.paginaDoControle.abrirDetalhesDoAtual()
        }
        function onVoltar() {
            if (janela.popupAberto) { controle.teclar(Qt.Key_Escape); return }
            if (janela.bigPictureNaFrente) { if (!bigPicture.ocupada) bigPicture.voltar(); return }
            if (janela.paginaAtual !== "todos") janela.voltar()
            else if (todos.buscaAberta) todos.buscaAberta = false
        }
        function onMenuPrincipal() {
            if (!janela.bigPictureNaFrente && !janela.popupAberto && (janela.paginaAtual === "todos" || janela.paginaAtual === "zerados"))
                menuPrincipal.open()
        }
        function onMenuDoJogo() { if (!janela.bigPictureNaFrente && !janela.popupAberto && janela.paginaDoControle) janela.paginaDoControle.abrirMenuDoAtual() }
        function onBuscar() { if (!janela.bigPictureNaFrente && !janela.popupAberto && janela.paginaAtual === "todos") todos.alternarBusca() }
        function onUsado() {
            janela.posicaoDoPonteiro = ponteiro.point.position
            janela.ponteiroEscondido = true
        }
    }

    HoverHandler {
        id: ponteiro
        cursorShape: janela.ponteiroEscondido ? Qt.BlankCursor : Qt.ArrowCursor
        onPointChanged: {
            if (!janela.ponteiroEscondido) return
            var p = point.position
            if (Math.abs(p.x - janela.posicaoDoPonteiro.x) > 1 || Math.abs(p.y - janela.posicaoDoPonteiro.y) > 1)
                janela.ponteiroEscondido = false
        }
    }
}
