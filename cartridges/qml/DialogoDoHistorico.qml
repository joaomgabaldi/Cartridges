import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import QtQuick.Window

// O histórico de sessões de um jogo (`Adw.Dialog` de 1040 de largura): o logo (ou o nome) e o resumo no topo, e lado a lado
// a tabela das sessões e o painel do gráfico. Só desenha: o que ele mostra e faz é o `historico`
// (cartridges/modelos/historico.py). Modal para o mouse, o teclado e o controle; o foco volta a quem o abriu. A faixa de
// cima não mostra título (`show_title=False`): o logo (ou o nome) é a manchete, e o título só vive no nome acessível.
// A raiz é só um `Item`: a confirmação de exclusão cobre a janela e não pode morar dentro do cartão.
Item {
    id: raiz

    MolduraDoDialogo {
        id: dialogo
        objectName: "dialogoDoHistorico"

        // A sessão cuja exclusão a confirmação pergunta.
        property var excluindo: ({ fim: 0, segundos: 0, duracao: "", titulo: "" })
        // O que sobra da altura do cartão para a tabela: o que o cartão pode ter, menos o cabeçalho e tudo o que não é a
        // tabela (a manchete, o resumo, os respiros). Sem ler a altura do próprio cartão (laço).
        readonly property real alturaMaximaDoCartao: emFolha ? height - 30 : height - 2 * margemV
        readonly property real alturaLivreDaTabela: alturaMaximaDoCartao - cabecalho.implicitHeight
            - (manchete.implicitHeight + resumo.implicitHeight + 5 * 12)
        // 34 do seletor, 12, o total, 12 e o gráfico no piso: o painel nunca fica mais baixo que isto.
        readonly property real pisoDoPainel: 34 + 12 + totalDoPeriodo.implicitHeight + 12 + 240

        function contem(pai, item) {
            for (var p = item; p; p = p.parent) // `parent`: o `parentItem` do C++ não existe no QML
                if (p === pai) return true
            return false
        }
        // Depois de uma exclusão ou de "Mostrar mais" a linha ou o botão que tinha o foco pode ter sumido.
        function garantirFoco() {
            var f = Window.window ? Window.window.activeFocusItem : null
            if (visible && !(f && f.visible && dentro(f))) // o botão escondido ainda é filho do diálogo
                cabecalho.botaoFechar.forceActiveFocus(Qt.TabFocusReason)
        }
        // O item com o foco fica à vista, na tabela e na rolagem do diálogo.
        function trazer(rolagem, item) {
            var topo = item.mapToItem(rolagem.contentItem, 0, 0).y
            var base = topo + item.height
            if (topo < rolagem.contentY) rolagem.contentY = Math.max(0, topo - 8)
            else if (base > rolagem.contentY + rolagem.height) rolagem.contentY = base - rolagem.height + 8
        }
        function pedirExclusao(sessao) {
            excluindo = sessao
            confirmacao.abrir()
        }
        // As setas andam entre as linhas, como na `ListBox` da `main`.
        function irParaLinha(indice) {
            var linha = repetidor.itemAt(indice)
            if (linha) linha.alvo.forceActiveFocus(Qt.TabFocusReason)
        }
        // Home, End, PageUp e PageDown entre as linhas, como o `GtkListBox`.
        function irParaLinhaPorTecla(indice, tecla) {
            var passo = Math.max(1, Math.floor(rolagem.height / Math.max(1, repetidor.itemAt(indice).height)))
            var destino = tecla === Qt.Key_Home ? 0 : tecla === Qt.Key_End ? repetidor.count - 1
                : tecla === Qt.Key_PageUp ? indice - passo : indice + passo
            irParaLinha(Math.max(0, Math.min(repetidor.count - 1, destino)))
        }

        aberto: historico.aberto
        largura: 1040
        focoInicial: cabecalho.botaoFechar
        nomeAcessivel: "Histórico de sessões"
        onFecharPedido: historico.fechar()
        onAbertoChanged: if (aberto) {
            rolagem.contentY = 0
            tabela.contentY = 0
        }

        Connections {
            target: dialogo.Window.window
            function onActiveFocusItemChanged() {
                var foco = dialogo.Window.window.activeFocusItem
                if (!dialogo.visible || !foco || !dialogo.dentro(foco)) return
                if (dialogo.contem(rolagem.contentItem, foco)) dialogo.trazer(rolagem, foco)
                if (dialogo.contem(tabela.contentItem, foco)) dialogo.trazer(tabela, foco)
            }
        }

        // O seletor de período: o `Adw.ToggleGroup`, uma trilha só a 10% com cada opção dentro (padding 3, raio 9 e 6).
        component BotaoDoPeriodo: Button {
            id: botao
            focusPolicy: Qt.StrongFocus
            hoverEnabled: true
            implicitHeight: 28
            implicitWidth: Math.max(contentItem.implicitWidth + 16, 24)
            leftPadding: 8
            rightPadding: 8
            topPadding: 0
            bottomPadding: 0
            Accessible.role: Accessible.RadioButton
            Accessible.checked: checked
            Keys.onReturnPressed: click()
            Keys.onEnterPressed: click()
            contentItem: Text {
                text: botao.text
                textFormat: Text.PlainText
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
                color: Tema.texto
                font { family: Tema.fonte; pixelSize: Tema.corpo; weight: Tema.pesoForte }
            }
            background: Rectangle {
                radius: 6
                // `--active-toggle-bg-color`: branco no claro, branco a 20% no escuro.
                color: botao.checked ? (Tema.escuro ? Qt.rgba(1, 1, 1, 0.2) : "#ffffff")
                    : botao.down ? Tema.planoPressionado : botao.hovered ? Tema.planoSobre : "transparent"
                Behavior on color { ColorAnimation { duration: Tema.duracaoCurta; easing { type: Easing.Bezier; bezierCurve: Tema.curva } } }
                Sombra { visible: botao.checked; camadas: Tema.sombraAviso; raio: 6 }
                AnelDeFoco { ativo: botao.visualFocus; raio: 6; afastamento: 0 }
            }
        }

        CabecalhoDoDialogo {
            id: cabecalho
            titulo: ""
            sombra: rolagem.contentY > 0
            // Com a confirmação ou as Preferências na frente, o Tab não alcança o X que ficou atrás.
            enabled: !confirmacao.aberto && !preferencias.aberto
            onFechar: historico.fechar()
        }

        // Com a confirmação ou as Preferências na frente, nada daqui recebe o mouse nem o Tab.
        Flickable {
            id: rolagem
            objectName: "rolagemDoHistorico"
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.preferredHeight: contentHeight
            Layout.minimumHeight: 0
            enabled: !confirmacao.aberto && !preferencias.aberto
            contentWidth: width
            contentHeight: conteudo.implicitHeight
            boundsBehavior: Flickable.StopAtBounds
            clip: true
            ScrollBar.vertical: BarraDeRolagem {}

            ColumnLayout {
                id: conteudo
                width: rolagem.width
                spacing: 12

                // O logo (até 992×120) ou o nome, nunca os dois.
                CabecalhoDoJogo {
                    id: manchete
                    Layout.fillWidth: true
                    Layout.leftMargin: 24
                    Layout.rightMargin: 24
                    logo: historico.logo
                    larguraDoLogo: historico.larguraDoLogo
                    nome: historico.nome
                    nomeDoLogo: "logoDoHistorico"
                    nomeDoTexto: "nomeDoHistorico"
                }

                Text {
                    id: resumo
                    objectName: "resumoDoHistorico"
                    Layout.fillWidth: true
                    Layout.leftMargin: 24
                    Layout.rightMargin: 24
                    text: historico.resumo
                    textFormat: Text.PlainText
                    wrapMode: Text.Wrap
                    horizontalAlignment: Text.AlignHCenter
                    color: Tema.textoSecundario
                    font { family: Tema.fonte; pixelSize: Tema.corpo }
                }

                // A tabela e o painel do gráfico: o painel tem sempre a altura da faixa, e a faixa segue a da tabela.
                RowLayout {
                    objectName: "colunasDoHistorico"
                    visible: !historico.vazio
                    Layout.fillWidth: true
                    Layout.leftMargin: 24
                    Layout.rightMargin: 24
                    Layout.topMargin: 12
                    spacing: 24

                    // A altura é a das linhas, até 440 e até o que a janela deixa, mas nunca abaixo do piso do painel: o
                    // gráfico fica à vista (`max_content_height` da `main` é só um teto). Só quando nem o piso cabe, o
                    // cartão inteiro rola.
                    Flickable {
                        id: tabela
                        objectName: "tabelaDeSessoes"
                        Layout.preferredWidth: 440
                        Layout.maximumWidth: 440
                        Layout.preferredHeight: Math.min(contentHeight, 440, Math.max(dialogo.pisoDoPainel, dialogo.alturaLivreDaTabela))
                        Layout.alignment: Qt.AlignTop
                        contentWidth: width
                        contentHeight: linhas.implicitHeight
                        boundsBehavior: Flickable.StopAtBounds
                        clip: true
                        ScrollBar.vertical: BarraDeRolagem {}

                        Column {
                            id: linhas
                            width: tabela.width
                            spacing: 6

                            GrupoDeLinhas {
                                width: parent.width
                                Repeater {
                                    id: repetidor
                                    model: historico.sessoes
                                    delegate: LinhaDoGrupo {
                                        id: linha
                                        objectName: "linhaDaSessao"
                                        required property var modelData
                                        required property int index
                                        property alias alvo: alvoDaLinha
                                        titulo: modelData.titulo
                                        subtitulo: modelData.subtitulo
                                        reservaADireita: lixeira.width
                                        // Cada linha recebe o foco do teclado antes da lixeira (`ListBoxRow` da `main`).
                                        Button {
                                            id: alvoDaLinha
                                            objectName: "alvoDaLinhaDaSessao"
                                            anchors.fill: parent
                                            focusPolicy: Qt.StrongFocus  // um `Control`: o anel só aparece com o teclado (`visualFocus`)
                                            contentItem: Item {}
                                            background: Item {}
                                            Binding { target: linha; property: "foco"; value: alvoDaLinha.visualFocus }
                                            Accessible.role: Accessible.ListItem
                                            Accessible.name: linha.titulo + ". " + linha.subtitulo
                                            Keys.onUpPressed: dialogo.irParaLinha(linha.index - 1)
                                            Keys.onDownPressed: dialogo.irParaLinha(linha.index + 1)
                                            Keys.onPressed: event => {
                                                if ([Qt.Key_Home, Qt.Key_End, Qt.Key_PageUp, Qt.Key_PageDown].indexOf(event.key) < 0) return
                                                dialogo.irParaLinhaPorTecla(linha.index, event.key)
                                                event.accepted = true
                                            }
                                        }
                                        Botao {
                                            id: lixeira
                                            objectName: "botaoExcluirSessao"
                                            anchors { right: parent.right; rightMargin: 14; verticalCenter: parent.verticalCenter }
                                            estilo: "plano"
                                            icone: "user-trash"
                                            dica: "Excluir esta sessão"
                                            onClicked: dialogo.pedirExclusao(linha.modelData)
                                            Keys.onUpPressed: dialogo.irParaLinha(linha.index - 1)
                                            Keys.onDownPressed: dialogo.irParaLinha(linha.index + 1)
                                            Keys.onPressed: event => {
                                                if ([Qt.Key_Home, Qt.Key_End, Qt.Key_PageUp, Qt.Key_PageDown].indexOf(event.key) < 0) return
                                                dialogo.irParaLinhaPorTecla(linha.index, event.key)
                                                event.accepted = true
                                            }
                                        }
                                    }
                                }
                            }
                            Botao {
                                id: botaoMais
                                objectName: "botaoMostrarMais"
                                visible: historico.haMais
                                anchors.horizontalCenter: parent.horizontalCenter
                                estilo: "plano"
                                text: "Mostrar mais sessões"
                                onClicked: {
                                    historico.mostrarMais()
                                    Qt.callLater(dialogo.garantirFoco)
                                }
                            }
                        }
                    }

                    // O seletor de período fica em cima, onde o olho chega antes do gráfico: é ele que diz o que o
                    // gráfico mostra.
                    ColumnLayout {
                        id: painel
                        objectName: "painelDoGrafico"
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        spacing: 12

                        Rectangle {
                            Layout.alignment: Qt.AlignHCenter
                            implicitWidth: periodos.implicitWidth + 6
                            implicitHeight: 34
                            radius: 9
                            color: Tema.botao
                            Row {
                                id: periodos
                                anchors.centerIn: parent
                                BotaoDoPeriodo {
                                    objectName: "botaoSemana"
                                    text: "Semana"
                                    checked: historico.periodo === "week"
                                    onClicked: historico.definirPeriodo("week")
                                }
                                BotaoDoPeriodo {
                                    objectName: "botaoMes"
                                    text: "Mês"
                                    checked: historico.periodo === "month"
                                    onClicked: historico.definirPeriodo("month")
                                }
                                BotaoDoPeriodo {
                                    objectName: "botaoTodoOPeriodo"
                                    text: "Todo o período"
                                    checked: historico.periodo === "all"
                                    onClicked: historico.definirPeriodo("all")
                                }
                            }
                        }
                        Text {
                            id: totalDoPeriodo
                            objectName: "totalDoPeriodo"
                            Layout.alignment: Qt.AlignHCenter
                            text: historico.totalDoPeriodo
                            textFormat: Text.PlainText
                            color: Tema.textoSecundario
                            font { family: Tema.fonte; pixelSize: Tema.corpo }
                        }
                        GraficoDoHistorico {
                            Layout.fillWidth: true
                            Layout.fillHeight: true
                            Layout.minimumWidth: 320
                            Layout.minimumHeight: 240
                            Layout.preferredHeight: 240
                        }
                    }
                }

                // A margem de baixo de 24 é da caixa inteira (12 do espaçamento e estes 12), mesmo sem as colunas.
                Item { implicitHeight: 12 }
            }
        }
    }

    // Por cima do histórico: o texto é o da `main`.
    DialogoDeConfirmacao {
        id: confirmacao
        objectName: "dialogoExcluirSessao"
        titulo: "Excluir esta sessão?"
        corpo: "Tem certeza que deseja excluir a sessão de %1, em %2? O tempo será descontado do total do jogo. Esta ação é irreversível."
            .arg(dialogo.excluindo.duracao).arg(dialogo.excluindo.titulo)
        rotuloConfirmar: "Excluir"
        rotuloCancelar: "Cancelar"
        destrutivo: true
        onConfirmado: {
            historico.excluir(dialogo.excluindo.fim, dialogo.excluindo.segundos)
            Qt.callLater(dialogo.garantirFoco)
        }
    }
}
