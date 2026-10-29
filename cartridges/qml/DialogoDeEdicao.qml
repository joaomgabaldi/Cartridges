import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Dialogs
import QtQuick.Window

// O diálogo de editar um jogo e o de adicionar um novo. Só desenha: o que ele edita é o `edicao`
// (cartridges/modelos/edicao.py) e a regra de validar e gravar é de cartridges/edicao.py.
// Modal para o mouse, o teclado e o controle; o foco volta a quem o abriu.
// Ainda sem os grupos de capa, logo e papel de parede (tarefa 7) e o de iluminação inteligente (plano 5).
Rectangle {
    id: dialogo
    objectName: "dialogoDeEdicao"

    // Quem tinha o foco ao abrir, e o último foco dentro do diálogo (para o devolver depois de um erro).
    property Item retorno: null
    property Item ultimoFoco: null
    property bool avancadasAbertas: false

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

    // Criado só ao clicar: o seletor nativo não precisa existir antes.
    Loader {
        id: cargaDoSeletor
        active: false
        sourceComponent: FileDialog {
            title: "Selecionar arquivo"
            nameFilters: ["Executáveis (*.exe *.bat *.cmd *.lnk *.url)"]
            onAccepted: edicao.escolherExecutavel(selectedFile)
        }
        onLoaded: item.open()
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

                GrupoDeLinhas {
                    width: parent.width
                    LinhaDeTexto {
                        id: campoNome
                        objectName: "campoNome"
                        titulo: "Título"
                        text: edicao.nome
                        onEditado: edicao.nome = text
                        onConfirmado: campoExecutavel.forceActiveFocus(Qt.TabFocusReason)
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
                            // O `Loader` é síncrono: ao ativar, o `onLoaded` já abre o seletor.
                            onClicked: { if (cargaDoSeletor.item) cargaDoSeletor.item.open(); else cargaDoSeletor.active = true }
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
                    // shortcut: o botão "Buscar na Steam" desta linha, o "Buscar dados na Steam pelo título" da
                    // linha do título e o seletor da linha do Ludusavi entram com a tarefa 9; até lá a linha
                    // só mostra o AppID e o jogo escolhido.
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
                    }
                    Item {
                        id: linhaDoLudusavi
                        objectName: "linhaDoLudusavi"
                        visible: dialogo.avancadasAbertas
                        width: parent.width
                        implicitHeight: 58
                        Rectangle { width: parent.width; height: 1; color: Tema.borda; visible: linhaDoLudusavi.y > 0 }
                        Column {
                            anchors { left: parent.left; leftMargin: 16; right: parent.right; rightMargin: 16; verticalCenter: parent.verticalCenter }
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
