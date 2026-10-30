import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Dialogs
import QtQuick.Shapes
import QtQuick.Window

// O diálogo de editar um jogo e o de adicionar um novo. Só desenha: o que ele edita é o `edicao`
// (cartridges/modelos/edicao.py) e a regra de validar e gravar é de cartridges/edicao.py.
// Modal para o mouse, o teclado e o controle; o foco volta a quem o abriu.
Rectangle {
    id: dialogo
    objectName: "dialogoDeEdicao"

    // Quem tinha o foco ao abrir, e o último foco dentro do diálogo (para o devolver depois de um erro).
    property Item retorno: null
    property Item ultimoFoco: null
    property bool avancadasAbertas: false
    // O que o seletor de arquivo aberto escolhe: "executavel", "capa", "logo" ou "papel".
    property string alvoDoSeletor: "executavel"

    function dentro(item) {
        for (var p = item; p; p = p.parentItem)
            if (p === dialogo) return true
        return false
    }
    function devolverFoco() { (ultimoFoco && dentro(ultimoFoco) ? ultimoFoco : campoNome).forceActiveFocus(Qt.TabFocusReason) }
    // O campo com o foco fica à vista na rolagem.
    function mostrar(item) {
        var topo = item.mapToItem(rolagem.contentItem, 0, 0).y
        var base = topo + item.height
        if (topo < rolagem.contentY) rolagem.contentY = Math.max(0, topo - 8)
        else if (base > rolagem.contentY + rolagem.height) rolagem.contentY = base - rolagem.height + 8
    }

    anchors.fill: parent
    visible: edicao.aberto
    color: "#80000000"
    Keys.onEscapePressed: edicao.cancelar()
    // Modal para o teclado e o controle: nenhuma tecla chega à página de trás.
    // O Tab gira dentro do diálogo porque a janela de trás fica desabilitada enquanto ele está aberto.
    Keys.onPressed: event => event.accepted = true

    onVisibleChanged: {
        if (visible) {
            retorno = Window.window ? Window.window.activeFocusItem : null
            avancadasAbertas = false
            rolagem.contentY = 0
            campoNome.forceActiveFocus(Qt.TabFocusReason)
        } else {
            // Depois da reação das outras bindings ao `aberto` (a página de trás volta a ficar habilitada).
            Qt.callLater(devolverAoRetorno)
        }
    }
    // Quem abriu pode ter sumido (um menu que fechou ao escolher "Editar"): então o foco vai à página à vista.
    function devolverAoRetorno() {
        if (visible) return
        if (retorno && retorno.visible && retorno.enabled) retorno.forceActiveFocus(Qt.TabFocusReason)
        else dialogo.retornoPerdido()
    }
    signal retornoPerdido()

    Connections {
        target: Window.window
        function onActiveFocusItemChanged() {
            var foco = Window.window.activeFocusItem
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

    MouseArea { anchors.fill: parent } // o que está embaixo não recebe cliques

    component BotaoDoCabecalho: Button {
        id: botao
        property color cor: Tema.superficie
        property color corDoTexto: Tema.texto
        focusPolicy: Qt.StrongFocus
        implicitHeight: 34
        leftPadding: 18
        rightPadding: 18
        contentItem: Text {
            text: botao.text
            textFormat: Text.PlainText
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            color: botao.corDoTexto
            opacity: botao.enabled ? 1 : 0.5
            font { family: Tema.fonte; pixelSize: 14 }
        }
        background: Rectangle {
            radius: 6
            color: botao.cor
            opacity: !botao.enabled ? 0.5 : botao.down ? 0.75 : botao.hovered ? 0.9 : 1
            border { width: botao.visualFocus ? 2 : 1; color: botao.visualFocus ? Tema.texto : Tema.borda }
        }
    }

    component BotaoDeLinha: Button {
        id: botao
        property string glifo
        property string dica
        focusPolicy: Qt.StrongFocus
        implicitWidth: 34
        implicitHeight: 34
        Accessible.name: dica
        ToolTip.visible: hovered && dica !== ""
        ToolTip.text: dica
        ToolTip.delay: 600
        contentItem: Text {
            text: botao.glifo
            textFormat: Text.PlainText
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            color: Tema.texto
            font { family: Tema.fonteDeIcones; pixelSize: 16 }
        }
        background: Rectangle {
            radius: 6
            color: botao.down ? Tema.pressionado : botao.hovered ? Tema.botaoSobre : "transparent"
            border { width: botao.visualFocus ? 2 : 0; color: Tema.destaque }
        }
    }

    // Criado só ao clicar: o seletor nativo não precisa existir antes. Um só serve aos quatro usos.
    function abrirSeletor(alvo) {
        alvoDoSeletor = alvo
        // O `Loader` é síncrono: ao ativar, o `onLoaded` já abre o seletor.
        if (cargaDoSeletor.item) cargaDoSeletor.item.open(); else cargaDoSeletor.active = true
    }
    Loader {
        id: cargaDoSeletor
        active: false
        sourceComponent: FileDialog {
            title: dialogo.alvoDoSeletor === "capa" ? "Escolher capa de um arquivo"
                : dialogo.alvoDoSeletor === "logo" ? "Escolher logo de um arquivo"
                : dialogo.alvoDoSeletor === "papel" ? "Escolher papel de parede de um arquivo" : "Selecionar arquivo"
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

    component BotaoDaCapa: BotaoDeLinha {
        id: botaoDaCapa
        contentItem: Text {
            text: botaoDaCapa.glifo
            textFormat: Text.PlainText
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            color: "white"
            font { family: Tema.fonteDeIcones; pixelSize: 16 }
        }
        background: Rectangle {
            radius: 17
            color: botaoDaCapa.down ? "#e6000000" : botaoDaCapa.hovered ? "#cc000000" : "#99000000"
            border { width: botaoDaCapa.visualFocus ? 2 : 0; color: Tema.destaque }
        }
    }

    // Uma linha do logo ou do papel de parede: o título, o estado em texto e os botões à direita.
    component LinhaDeArte: Item {
        id: linhaDeArte
        property string titulo
        property string subtitulo
        default property alias botoes: lado.data
        width: parent.width
        implicitHeight: 58
        Rectangle { width: parent.width; height: 1; color: Tema.borda; visible: linhaDeArte.y > 0 }
        Column {
            anchors { left: parent.left; leftMargin: 16; right: lado.left; rightMargin: 8; verticalCenter: parent.verticalCenter }
            Text {
                width: parent.width
                text: linhaDeArte.titulo
                textFormat: Text.PlainText
                elide: Text.ElideRight
                color: Tema.texto
                font { family: Tema.fonte; pixelSize: 15 }
            }
            Text {
                objectName: linhaDeArte.objectName + "Subtitulo"
                width: parent.width
                visible: text !== ""
                text: linhaDeArte.subtitulo
                textFormat: Text.PlainText
                elide: Text.ElideRight
                color: Tema.textoSecundario
                font { family: Tema.fonte; pixelSize: 12 }
            }
        }
        Row {
            id: lado
            anchors { right: parent.right; rightMargin: 8; verticalCenter: parent.verticalCenter }
            spacing: 4
        }
    }

    Rectangle {
        id: cartao
        anchors.centerIn: parent
        width: Math.min(480, parent.width - 48)
        height: Math.min(parent.height - 48, 760)
        radius: 8
        color: Tema.fundo
        border.color: Tema.botaoSobre
        clip: true
        // Com um seletor aberto por cima, nada daqui recebe o mouse nem o Tab.
        enabled: !edicao.seletorDeCapa.aberto && !edicao.seletorDeLogo.aberto && !edicao.seletorDePapelDeParede.aberto
            && !edicao.seletorDaSteam.aberto && !edicao.seletorDoLudusavi.aberto

        Flickable {
            id: rolagem
            anchors { left: parent.left; right: parent.right; top: cabecalho.bottom; bottom: parent.bottom }
            contentWidth: width
            contentHeight: grupos.implicitHeight + 32
            boundsBehavior: Flickable.StopAtBounds
            clip: true
            ScrollBar.vertical: BarraDeRolagem {}

            Column {
                id: grupos
                x: 16
                y: 8
                width: rolagem.width - 32
                spacing: 16

                // A capa 200x300 com os botões sobre ela, como na tela de detalhes do jogo.
                Item {
                    width: parent.width
                    height: 300
                    Rectangle {
                        id: moldura
                        objectName: "capaDaEdicao"
                        x: (parent.width - width) / 2
                        width: 200
                        height: 300
                        radius: 8
                        color: Tema.superficie
                        border.color: Tema.borda
                        clip: true
                        AnimatedImage {
                            id: previa
                            objectName: "previaDaCapa"
                            anchors.fill: parent
                            source: edicao.capa !== "" ? edicao.capa : paginaTodos.placeholder
                            fillMode: Image.PreserveAspectCrop
                            asynchronous: true
                            cache: false
                            opacity: edicao.convertendoCapa ? 0.3 : 1
                        }
                        BusyIndicator {
                            anchors.centerIn: parent
                            running: edicao.convertendoCapa
                            visible: running
                        }
                        Row {
                            anchors { right: parent.right; bottom: parent.bottom; rightMargin: 6; bottomMargin: 6 }
                            spacing: 6
                            BotaoDaCapa {
                                id: botaoSgdbDaCapa
                                objectName: "botaoEscolherCapaSgdb"
                                glifo: ""  // buscar
                                dica: "Escolher capa no SteamGridDB"
                                onClicked: edicao.seletorDeCapa.abrir(edicao.nome)
                            }
                            BotaoDaCapa {
                                objectName: "botaoExcluirCapa"
                                visible: edicao.temCapa
                                glifo: "\uE74D"  // lixeira
                                dica: "Excluir capa"
                                onClicked: edicao.excluirCapa()
                            }
                            BotaoDaCapa {
                                objectName: "botaoEscolherCapa"
                                glifo: "\uE8E5"  // abrir arquivo
                                dica: "Escolher capa de um arquivo"
                                onClicked: dialogo.abrirSeletor("capa")
                            }
                        }
                    }
                }

                GrupoDeLinhas {
                    width: parent.width
                    LinhaDeArte {
                        objectName: "linhaDoLogo"
                        titulo: "Logo"
                        subtitulo: edicao.logoSubtitulo
                        BotaoDeLinha {
                            objectName: "botaoRestaurarLogo"
                            visible: edicao.logoRestauravel
                            glifo: "\uE7A7"  // desfazer
                            dica: "Voltar a escolher o logo automaticamente"
                            onClicked: edicao.restaurarLogo()
                        }
                        BotaoDeLinha {
                            id: botaoSgdbDoLogo
                            objectName: "botaoEscolherLogoSgdb"
                            glifo: ""  // buscar
                            dica: "Escolher logo no SteamGridDB"
                            onClicked: edicao.seletorDeLogo.abrir(edicao.nome)
                        }
                        BotaoDeLinha {
                            objectName: "botaoEscolherLogo"
                            glifo: "\uE8E5"  // abrir arquivo
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
                        BotaoDeLinha {
                            objectName: "botaoRestaurarPapel"
                            visible: edicao.papelRestauravel
                            glifo: "\uE7A7"  // desfazer
                            dica: "Voltar a escolher o papel de parede automaticamente"
                            onClicked: edicao.restaurarPapel()
                        }
                        BotaoDeLinha {
                            id: botaoWallhavenDoPapel
                            objectName: "botaoEscolherPapelWallhaven"
                            glifo: ""  // buscar
                            dica: "Escolher papel de parede no wallhaven"
                            onClicked: edicao.seletorDePapelDeParede.abrir(edicao.nome)
                        }
                        BotaoDeLinha {
                            objectName: "botaoEscolherPapel"
                            glifo: "\uE8E5"  // abrir arquivo
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
                        BotaoDeLinha {
                            objectName: "botaoRestaurarFita"
                            visible: edicao.fitaManual
                            glifo: "\uE7A7"  // desfazer
                            dica: edicao.dicaDeVoltar
                            onClicked: edicao.redefinirFita()
                        }
                        BotaoDeLinha {
                            id: botaoDaCorDaFita
                            objectName: "botaoDaCorDaFita"
                            dica: "Escolher a cor da iluminação inteligente"
                            onClicked: balaoDaCorDaFita.opened ? balaoDaCorDaFita.close() : balaoDaCorDaFita.open()
                            // A amostra de 22x22: a cor escolhida, ou uma roda de cores quando a cor acompanha a tela.
                            Rectangle {
                                objectName: "amostraDaCor"
                                anchors.centerIn: parent
                                width: 22
                                height: 22
                                radius: 11
                                visible: !edicao.fitaAutomatica
                                color: edicao.fitaCor
                                border { width: 1; color: Tema.borda }
                            }
                            Shape {
                                objectName: "amostraEmRoda"
                                anchors.centerIn: parent
                                width: 22
                                height: 22
                                visible: edicao.fitaAutomatica
                                ShapePath {
                                    strokeWidth: -1
                                    fillGradient: ConicalGradient {
                                        centerX: 11
                                        centerY: 11
                                        angle: 90
                                        GradientStop { position: 0 / 6; color: "#ff0000" }
                                        GradientStop { position: 1 / 6; color: "#ffff00" }
                                        GradientStop { position: 2 / 6; color: "#00ff00" }
                                        GradientStop { position: 3 / 6; color: "#00ffff" }
                                        GradientStop { position: 4 / 6; color: "#0000ff" }
                                        GradientStop { position: 5 / 6; color: "#ff00ff" }
                                        GradientStop { position: 6 / 6; color: "#ff0000" }
                                    }
                                    PathAngleArc { centerX: 11; centerY: 11; radiusX: 11; radiusY: 11; startAngle: 0; sweepAngle: 360 }
                                }
                                // O furo do meio, como numa roda de cores.
                                Rectangle { anchors.centerIn: parent; width: 8; height: 8; radius: 4; color: Tema.superficie }
                            }
                            Popup {
                                id: balaoDaCorDaFita
                                objectName: "balaoDaCorDaFita"
                                x: botaoDaCorDaFita.width - width
                                y: botaoDaCorDaFita.height + 4
                                padding: 12
                                margins: 8  // o balão não sai da janela, mesmo com a linha no pé da rolagem
                                closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
                                // O seletor parte da cor que a linha mostra agora; depois disso quem manda nele é a mão.
                                onAboutToShow: {
                                    var cor = edicao.fitaCor
                                    seletorDeCor.matiz = Math.max(0, cor.hsvHue) * 360
                                    seletorDeCor.saturacao = Math.round(cor.hsvSaturation * 1000)
                                }
                                onOpened: seletorDeCor.forceActiveFocus(Qt.TabFocusReason)
                                onClosed: botaoDaCorDaFita.forceActiveFocus(Qt.TabFocusReason)
                                background: Rectangle { color: Tema.superficie; border.color: Tema.borda; radius: 8 }
                                contentItem: SeletorDeCor {
                                    id: seletorDeCor
                                    objectName: "seletorDeCor"
                                    onEscolhida: cor => edicao.escolherCorDaFita(cor)
                                }
                            }
                        }
                    }
                    LinhaDeArte {
                        objectName: "linhaDoBrilhoDaFita"
                        visible: !edicao.zerado
                        titulo: "Brilho (%)"
                        // Só diz alguma coisa quando está apagada.
                        subtitulo: edicao.fitaDisponivel ? "" : edicao.fitaSubtitulo
                        enabled: edicao.fitaDisponivel
                        SpinBox {
                            id: caixaDoBrilho
                            objectName: "caixaDoBrilhoDaFita"
                            from: 1
                            to: 100
                            value: edicao.fitaBrilho
                            focusPolicy: Qt.StrongFocus
                            Accessible.name: "Brilho (%)"
                            onValueModified: edicao.definirBrilhoDaFita(value)
                            contentItem: Text {
                                text: caixaDoBrilho.value
                                textFormat: Text.PlainText
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                                color: Tema.texto
                                font { family: Tema.fonte; pixelSize: 15 }
                            }
                            up.indicator: Text {
                                x: caixaDoBrilho.width - width - 8
                                anchors.verticalCenter: parent.verticalCenter
                                text: "+"
                                textFormat: Text.PlainText
                                color: caixaDoBrilho.up.pressed ? Tema.destaque : Tema.texto
                                opacity: caixaDoBrilho.enabled ? 1 : 0.4
                                font { family: Tema.fonte; pixelSize: 18 }
                            }
                            down.indicator: Text {
                                x: 8
                                anchors.verticalCenter: parent.verticalCenter
                                text: "\u2212"
                                textFormat: Text.PlainText
                                color: caixaDoBrilho.down.pressed ? Tema.destaque : Tema.texto
                                opacity: caixaDoBrilho.enabled ? 1 : 0.4
                                font { family: Tema.fonte; pixelSize: 18 }
                            }
                            background: Rectangle {
                                implicitWidth: 104
                                implicitHeight: 34
                                radius: 6
                                color: "transparent"
                                border { width: caixaDoBrilho.visualFocus ? 2 : 1; color: caixaDoBrilho.visualFocus ? Tema.destaque : Tema.borda }
                            }
                        }
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
                        BotaoDeLinha {
                            objectName: "botaoBuscarMetadados"
                            // Fica no lugar durante a busca (o foco não se perde); o modelo ignora o segundo clique.
                            opacity: edicao.buscandoMetadados ? 0.4 : 1
                            enabled: edicao.nome.trim() !== ""
                            glifo: "\uE896"  // baixar
                            dica: "Buscar dados na Steam pelo título"
                            onClicked: edicao.buscarMetadados()
                        }
                        BusyIndicator {
                            objectName: "carregandoMetadados"
                            visible: edicao.buscandoMetadados
                            running: visible
                            implicitWidth: 34
                            implicitHeight: 34
                            Accessible.name: "Buscando dados na Steam"
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
                    Item {
                        id: linhaDaNota
                        width: parent.width
                        implicitHeight: 64
                        Rectangle { width: parent.width; height: 1; color: Tema.borda; visible: linhaDaNota.y > 0 }
                        Column {
                            anchors { left: parent.left; leftMargin: 16; right: estrelas.left; rightMargin: 8; verticalCenter: parent.verticalCenter }
                            spacing: 2
                            Text {
                                width: parent.width
                                text: "Minha nota"
                                textFormat: Text.PlainText
                                color: Tema.texto
                                font { family: Tema.fonte; pixelSize: 15 }
                            }
                            Text {
                                width: parent.width
                                text: "Clique na nota para removê-la"
                                textFormat: Text.PlainText
                                wrapMode: Text.Wrap
                                color: Tema.textoSecundario
                                font { family: Tema.fonte; pixelSize: 12 }
                            }
                        }
                        Row {
                            id: estrelas
                            objectName: "estrelasDaNota"
                            anchors { right: parent.right; rightMargin: 8; verticalCenter: parent.verticalCenter }
                            Repeater {
                                model: 5
                                delegate: BotaoDeLinha {
                                    required property int index
                                    objectName: "estrela" + (index + 1)
                                    glifo: index < edicao.nota ? "" : ""  // estrela cheia ou vazia
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
                            glifo: ""  // abrir arquivo
                            dica: "Selecionar arquivo"
                            onClicked: dialogo.abrirSeletor("executavel")
                        }
                        BotaoDeLinha {
                            objectName: "botaoAbrirPasta"
                            visible: edicao.podeAbrirPasta
                            glifo: ""  // pasta
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

                GrupoDeLinhas {
                    width: parent.width
                    Button {
                        id: cabecalhoDasAvancadas
                        objectName: "cabecalhoDasAvancadas"
                        width: parent.width
                        implicitHeight: 52
                        focusPolicy: Qt.StrongFocus
                        text: "Opções avançadas"
                        Accessible.name: text
                        Accessible.role: Accessible.Button
                        onClicked: dialogo.avancadasAbertas = !dialogo.avancadasAbertas
                        contentItem: Text {
                            leftPadding: 16
                            text: cabecalhoDasAvancadas.text
                            textFormat: Text.PlainText
                            verticalAlignment: Text.AlignVCenter
                            color: Tema.texto
                            font { family: Tema.fonte; pixelSize: 15 }
                        }
                        background: Rectangle {
                            radius: 8
                            color: cabecalhoDasAvancadas.hovered ? Tema.botaoSobre : "transparent"
                            border { width: cabecalhoDasAvancadas.visualFocus ? 2 : 0; color: Tema.destaque }
                            Text {
                                anchors { right: parent.right; rightMargin: 16; verticalCenter: parent.verticalCenter }
                                text: dialogo.avancadasAbertas ? "" : ""  // seta para cima ou para baixo
                                textFormat: Text.PlainText
                                color: Tema.textoSecundario
                                font { family: Tema.fonteDeIcones; pixelSize: 12 }
                            }
                        }
                    }
                    LinhaDeTexto {
                        id: campoAppid
                        objectName: "campoAppid"
                        visible: dialogo.avancadasAbertas
                        erro: !edicao.appidValido
                        titulo: "AppID da Steam"
                        inputMethodHints: Qt.ImhDigitsOnly
                        text: edicao.appid
                        onEditado: edicao.appid = text
                        onConfirmado: if (!edicao.ocupado) edicao.aplicar()
                        BotaoDeLinha {
                            objectName: "botaoBuscarAppid"
                            enabled: edicao.nome.trim() !== ""
                            glifo: "\uE721"  // buscar
                            dica: "Buscar na Steam"
                            onClicked: edicao.buscarAppid()
                        }
                    }
                    Item {
                        id: linhaDoLudusavi
                        objectName: "linhaDoLudusavi"
                        visible: dialogo.avancadasAbertas
                        width: parent.width
                        implicitHeight: 58
                        Rectangle { width: parent.width; height: 1; color: Tema.borda; visible: linhaDoLudusavi.y > 0 }
                        // A linha inteira é o botão que abre o seletor; sem a lista baixada, ela fica desabilitada.
                        Button {
                            id: botaoDoLudusavi
                            objectName: "botaoJogoNoLudusavi"
                            anchors.fill: parent
                            enabled: edicao.ludusaviDisponivel
                            focusPolicy: Qt.StrongFocus
                            Accessible.name: "Jogo no Ludusavi: " + edicao.ludusaviSubtitulo
                            Accessible.role: Accessible.Button
                            Keys.onReturnPressed: click()
                            Keys.onEnterPressed: click()
                            onClicked: edicao.escolherJogoNoLudusavi()
                            contentItem: Item {}
                            background: Rectangle {
                                radius: 8
                                color: botaoDoLudusavi.down ? Tema.pressionado : botaoDoLudusavi.hovered ? Tema.botaoSobre : "transparent"
                                border { width: botaoDoLudusavi.visualFocus ? 2 : 0; color: Tema.destaque }
                            }
                        }
                        Text {
                            anchors { right: parent.right; rightMargin: 16; verticalCenter: parent.verticalCenter }
                            visible: edicao.ludusaviDisponivel
                            text: "\uE76C"  // seta para a direita
                            textFormat: Text.PlainText
                            color: Tema.textoSecundario
                            font { family: Tema.fonteDeIcones; pixelSize: 12 }
                        }
                        Column {
                            anchors { left: parent.left; leftMargin: 16; right: parent.right; rightMargin: 36; verticalCenter: parent.verticalCenter }
                            Text {
                                width: parent.width
                                text: "Jogo no Ludusavi"
                                textFormat: Text.PlainText
                                color: Tema.textoSecundario
                                font { family: Tema.fonte; pixelSize: 12 }
                            }
                            Text {
                                objectName: "subtituloDoLudusavi"
                                width: parent.width
                                text: edicao.ludusaviSubtitulo
                                textFormat: Text.PlainText
                                elide: Text.ElideRight
                                color: Tema.texto
                                font { family: Tema.fonte; pixelSize: 15 }
                            }
                        }
                    }
                }
            }
        }

        // O cabeçalho vem depois da rolagem na árvore, para a ordem do Tab ser: os campos, "Cancelar", "Aplicar".
        Rectangle {
            id: cabecalho
            anchors { left: parent.left; right: parent.right; top: parent.top }
            height: 56
            color: Tema.fundo
            Rectangle { anchors { left: parent.left; right: parent.right; bottom: parent.bottom } height: 1; color: Tema.borda }

            BotaoDoCabecalho {
                id: botaoCancelar
                objectName: "botaoCancelarDaEdicao"
                anchors { left: parent.left; leftMargin: 12; verticalCenter: parent.verticalCenter }
                text: "Cancelar"
                onClicked: edicao.cancelar()
            }
            Text {
                objectName: "tituloDaEdicao"
                anchors { left: botaoCancelar.right; right: botaoAplicar.left; leftMargin: 8; rightMargin: 8; verticalCenter: parent.verticalCenter }
                text: edicao.titulo
                textFormat: Text.PlainText
                horizontalAlignment: Text.AlignHCenter
                elide: Text.ElideRight
                color: Tema.texto
                font { family: Tema.fonte; pixelSize: 16; weight: Font.DemiBold }
                Accessible.role: Accessible.Heading
                Accessible.name: text
            }
            BotaoDoCabecalho {
                id: botaoAplicar
                objectName: "botaoAplicarDaEdicao"
                anchors { right: parent.right; rightMargin: 12; verticalCenter: parent.verticalCenter }
                text: edicao.rotuloDoAplicar
                enabled: !edicao.ocupado && edicao.appidValido
                cor: Tema.destaque
                corDoTexto: "white"
                onClicked: edicao.aplicar()
            }
        }
    }
}
