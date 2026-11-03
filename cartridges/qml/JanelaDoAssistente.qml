import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Dialogs
import QtQuick.Effects
import QtQuick.Window

// O assistente da primeira abertura (D86): janela própria com a barra do app (`Adw.HeaderBar` sem título, minimizar e
// fechar; 640x640 no total, o conteúdo com 593), antes da biblioteca, num motor próprio. As oito telas do `.blp` da `main` num carrossel sem gesto, os pontos e o rodapé
// "Voltar" | "Pular" "Continuar". Só desenha: o que ele mostra e grava é o `assistente` (cartridges/assistente.py).
// Os modais por cima (iluminação, logins, aviso) deixam o fundo `enabled: false`.
Window {
    id: raiz
    objectName: "janelaDoAssistente"

    // A context property com outro nome: dentro do `ConfiguracaoDasFitas` (que tem a propriedade `assistente`) o nome
    // resolveria para a própria propriedade.
    readonly property var modelo: assistente
    readonly property string paginaAtual: modelo.paginas[modelo.indice] || ""
    readonly property bool modalAberto: fitas.visible || loginEpic.visible || loginEa.visible || dialogo.visible
    // Sem a marca `comAgente` (os testes), não há ponte do QWindowKit e a moldura é a nativa.
    readonly property bool semAgente: typeof comAgente === "undefined"
    readonly property QtObject agente: carga.item
    readonly property real topo: semAgente ? 0 : barra.altura

    title: "Cartridges"
    width: 640
    height: 640
    minimumWidth: 640
    maximumWidth: 640
    minimumHeight: 640
    maximumHeight: 640
    color: Tema.fundo
    flags: semAgente ? Qt.Window | Qt.CustomizeWindowHint | Qt.WindowTitleHint | Qt.WindowMinimizeButtonHint | Qt.WindowCloseButtonHint : Qt.Window
    visible: true

    Loader {
        id: carga
        active: !raiz.semAgente
        source: "AgenteDaJanela.qml"
    }
    Connections {
        target: Tema
        function onEscuroChanged() { if (raiz.agente) raiz.agente.setWindowAttribute("dark-mode", Tema.escuro) }
    }

    onClosing: (fechar) => fechar.accepted = raiz.modelo.fecharNoX()

    // O foco do teclado acompanha a tela: quem o tinha pode ter sumido (a tela saiu da vista, o rodapé escondeu, um
    // modal fechou com o fundo desabilitado e o devolveu à janela). Aí ele vai ao primeiro controle da tela.
    function recuperarFoco() {
        if (raiz.modalAberto) return
        var foco = raiz.activeFocusItem
        if (foco && foco !== raiz.contentItem && foco.visible && foco.enabled) return
        for (var i = 0; i < fileira.children.length; ++i) {
            var pagina = fileira.children[i]
            if (pagina.nome === raiz.paginaAtual && pagina.primeiro) pagina.primeiro.forceActiveFocus(Qt.TabFocusReason)
        }
    }
    onPaginaAtualChanged: Qt.callLater(raiz.recuperarFoco)
    onModalAbertoChanged: if (!modalAberto) Qt.callLater(() => Qt.callLater(raiz.recuperarFoco))
    // O tamanho só depois do `setup`: antes, o QWindowKit o sobrescreve.
    Component.onCompleted: {
        if (agente) {
            agente.setup(raiz)
            agente.setWindowAttribute("dark-mode", Tema.escuro)
            barra.ligarAgente()
            width = 640
            height = 640
            minimumWidth = maximumWidth = 640
            minimumHeight = maximumHeight = 640
        }
        Qt.callLater(raiz.recuperarFoco)
    }

    Connections {
        target: raiz.modelo
        function onDialogoPedido(titulo, corpo) { dialogo.abrir(titulo, corpo, [], "") }
    }

    // Criados só ao clicar: o seletor nativo não precisa existir antes.
    Loader {
        id: cargaDaPasta
        active: false
        sourceComponent: FolderDialog {
            onAccepted: raiz.modelo.escolherPasta(selectedFolder)
        }
        onLoaded: item.open()
    }
    Loader {
        id: cargaDoBackup
        active: false
        sourceComponent: FileDialog {
            fileMode: FileDialog.OpenFile
            nameFilters: ["Backup do Cartridges (*.zip)"]
            onAccepted: raiz.modelo.restaurarBackup(selectedFile)
        }
        onLoaded: item.open()
    }

    // Uma tela, como o `Adw.StatusPage` (`adw.css:1920`): margem 36/12 e espaço 36 entre o ícone, o texto e o conteúdo; o
    // título e a descrição a 12. `compacta` (a das conquistas): ícone de 96, título title-2, margem 24 e espaço 24. Com
    // rolagem quando não cabe. Só a tela à vista fica habilitada: o Tab não alcança as outras.
    component Pagina: Flickable {
        id: pagina
        property string nome
        property string icone
        property string imagem
        property string titulo
        property string descricao
        property bool compacta: false
        // O controle que recebe o foco quando a tela aparece.
        property Item primeiro: null
        default property alias conteudo: extra.data

        objectName: "pagina_" + nome
        visible: raiz.modelo.paginas.indexOf(nome) >= 0
        enabled: raiz.paginaAtual === nome
        width: carrossel.width
        height: carrossel.height
        contentWidth: width
        contentHeight: Math.max(height, coluna.implicitHeight + 2 * (compacta ? 24 : 36))
        interactive: contentHeight > height
        boundsBehavior: Flickable.StopAtBounds
        clip: true
        ScrollBar.vertical: BarraDeRolagem {}

        Column {
            id: coluna
            x: 12
            y: Math.max(pagina.compacta ? 24 : 36, (pagina.height - implicitHeight) / 2)
            width: pagina.width - 24
            spacing: pagina.compacta ? 24 : 36

            Image {
                objectName: "imagem_" + pagina.nome
                anchors.horizontalCenter: parent.horizontalCenter
                visible: pagina.imagem !== ""
                source: pagina.imagem
                sourceSize: Qt.size(128, 128)
                width: 128
                height: 128
            }
            Icone {
                objectName: "icone_" + pagina.nome
                anchors.horizontalCenter: parent.horizontalCenter
                visible: pagina.icone !== ""
                nome: pagina.icone
                tamanho: pagina.compacta ? 96 : 128
                opacity: Tema.opacidadeApagado
            }
            Column {
                width: parent.width
                spacing: 12
                Text {
                    objectName: "titulo_" + pagina.nome
                    width: parent.width
                    text: pagina.titulo
                    textFormat: Text.PlainText
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.Wrap
                    color: Tema.texto
                    font {
                        family: Tema.fonte
                        pixelSize: pagina.compacta ? Tema.titulo2 : Tema.titulo1
                        weight: pagina.compacta ? Tema.pesoTitulo2 : Tema.pesoTitulo1
                    }
                    Accessible.role: Accessible.Heading
                    Accessible.name: text
                }
                Text {
                    objectName: "descricao_" + pagina.nome
                    width: parent.width
                    text: pagina.descricao
                    textFormat: Text.PlainText
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.Wrap
                    color: Tema.texto
                    font { family: Tema.fonte; pixelSize: Tema.corpo }
                }
            }
            Column {
                id: extra
                anchors.horizontalCenter: parent.horizontalCenter
                width: Math.min(440, parent.width)
                spacing: 12
            }
        }
    }

    // A barra do app: sem título, só minimizar e fechar (`Adw.HeaderBar` do `assistente.blp`).
    BarraDeTitulo {
        id: barra
        objectName: "barraDoAssistente"
        anchors { top: parent.top; left: parent.left; right: parent.right }
        visible: !raiz.semAgente
        janela: raiz
        agente: raiz.agente
        titulo: ""
        comMaximizar: false
    }

    Item {
        id: fundo
        anchors { fill: parent; topMargin: raiz.topo }
        enabled: !raiz.modalAberto

        Item {
            id: carrossel
            objectName: "carrossel"
            anchors { top: parent.top; left: parent.left; right: parent.right; bottom: rodape.top }
            clip: true

            property real posicao: raiz.modelo.indice
            property real _de: 0
            property real _t: 0
            property int _para: 0
            readonly property real _w: Math.sqrt(500 / 0.5)
            // Resposta ao degrau do oscilador crítico: 1 - (1 + wt)e^(-wt).
            on_TChanged: posicao = _de + (_para - _de) * (1 - (1 + _w * _t) * Math.exp(-_w * _t))
            NumberAnimation { id: relogioDoCarrossel; target: carrossel; property: "_t"; from: 0; to: 0.5; duration: 500 }
            Connections {
                target: raiz.modelo
                function onIndiceChanged() {
                    relogioDoCarrossel.stop()
                    // `animar` já foi relido pelo modelo a esta troca (`animarMudou`).
                    if (!raiz.modelo.animar) { carrossel.posicao = raiz.modelo.indice; return }
                    carrossel._de = carrossel.posicao
                    carrossel._para = raiz.modelo.indice
                    relogioDoCarrossel.start()
                }
            }

            // Sem gesto: só os botões trocam de tela. A troca é animada só com as animações do Windows ligadas.
            // `Adw.Carousel.scroll_to(animate=True)`: mola de amortecimento crítico (massa 0,5, rigidez 500). A posição é em
            // telas (`posicao`); os pontos a seguem.
            Row {
                id: fileira
                x: -carrossel.posicao * carrossel.width

                Pagina {
                    nome: "boas_vindas"
                    imagem: raiz.modelo.imagens.logo
                    titulo: "Boas-vindas ao Cartridges"
                    descricao: "Reúna os seus jogos em uma única biblioteca, com capas, tempo de jogo e conquistas. Configure o essencial em poucos passos."
                    primeiro: botaoComecar

                    Column {
                        anchors.horizontalCenter: parent.horizontalCenter
                        spacing: 12
                        // A validação do backup leva segundos: um segundo clique restauraria duas vezes.
                        enabled: !raiz.modelo.preparando

                        BotaoDoModal {
                            id: botaoComecar
                            objectName: "botaoComecar"
                            anchors.horizontalCenter: parent.horizontalCenter
                            text: "Começar"
                            destaque: true
                            onClicked: raiz.modelo.avancar()
                        }
                        BotaoDoModal {
                            objectName: "botaoRestaurar"
                            anchors.horizontalCenter: parent.horizontalCenter
                            text: "Restaurar um backup"
                            onClicked: cargaDoBackup.active ? cargaDoBackup.item.open() : cargaDoBackup.active = true
                        }
                        Botao {
                            objectName: "botaoPularConfiguracao"
                            anchors.horizontalCenter: parent.horizontalCenter
                            estilo: "plano"
                            text: "Pular configuração"
                            onClicked: raiz.modelo.concluir()
                        }
                    }
                }

                Pagina {
                    nome: "jogos"
                    icone: "folder"
                    titulo: "Seus jogos"
                    descricao: "O Cartridges adiciona à biblioteca os jogos cujos atalhos estão em uma pasta. Escolha a pasta onde estão, ou onde ficarão, os atalhos dos seus jogos. Novos atalhos colocados nela aparecem na biblioteca sempre que o aplicativo é aberto."
                    primeiro: linhaDaPasta.botaoDaLinha

                    GrupoDeLinhas {
                        width: parent.width
                        LinhaDeAcao {
                            id: linhaDaPasta
                            objectName: "linhaDaPasta"
                            titulo: "Pasta"
                            subtitulo: raiz.modelo.subtituloDaPasta
                            rotulo: "Escolher"
                            onAcionada: cargaDaPasta.active ? cargaDaPasta.item.open() : cargaDaPasta.active = true
                        }
                    }
                }

                Pagina {
                    nome: "capas"
                    titulo: "Capas e logos"
                    descricao: "O SteamGridDB fornece capas e logos para os seus jogos. Para usá-lo, informe uma chave da API."
                    primeiro: linhaDaChaveSgdb

                    // A capa de exemplo com o placeholder por cima, que desliza e revela a capa; no lugar do ícone. O
                    // quadro de cada instante é o `quadro_das_capas` da `main`. Anima só com a tela à vista.
                    Item {
                        id: palco
                        objectName: "palcoDasCapas"
                        property real instante: raiz.modelo.instanteParado
                        readonly property var quadro: raiz.modelo.quadro(instante)
                        readonly property bool animando: animacao.running
                        anchors.horizontalCenter: parent.horizontalCenter
                        width: 120
                        height: 180

                        // `.capa-de-exemplo`: raio 6 nas duas imagens (máscara; `clip` só corta em retângulo).
                        Item {
                            id: mascaraDaCapa
                            anchors.fill: parent
                            visible: false
                            layer.enabled: true
                            Rectangle { anchors.fill: parent; radius: 6 }
                        }
                        Item {
                            anchors.fill: parent
                            layer.enabled: true
                            layer.effect: MultiEffect { maskEnabled: true; maskSource: mascaraDaCapa; maskThresholdMin: 0.5; maskSpreadAtMin: 1.0 }
                            Image {
                                objectName: "capaDeExemplo"
                                anchors.fill: parent
                                source: raiz.modelo.imagens.capa
                                sourceSize: Qt.size(240, 360)
                                opacity: palco.quadro[2]
                            }
                            Image {
                                objectName: "capaVazia"
                                x: palco.quadro[0]
                                width: parent.width
                                height: parent.height
                                source: raiz.modelo.imagens.vazia
                                sourceSize: Qt.size(240, 360)
                                opacity: palco.quadro[1]
                            }
                        }
                        NumberAnimation {
                            id: animacao
                            target: palco
                            property: "instante"
                            from: 0
                            to: raiz.modelo.ciclo
                            duration: raiz.modelo.ciclo
                            loops: Animation.Infinite
                            running: raiz.modelo.animar && raiz.paginaAtual === "capas" && raiz.visible
                            // Parada (fora da tela ou sem animações), a capa fica sozinha.
                            onRunningChanged: if (!running) palco.instante = raiz.modelo.instanteParado
                        }
                    }

                    GrupoDePreferencias {
                        objectName: "grupoDaChaveSgdb"
                        // A mesma frase das Preferências; texto nosso, com o único link.
                        descricao: 'É necessária uma chave da API para usar o SteamGridDB. <a href="https://www.steamgriddb.com/profile/preferences/api">Obtenha aqui</a>.'
                        descricaoRica: true
                        onLinkAcionado: endereco => raiz.modelo.abrirEndereco(endereco)

                        LinhaDeTexto {
                            id: linhaDaChaveSgdb
                            objectName: "linhaDaChaveSgdb"
                            titulo: "Chave da API"
                            // Lido uma vez: com a ligação, o espaço digitado sumiria antes da letra seguinte.
                            Component.onCompleted: text = raiz.modelo.chaveSgdb
                            onEditado: raiz.modelo.definirChaveSgdb(text)
                        }
                        LinhaDeAlternancia {
                            objectName: "linhaCapasAnimadas"
                            titulo: "Capas animadas"
                            aparece: raiz.modelo.chaveSgdb !== ""
                            checked: raiz.modelo.capasAnimadas
                            onAlternado: raiz.modelo.definirCapasAnimadas(checked)
                        }
                    }
                }

                Pagina {
                    nome: "conquistas"
                    compacta: true
                    titulo: "Conquistas"
                    descricao: "Entre com as contas das lojas para acompanhar as conquistas dos seus jogos."

                    // O cartão do aviso de conquista, o de verdade, com um exemplo; no lugar do ícone.
                    CartaoDoAviso {
                        anchors.horizontalCenter: parent.horizontalCenter
                        rotulo: raiz.modelo.cartao.rotulo
                        titulo: raiz.modelo.cartao.titulo
                        descricao: raiz.modelo.cartao.descricao
                        icone: raiz.modelo.cartao.icone
                        embutido: true
                    }
                    GrupoDasContas {
                        id: grupoDasContas
                        width: parent.width
                        contas: raiz.modelo.contas
                        comCabecalho: false
                    }
                    GrupoDePreferencias {
                        objectName: "grupoDaChaveDaSteam"
                        titulo: "Steam Web API"
                        descricao: 'Informe a chave da Steam Web API. <a href="https://steamcommunity.com/dev/apikey">Obtenha aqui</a>.'
                        descricaoRica: true
                        onLinkAcionado: endereco => raiz.modelo.abrirEndereco(endereco)

                        LinhaDeTexto {
                            objectName: "linhaDaChaveDaSteam"
                            titulo: "Chave da API"
                            Component.onCompleted: text = raiz.modelo.chaveSteam
                            onEditado: raiz.modelo.definirChaveSteam(text)
                        }
                    }
                }

                Pagina {
                    nome: "iluminacao"
                    icone: "display-brightness"
                    titulo: "Iluminação inteligente"
                    descricao: "O Cartridges pode mudar a cor dos seus dispositivos de iluminação compatíveis com a Tuya de acordo com o jogo em execução."
                    primeiro: botaoConfigurar

                    BotaoDoModal {
                        id: botaoConfigurar
                        objectName: "botaoConfigurar"
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: "Configurar"
                        onClicked: raiz.modelo.configurarIluminacao()
                    }
                }

                Pagina {
                    nome: "controle"
                    icone: "input-gaming"
                    titulo: "Controle"
                    descricao: "O Cartridges pode abrir o Big Picture automaticamente quando um controle é conectado."

                    GrupoDeLinhas {
                        width: parent.width
                        LinhaDeAlternancia {
                            objectName: "linhaBigPicture"
                            titulo: "Abrir o Big Picture ao conectar um controle"
                            subtitulo: "Abre o Big Picture ao iniciar o aplicativo com um controle conectado ou ao conectar um controle na biblioteca"
                            checked: raiz.modelo.bigPictureAoConectar
                            onAlternado: raiz.modelo.definir("big-picture-ao-conectar", checked)
                        }
                    }
                }

                Pagina {
                    nome: "monitores"
                    icone: "video-joined-displays"
                    titulo: "Outros monitores"
                    descricao: "Escolha o que o Cartridges faz com os demais monitores ao iniciar um jogo."

                    GrupoDeLinhas {
                        width: parent.width
                        LinhaDeAlternancia {
                            objectName: "linhaMover"
                            titulo: "Mover o aplicativo para outro monitor ao iniciar um jogo"
                            checked: raiz.modelo.moverJanela
                            onAlternado: raiz.modelo.definir("session-move-window", checked)
                        }
                        LinhaDeEscolha {
                            objectName: "linhaMonitor"
                            titulo: "Monitor"
                            enabled: raiz.modelo.moverJanela
                            model: raiz.modelo.monitores
                            currentIndex: raiz.modelo.monitorEscolhido
                            onEscolhido: indice => raiz.modelo.escolherMonitor(indice)
                        }
                        LinhaDeBotao {
                            objectName: "linhaIdentificar"
                            titulo: "Identificar monitores"
                            onAcionada: raiz.modelo.identificarMonitores()
                        }
                        LinhaDeAlternancia {
                            objectName: "linhaPapelDeParede"
                            titulo: "Trocar o papel de parede dos outros monitores"
                            checked: raiz.modelo.papelDeParede
                            onAlternado: raiz.modelo.definir("session-wallpaper", checked)
                        }
                    }
                }

                Pagina {
                    nome: "pronto"
                    icone: "object-select"
                    titulo: "Tudo pronto"
                    descricao: "Você pode alterar estas opções a qualquer momento em Preferências."
                    primeiro: botaoAbrirBiblioteca

                    BotaoDoModal {
                        id: botaoAbrirBiblioteca
                        objectName: "botaoAbrirBiblioteca"
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: "Abrir a biblioteca"
                        destaque: true
                        onClicked: raiz.modelo.concluir()
                    }
                }
            }
        }

        // O rodapé é conteúdo da janela (a moldura é a nativa): arrastar sobre os botões não move a janela.
        Column {
            id: rodape
            objectName: "rodape"
            anchors { left: parent.left; right: parent.right; bottom: parent.bottom; margins: 12 }
            spacing: 12

            // `Adw.CarouselIndicatorDots`: o ponto da tela à vista é maior (raio 4 contra 3) e a troca desliza com o carrossel.
            Row {
                objectName: "pontos"
                anchors.horizontalCenter: parent.horizontalCenter
                spacing: 7
                height: 8
                Repeater {
                    model: raiz.modelo.paginas.length
                    Item {
                        id: ponto
                        required property int index
                        readonly property real peso: Math.max(0, 1 - Math.abs(carrossel.posicao - index))
                        width: 6 + 2 * peso
                        height: 8
                        Rectangle {
                            anchors.centerIn: parent
                            width: parent.width
                            height: width
                            radius: width / 2
                            color: Tema.texto
                            opacity: 0.3 + 0.6 * ponto.peso
                        }
                    }
                }
            }
            Item {
                objectName: "botoesDoRodape"
                width: parent.width
                height: 36
                visible: raiz.modelo.rodapeVisivel

                Botao {
                    objectName: "botaoVoltar"
                    anchors.left: parent.left
                    text: "Voltar"
                    onClicked: raiz.modelo.voltar()
                }
                Row {
                    anchors.right: parent.right
                    spacing: 6
                    Botao {
                        objectName: "botaoPular"
                        text: "Pular"
                        onClicked: raiz.modelo.avancar()
                    }
                    Botao {
                        objectName: "botaoContinuar"
                        text: "Continuar"
                        estilo: "sugestao"
                        enabled: raiz.modelo.podeContinuar
                        onClicked: raiz.modelo.avancar()
                    }
                }
            }
        }
    }

    // Por cima do fundo: o aviso ("Preparando a restauração. Aguarde…" e os das contas), os modais e o diálogo.
    Avisos {
        anchors.fill: parent
        fila: raiz.modelo.avisos
    }
    ConfiguracaoDasFitas {
        id: fitas
        assistente: raiz.modelo.configuracaoDasFitas
    }
    JanelaDeLogin {
        id: loginEpic
        objectName: "janelaDeLoginEpic"
        login: raiz.modelo.contas.loginEpic
    }
    JanelaDeLogin {
        id: loginEa
        objectName: "janelaDeLoginEa"
        login: raiz.modelo.contas.loginEa
    }
    DialogoDeAviso {
        id: dialogo
        objectName: "dialogoDoAssistente"
        z: 10
    }

    // window.csd: o contorno de 1 px da janela sem moldura nativa.
    Rectangle {
        anchors.fill: parent
        z: 1000
        enabled: false
        visible: !raiz.semAgente
        radius: 8
        color: "transparent"
        border { width: 1; color: Tema.contorno }
    }
}
