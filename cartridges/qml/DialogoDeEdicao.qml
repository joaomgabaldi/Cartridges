import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Dialogs
import QtQuick.Effects
import QtQuick.Layouts
import QtQuick.Window

// O diálogo de editar um jogo e o de adicionar um novo (`Adw.Dialog` de 480 de largura com a `HeaderBar` e uma
// `PreferencesPage`). Só desenha: o que ele edita é o `edicao` (cartridges/modelos/edicao.py) e a regra de validar e
// gravar é de cartridges/edicao.py. Modal para o mouse, o teclado e o controle; o foco volta a quem o abriu.
MolduraDoDialogo {
    id: dialogo
    objectName: "dialogoDeEdicao"

    // O último foco dentro do diálogo (para o devolver depois de um erro).
    property Item ultimoFoco: null
    property bool avancadasAbertas: false
    // O que o seletor de arquivo aberto escolhe: "executavel", "capa", "logo" ou "papel".
    property string alvoDoSeletor: "executavel"
    // Com um seletor ou as Preferências por cima, nada daqui recebe o mouse nem o Tab.
    readonly property bool ativo: !preferencias.aberto && !edicao.seletorDeCapa.aberto && !edicao.seletorDeLogo.aberto
        && !edicao.seletorDePapelDeParede.aberto && !edicao.seletorDaSteam.aberto && !edicao.seletorDoLudusavi.aberto

    function devolverFoco() { (ultimoFoco && dentro(ultimoFoco) ? ultimoFoco : campoNome).forceActiveFocus(Qt.TabFocusReason) }
    // O campo com o foco fica à vista na rolagem.
    function mostrar(item) {
        var topo = item.mapToItem(rolagem.contentItem, 0, 0).y
        var base = topo + item.height
        if (topo < rolagem.contentY) rolagem.contentY = Math.max(0, topo - 8)
        else if (base > rolagem.contentY + rolagem.height) rolagem.contentY = base - rolagem.height + 8
    }

    aberto: edicao.aberto
    largura: 480
    focoInicial: campoNome
    nomeAcessivel: edicao.titulo
    onFecharPedido: edicao.cancelar()
    onAbertoChanged: if (aberto) {
        avancadasAbertas = false
        rolagem.contentY = 0
    }

    Connections {
        target: dialogo.Window.window
        function onActiveFocusItemChanged() {
            var foco = dialogo.Window.window.activeFocusItem
            if (!dialogo.visible || !foco || !dialogo.dentro(foco)) return
            dialogo.ultimoFoco = foco
            if (foco !== botaoCancelar && foco !== botaoAplicar) dialogo.mostrar(foco)
        }
    }
    Connections {
        target: edicao
        function onAvancadasPedidas() { dialogo.avancadasAbertas = true }
        function onFocoDevolvido() { dialogo.devolverFoco() }
    }

    // Criado só ao clicar: o seletor nativo não precisa existir antes. Um só serve aos quatro usos. Sem título próprio,
    // como o `Gtk.FileDialog` da `main`.
    function abrirSeletor(alvo) {
        alvoDoSeletor = alvo
        // O `Loader` é síncrono: ao ativar, o `onLoaded` já abre o seletor.
        if (cargaDoSeletor.item) cargaDoSeletor.item.open(); else cargaDoSeletor.active = true
    }
    Loader {
        id: cargaDoSeletor
        active: false
        sourceComponent: FileDialog {
            // Capa e papel de parede usam o mesmo filtro, "Imagens e vídeos" (`details_dialog.py:1283`).
            nameFilters: dialogo.alvoDoSeletor === "capa" ? [edicao.filtroDaCapa]
                : dialogo.alvoDoSeletor === "logo" ? [edicao.filtroDoLogo]
                : dialogo.alvoDoSeletor === "papel" ? [edicao.filtroDoPapel]
                : ["Executáveis (*.exe *.bat *.cmd *.lnk *.url)"]
            onAccepted: {
                if (dialogo.alvoDoSeletor === "capa") edicao.escolherCapa(selectedFile)
                else if (dialogo.alvoDoSeletor === "logo") edicao.escolherLogo(selectedFile)
                else if (dialogo.alvoDoSeletor === "papel") edicao.escolherPapel(selectedFile)
                else edicao.escolherExecutavel(selectedFile)
            }
        }
        onLoaded: item.open()
    }

    // Uma `Adw.ActionRow` com botões planos no fim e ativável: clicar na linha aciona o botão `ativavel`
    // (`activatable-widget`). Desabilitada, apaga a 50% como as outras linhas.
    component LinhaDeArte: LinhaDoGrupo {
        id: linhaDeArte
        default property alias botoes: lado.data
        property Item ativavel
        reservaADireita: lado.width
        sobre: areaDaLinha.containsMouse
        pressionada: areaDaLinha.pressed
        MouseArea {
            id: areaDaLinha
            anchors.fill: parent
            hoverEnabled: true
            onClicked: if (linhaDeArte.ativavel && linhaDeArte.ativavel.enabled) linhaDeArte.ativavel.click()
        }
        Row {
            id: lado
            anchors { right: parent.right; rightMargin: 14; verticalCenter: parent.verticalCenter }
            spacing: 6
        }
    }

    // O botão plano de ícone dos sufixos das linhas.
    component BotaoDeLinha: Botao {
        estilo: "plano"
    }

    CabecalhoDoDialogo {
        titulo: edicao.titulo
        comFechar: false
        sombra: rolagem.contentY > 0
        enabled: dialogo.ativo
        inicio: [
            Botao {
                id: botaoCancelar
                objectName: "botaoCancelarDaEdicao"
                estilo: "plano"
                text: "Cancelar"
                onClicked: edicao.cancelar()
            }
        ]
        fim: [
            Botao {
                id: botaoAplicar
                objectName: "botaoAplicarDaEdicao"
                estilo: "sugestao"
                text: edicao.rotuloDoAplicar
                enabled: !edicao.ocupado && edicao.appidValido
                onClicked: edicao.aplicar()
            }
        ]
    }

    Flickable {
        id: rolagem
        Layout.fillWidth: true
        Layout.fillHeight: true
        Layout.preferredHeight: contentHeight
        enabled: dialogo.ativo
        contentWidth: width
        contentHeight: grupos.implicitHeight + 48
        boundsBehavior: Flickable.StopAtBounds
        clip: true
        ScrollBar.vertical: BarraDeRolagem {}

        // `PreferencesPage`: 24 em cima e embaixo, 12 dos lados e 24 entre os grupos.
        Column {
            id: grupos
            x: 12
            y: 24
            width: rolagem.width - 24
            spacing: 24

            // A capa de 200x300, centrada, com os botões sobre ela (Excluir, Buscar, Abrir arquivo).
            Item {
                width: parent.width
                height: 300

                Item {
                    id: moldura
                    objectName: "capaDaEdicao"
                    x: (parent.width - width) / 2
                    width: 200
                    height: 300

                    // Convertendo: a capa e os botões somem e fica o `Adw.Spinner`.
                    Item {
                        anchors.fill: parent
                        opacity: edicao.convertendoCapa ? 0 : 1
                        enabled: !edicao.convertendoCapa  // somem, e não recebem clique nem Tab
                        Behavior on opacity { enabled: Tema.animacoes; NumberAnimation { duration: Tema.duracaoCurta } }

                        // `.card`: raio 12, o contorno e a sombra; o corte acompanha o raio.
                        Sombra { camadas: Tema.sombraCartao; raio: 12 }
                        Item {
                            id: mascara
                            anchors.fill: parent
                            visible: false
                            layer.enabled: true
                            Rectangle { anchors.fill: parent; radius: 12 }
                        }
                        Item {
                            anchors.fill: parent
                            layer.enabled: true
                            layer.effect: MultiEffect {
                                maskEnabled: true
                                maskSource: mascara
                                maskThresholdMin: 0.5
                                maskSpreadAtMin: 1.0
                            }
                            AnimatedImage {
                                id: previa
                                objectName: "previaDaCapa"
                                // A URL que não se leu (arquivo quebrado): no lugar dela, o placeholder, como na grade.
                                property string ilegivel: ""
                                anchors.fill: parent
                                source: edicao.capa !== "" && edicao.capa !== ilegivel ? edicao.capa : paginaTodos.placeholder
                                // Adiado: o `AnimatedImage` falha dentro da própria atribuição do `source`, que não se reavalia ali.
                                onStatusChanged: if (status === Image.Error && source.toString() === edicao.capa) {
                                    const url = edicao.capa
                                    Qt.callLater(() => ilegivel = url)
                                }
                                // `content-fit: contain`, o padrão do `Gtk.Picture`.
                                fillMode: Image.PreserveAspectFit
                                asynchronous: true
                                cache: false
                            }
                        }

                        BotaoOsd {
                            id: botaoExcluirCapa
                            objectName: "botaoExcluirCapa"
                            x: 80
                            y: 260
                            // O `Revealer` em `crossfade`: a posição é fixa, só a opacidade muda.
                            opacity: edicao.temCapa ? 1 : 0
                            visible: opacity > 0
                            Behavior on opacity { enabled: Tema.animacoes; NumberAnimation { duration: Tema.duracaoCurta } }
                            icone: "user-trash"
                            dica: "Excluir capa"
                            onClicked: edicao.excluirCapa()
                        }
                        BotaoOsd {
                            id: botaoSgdbDaCapa
                            objectName: "botaoEscolherCapaSgdb"
                            x: 120
                            y: 260
                            icone: "edit-find"
                            dica: "Escolher capa no SteamGridDB"
                            onClicked: edicao.seletorDeCapa.abrir(edicao.nome)
                        }
                        BotaoOsd {
                            objectName: "botaoEscolherCapa"
                            x: 160
                            y: 260
                            icone: "document-open"
                            dica: "Escolher capa de um arquivo"
                            onClicked: dialogo.abrirSeletor("capa")
                        }
                    }
                    Girador {
                        anchors.centerIn: parent
                        running: edicao.convertendoCapa
                        visible: running
                    }
                }
            }

            GrupoDeLinhas {
                width: parent.width
                LinhaDeArte {
                    objectName: "linhaDoLogo"
                    titulo: "Logo"
                    subtitulo: edicao.logoSubtitulo
                    ativavel: botaoSgdbDoLogo
                    BotaoDeLinha {
                        objectName: "botaoRestaurarLogo"
                        visible: edicao.logoRestauravel
                        icone: "edit-undo"
                        dica: "Voltar a escolher o logo automaticamente"
                        onClicked: edicao.restaurarLogo()
                    }
                    BotaoDeLinha {
                        id: botaoSgdbDoLogo
                        objectName: "botaoEscolherLogoSgdb"
                        icone: "edit-find"
                        dica: "Escolher logo no SteamGridDB"
                        onClicked: edicao.seletorDeLogo.abrir(edicao.nome)
                    }
                    BotaoDeLinha {
                        objectName: "botaoEscolherLogo"
                        icone: "document-open"
                        dica: "Escolher logo de um arquivo"
                        onClicked: dialogo.abrirSeletor("logo")
                    }
                }
                LinhaDeArte {
                    objectName: "linhaDoPapel"
                    visible: !edicao.zerado
                    titulo: "Papel de parede da sessão"
                    subtitulo: edicao.papelSubtitulo
                    enabled: edicao.papelDisponivel
                    ativavel: botaoWallhavenDoPapel
                    BotaoDeLinha {
                        objectName: "botaoRestaurarPapel"
                        visible: edicao.papelRestauravel
                        icone: "edit-undo"
                        dica: "Voltar a escolher o papel de parede automaticamente"
                        onClicked: edicao.restaurarPapel()
                    }
                    BotaoDeLinha {
                        id: botaoWallhavenDoPapel
                        objectName: "botaoEscolherPapelWallhaven"
                        icone: "edit-find"
                        dica: "Escolher papel de parede no wallhaven"
                        onClicked: edicao.seletorDePapelDeParede.abrir(edicao.nome)
                    }
                    BotaoDeLinha {
                        objectName: "botaoEscolherPapel"
                        icone: "document-open"
                        dica: "Escolher papel de parede de um arquivo"
                        onClicked: dialogo.abrirSeletor("papel")
                    }
                }
                // A cor que as fitas de LED vestem enquanto este jogo corre. Sem escolha, ela sai da capa; por isso
                // o botão de voltar ao automático só aparece quando houve escolha. Cada movimento no seletor já
                // acende as fitas (a prévia); o Aplicar é que grava.
                LinhaDeArte {
                    objectName: "linhaDaFita"
                    visible: !edicao.zerado
                    titulo: "Iluminação inteligente"
                    subtitulo: edicao.fitaSubtitulo
                    enabled: edicao.fitaDisponivel
                    ativavel: botaoDaCorDaFita
                    BotaoDeLinha {
                        objectName: "botaoRestaurarFita"
                        visible: edicao.fitaManual
                        icone: "edit-undo"
                        dica: edicao.dicaDeVoltar
                        onClicked: edicao.redefinirFita()
                    }
                    AmostraDeCor {
                        id: botaoDaCorDaFita
                        objectName: "botaoDaCorDaFita"
                        cor: edicao.fitaCor
                        roda: edicao.fitaAutomatica
                        dica: "Escolher a cor da iluminação inteligente"
                        nomeDoBalao: "balaoDaCorDaFita"
                        nomeDoSeletor: "seletorDeCor"
                        nomeDaAmostra: "amostraDaCor"
                        nomeDaRoda: "amostraEmRoda"
                        onEscolhida: cor => edicao.escolherCorDaFita(cor)
                    }
                }
                LinhaDeNumero {
                    objectName: "linhaDoBrilhoDaFita"
                    visible: !edicao.zerado
                    titulo: "Brilho (%)"
                    // Só diz alguma coisa quando está apagada.
                    subtitulo: edicao.fitaDisponivel ? "" : edicao.fitaSubtitulo
                    enabled: edicao.fitaDisponivel
                    de: 1
                    ate: 100
                    passo: 1
                    pagina: 10
                    value: edicao.fitaBrilho
                    onAlterado: valor => edicao.definirBrilhoDaFita(valor)
                }
            }

            GrupoDeLinhas {
                width: parent.width
                LinhaDeTexto {
                    id: campoNome
                    objectName: "campoNome"
                    titulo: "Título"
                    text: edicao.nome
                    onEditado: edicao.nome = text
                    onConfirmado: campoExecutavel.forceActiveFocus(Qt.TabFocusReason)
                    // O `Gtk.Stack` do botão e do `Adw.Spinner`: um no lugar do outro, o botão sempre ativo.
                    Item {
                        width: 34
                        height: 34
                        Item {
                            anchors.fill: parent
                            opacity: edicao.buscandoMetadados ? 0 : 1
                            // Sem `enabled`: o foco do teclado fica no botão (o modelo ignora o segundo clique).
                            Behavior on opacity { enabled: Tema.animacoes; NumberAnimation { duration: Tema.duracaoCurta } }
                            BotaoDeLinha {
                                objectName: "botaoBuscarMetadados"
                                icone: "folder-download"
                                dica: "Buscar dados na Steam pelo título"
                                onClicked: edicao.buscarMetadados()
                            }
                        }
                        Girador {
                            objectName: "carregandoMetadados"
                            anchors.fill: parent
                            visible: edicao.buscandoMetadados
                            running: visible
                            Accessible.name: "Buscando dados na Steam"
                        }
                    }
                }
                LinhaDeTexto {
                    objectName: "campoDesenvolvedora"
                    titulo: "Desenvolvedora (opcional)"
                    text: edicao.desenvolvedora
                    onEditado: edicao.desenvolvedora = text
                    onConfirmado: campoExecutavel.forceActiveFocus(Qt.TabFocusReason)
                }
                LinhaDeTexto {
                    objectName: "campoPublicadora"
                    titulo: "Publicadora (opcional)"
                    text: edicao.publicadora
                    onEditado: edicao.publicadora = text
                    onConfirmado: campoExecutavel.forceActiveFocus(Qt.TabFocusReason)
                }
                LinhaDeTexto {
                    objectName: "campoLancamento"
                    titulo: "Data de lançamento (opcional)"
                    text: edicao.lancamento
                    onEditado: edicao.lancamento = text
                    onConfirmado: campoExecutavel.forceActiveFocus(Qt.TabFocusReason)
                }
                LinhaDeTexto {
                    objectName: "campoGenero"
                    titulo: "Gênero (opcional)"
                    text: edicao.genero
                    onEditado: edicao.genero = text
                    onConfirmado: campoExecutavel.forceActiveFocus(Qt.TabFocusReason)
                }
                LinhaDeEscolha {
                    objectName: "escolhaDeControle"
                    titulo: "Compatibilidade com controle"
                    model: edicao.opcoesDeControle
                    currentIndex: edicao.controleIndice
                    onEscolhido: indice => edicao.controleIndice = indice
                }
            }

            GrupoDeLinhas {
                width: parent.width
                LinhaDeEscolha {
                    objectName: "escolhaDeStatus"
                    titulo: "Status"
                    model: edicao.opcoesDeStatus
                    currentIndex: edicao.statusIndice
                    onEscolhido: indice => edicao.statusIndice = indice
                }
                LinhaDoGrupo {
                    id: linhaDaNota
                    objectName: "linhaDaNota"
                    titulo: "Minha nota"
                    subtitulo: "Clique na nota para removê-la"
                    reservaADireita: estrelas.width
                    Row {
                        id: estrelas
                        objectName: "estrelasDaNota"
                        anchors { right: parent.right; rightMargin: 14; verticalCenter: parent.verticalCenter }
                        spacing: 0
                        Repeater {
                            model: 5
                            delegate: BotaoDeLinha {
                                required property int index
                                objectName: "estrela" + (index + 1)
                                icone: index < edicao.nota ? "starred" : "non-starred"
                                dica: index === 0 ? "1 estrela" : (index + 1) + " estrelas"
                                onClicked: edicao.definirNota(index + 1)
                            }
                        }
                    }
                }
            }

            // Um zerado não é mais lançado: sem a linha do executável nem a das atualizações.
            GrupoDeLinhas {
                width: parent.width
                visible: !edicao.zerado
                LinhaDeTexto {
                    id: campoExecutavel
                    objectName: "campoExecutavel"
                    titulo: "Executável"
                    text: edicao.executavel
                    onEditado: edicao.executavel = text
                    onConfirmado: if (!edicao.ocupado) edicao.aplicar()
                    BotaoDeLinha {
                        objectName: "botaoSelecionarExecutavel"
                        icone: "document-open"
                        dica: "Selecionar arquivo"
                        onClicked: dialogo.abrirSeletor("executavel")
                    }
                    BotaoDeLinha {
                        objectName: "botaoAbrirPasta"
                        visible: edicao.podeAbrirPasta
                        icone: "folder"
                        dica: "Abrir a pasta do jogo"
                        onClicked: edicao.abrirPasta()
                    }
                }
                LinhaDeAlternancia {
                    objectName: "alternanciaDeAdmin"
                    titulo: "Abrir como administrador"
                    subtitulo: "Inicia o jogo como administrador"
                    checked: edicao.admin
                    onAlternado: edicao.admin = checked
                }
                LinhaDeAlternancia {
                    objectName: "alternanciaDeRastreio"
                    visible: edicao.rastreioVisivel
                    titulo: "Rastrear processo do jogo"
                    subtitulo: "Conta o tempo de jogo pelo nome do executável, em vez de encerrar a sessão manualmente"
                    checked: edicao.rastrearProcesso
                    onAlternado: {
                        edicao.rastrearProcesso = checked
                        if (checked) campoProcesso.forceActiveFocus(Qt.TabFocusReason)
                    }
                }
                LinhaDeTexto {
                    id: campoProcesso
                    objectName: "campoProcesso"
                    visible: edicao.rastreioVisivel && edicao.rastrearProcesso
                    titulo: "Nome do executável"
                    text: edicao.executavelDoProcesso
                    onEditado: edicao.executavelDoProcesso = text
                    onConfirmado: if (!edicao.ocupado) edicao.aplicar()
                }
            }

            GrupoDeLinhas {
                width: parent.width
                visible: !edicao.zerado
                LinhaDeAlternancia {
                    objectName: "alternanciaDeAtualizacoes"
                    titulo: "Notificar sobre atualizações"
                    subtitulo: "Avisa quando houver atualização disponível"
                    checked: edicao.notificarAtualizacoes
                    onAlternado: edicao.notificarAtualizacoes = checked
                }
            }

            GrupoDeLinhas {
                width: parent.width
                LinhaDeAlternancia {
                    objectName: "alternanciaDeConquistas"
                    titulo: "Conquistas"
                    subtitulo: "Acompanha as conquistas deste jogo e mostra o progresso na página do jogo"
                    checked: edicao.conquistas
                    onAlternado: edicao.conquistas = checked
                }
            }

            // `Adw.ExpanderRow`: a linha, a seta que gira e as linhas de dentro, que abrem em 200 ms.
            GrupoDeLinhas {
                width: parent.width
                LinhaDoGrupo {
                    titulo: "Opções avançadas"
                    reservaADireita: 16
                    sobre: botaoDasAvancadas.hovered
                    pressionada: botaoDasAvancadas.down
                    foco: botaoDasAvancadas.visualFocus
                    Button {
                        id: botaoDasAvancadas
                        objectName: "cabecalhoDasAvancadas"
                        anchors.fill: parent
                        focusPolicy: Qt.StrongFocus
                        hoverEnabled: true
                        text: "Opções avançadas"
                        Accessible.name: text
                        Accessible.role: Accessible.Button
                        Keys.onReturnPressed: click()
                        Keys.onEnterPressed: click()
                        onClicked: dialogo.avancadasAbertas = !dialogo.avancadasAbertas
                        contentItem: Item {}
                        background: Item {}
                    }
                    Icone {
                        anchors { right: parent.right; rightMargin: 14; verticalCenter: parent.verticalCenter }
                        nome: "pan-down"
                        // `.expander-row-arrow`: 55% fechada; aberta, 100% e na cor de destaque.
                        cor: dialogo.avancadasAbertas ? Tema.destaqueTexto : Tema.texto
                        opacity: dialogo.avancadasAbertas ? 1 : Tema.opacidadeApagado
                        rotation: dialogo.avancadasAbertas ? 180 : 0
                        Behavior on rotation { enabled: Tema.animacoes; NumberAnimation { duration: Tema.duracaoCurta; easing { type: Easing.Bezier; bezierCurve: Tema.curva } } }
                    }
                }
                Item {
                    width: parent.width
                    height: dialogo.avancadasAbertas ? avancadas.implicitHeight : 0
                    visible: height > 0
                    clip: true
                    Behavior on height { enabled: Tema.animacoes; NumberAnimation { duration: Tema.duracaoCurta; easing { type: Easing.Bezier; bezierCurve: Tema.curva } } }
                    Column {
                        id: avancadas
                        width: parent.width
                        // O 1 px de cima: a primeira linha de dentro não é a primeira do cartão (nem arredonda em cima).
                        topPadding: 1
                        LinhaDeTexto {
                            id: campoAppid
                            objectName: "campoAppid"
                            erro: !edicao.appidValido
                            titulo: "AppID da Steam"
                            inputMethodHints: Qt.ImhDigitsOnly
                            text: edicao.appid
                            onEditado: edicao.appid = text
                            // Enter no AppID não aplica: só o executável e o nome do processo chamam o Aplicar.
                            BotaoDeLinha {
                                objectName: "botaoBuscarAppid"
                                enabled: edicao.nome.trim() !== ""
                                icone: "edit-find"
                                dica: "Buscar na Steam"
                                onClicked: edicao.buscarAppid()
                            }
                        }
                        LinhaDeAcao {
                            objectName: "linhaDoLudusavi"
                            titulo: "Jogo no Ludusavi"
                            subtitulo: edicao.ludusaviSubtitulo
                            icone: "go-next"
                            enabled: edicao.ludusaviDisponivel
                            onAcionada: edicao.escolherJogoNoLudusavi()
                        }
                    }
                }
            }
        }
    }
}
