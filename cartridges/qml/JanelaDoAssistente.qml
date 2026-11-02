import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Dialogs
import QtQuick.Window

// O assistente da primeira abertura (D86): janela própria com a moldura nativa (minimizar e fechar), antes da
// biblioteca, num motor próprio. As oito telas do `.blp` da `main` num carrossel sem gesto, os pontos e o rodapé
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

    title: "Cartridges"
    width: 640
    height: 640
    minimumWidth: 640
    maximumWidth: 640
    minimumHeight: 640
    maximumHeight: 640
    color: Tema.fundo
    flags: Qt.Window | Qt.CustomizeWindowHint | Qt.WindowTitleHint | Qt.WindowMinimizeButtonHint | Qt.WindowCloseButtonHint
    visible: true

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
    Component.onCompleted: Qt.callLater(raiz.recuperarFoco)

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

    // Uma tela, como o `Adw.StatusPage`: o ícone (glifo ou imagem), o título, a descrição e o conteúdo, centralizados e
    // com rolagem quando não cabem. Só a tela à vista fica habilitada: o Tab não alcança as outras.
    component Pagina: Flickable {
        id: pagina
        property string nome
        property string glifo
        property string imagem
        property string titulo
        property string descricao
        // O controle que recebe o foco quando a tela aparece.
        property Item primeiro: null
        default property alias conteudo: extra.data

        objectName: "pagina_" + nome
        visible: raiz.modelo.paginas.indexOf(nome) >= 0
        enabled: raiz.paginaAtual === nome
        width: carrossel.width
        height: carrossel.height
        contentWidth: width
        contentHeight: Math.max(height, coluna.implicitHeight + 48)
        interactive: contentHeight > height
        boundsBehavior: Flickable.StopAtBounds
        clip: true
        ScrollBar.vertical: BarraDeRolagem {}

        Column {
            id: coluna
            x: 24
            y: Math.max(24, (pagina.height - implicitHeight) / 2)
            width: pagina.width - 48
            spacing: 12

            Image {
                objectName: "imagem_" + pagina.nome
                anchors.horizontalCenter: parent.horizontalCenter
                visible: pagina.imagem !== ""
                source: pagina.imagem
                sourceSize: Qt.size(128, 128)
                width: 128
                height: 128
            }
            Text {
                objectName: "icone_" + pagina.nome
                anchors.horizontalCenter: parent.horizontalCenter
                visible: pagina.glifo !== ""
                text: pagina.glifo
                textFormat: Text.PlainText
                color: Tema.textoSecundario
                font { family: Tema.fonteDeIcones; pixelSize: 96 }
            }
            Text {
                objectName: "titulo_" + pagina.nome
                width: parent.width
                text: pagina.titulo
                textFormat: Text.PlainText
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap
                color: Tema.texto
                font { family: Tema.fonte; pixelSize: 26; weight: Font.Bold }
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
                font { family: Tema.fonte; pixelSize: 15 }
            }
            Item { width: 1; height: 12 }
            Column {
                id: extra
                anchors.horizontalCenter: parent.horizontalCenter
                width: Math.min(440, parent.width)
                spacing: 12
            }
        }
    }

    // O botão sem fundo ("flat").
    component BotaoPlano: Button {
        id: plano
        focusPolicy: Qt.StrongFocus
        implicitHeight: 36
        leftPadding: 20
        rightPadding: 20
        Keys.onReturnPressed: click()
        Keys.onEnterPressed: click()
        contentItem: Text {
            text: plano.text
            textFormat: Text.PlainText
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            opacity: plano.enabled ? 1 : 0.5
            color: Tema.texto
            font { family: Tema.fonte; pixelSize: 14 }
        }
        background: Rectangle {
            radius: height / 2
            color: plano.down ? Tema.pressionado : plano.hovered ? Tema.botaoSobre : "transparent"
            border { width: plano.visualFocus ? 2 : 0; color: Tema.texto }
        }
    }

    Item {
        id: fundo
        anchors.fill: parent
        enabled: !raiz.modalAberto

        Item {
            id: carrossel
            objectName: "carrossel"
            anchors { top: parent.top; left: parent.left; right: parent.right; bottom: rodape.top }
            clip: true

            // Sem gesto: só os botões trocam de tela. A troca é animada só com as animações do Windows ligadas.
            Row {
                id: fileira
                x: -raiz.modelo.indice * carrossel.width
                Behavior on x {
                    enabled: raiz.modelo.animar
                    NumberAnimation { duration: Tema.duracaoMedia; easing.type: Easing.OutCubic }
                }

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
                        BotaoPlano {
                            objectName: "botaoPularConfiguracao"
                            anchors.horizontalCenter: parent.horizontalCenter
                            text: "Pular configuração"
                            onClicked: raiz.modelo.concluir()
                        }
                    }
                }

                Pagina {
                    nome: "jogos"
                    glifo: ""  // Folder ("folder-symbolic")
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
                    glifo: ""  // Brightness ("display-brightness-symbolic")
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
                    glifo: ""  // Game ("input-gaming-symbolic")
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
                    glifo: ""  // TVMonitor ("video-joined-displays-symbolic")
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
                    glifo: ""  // CheckMark ("object-select-symbolic")
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

            Row {
                objectName: "pontos"
                anchors.horizontalCenter: parent.horizontalCenter
                spacing: 8
                Repeater {
                    model: raiz.modelo.paginas.length
                    Rectangle {
                        required property int index
                        width: 7
                        height: 7
                        radius: 3.5
                        color: Tema.texto
                        opacity: index === raiz.modelo.indice ? 0.9 : 0.3
                    }
                }
            }
            Item {
                objectName: "botoesDoRodape"
                width: parent.width
                height: 36
                visible: raiz.modelo.rodapeVisivel

                BotaoPlano {
                    objectName: "botaoVoltar"
                    anchors.left: parent.left
                    text: "Voltar"
                    onClicked: raiz.modelo.voltar()
                }
                Row {
                    anchors.right: parent.right
                    spacing: 6
                    BotaoPlano {
                        objectName: "botaoPular"
                        text: "Pular"
                        onClicked: raiz.modelo.avancar()
                    }
                    BotaoDoModal {
                        objectName: "botaoContinuar"
                        text: "Continuar"
                        destaque: true
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
}
