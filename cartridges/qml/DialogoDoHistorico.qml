import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import QtQuick.Window

// O histórico de sessões de um jogo: o logo (ou o nome) e o resumo no topo, e lado a lado a tabela das sessões e o
// painel do gráfico. Só desenha: o que ele mostra e faz é o `historico` (cartridges/modelos/historico.py).
// Modal para o mouse, o teclado e o controle, como o de edição; o foco volta a quem o abriu. Sem título visível: o logo
// (ou o nome) é a manchete, e o título só vive no nome acessível.
Rectangle {
    id: dialogo
    objectName: "dialogoDoHistorico"

    Accessible.role: Accessible.Dialog
    Accessible.name: "Histórico de sessões"
    // A sessão cuja exclusão a confirmação pergunta.
    property var excluindo: ({ fim: 0, segundos: 0, duracao: "", titulo: "" })
    // Quem tinha o foco ao abrir.
    property Item retorno: null

    function contem(pai, item) {
        for (var p = item; p; p = p.parent) // `parent`: o `parentItem` do C++ não existe no QML
            if (p === pai) return true
        return false
    }
    function dentro(item) { return contem(dialogo, item) }
    // Depois de uma exclusão ou de "Mostrar mais" a linha ou o botão que tinha o foco pode ter sumido.
    function garantirFoco() {
        var f = Window.window ? Window.window.activeFocusItem : null
        if (visible && !(f && f.visible && dentro(f))) // o botão escondido ainda é filho do diálogo
            botaoFechar.forceActiveFocus(Qt.TabFocusReason)
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

    anchors.fill: parent
    visible: historico.aberto
    color: "#80000000"
    Keys.onEscapePressed: historico.fechar()
    // Modal para o teclado e o controle: nenhuma tecla chega à página de trás.
    Keys.onPressed: event => event.accepted = true

    onVisibleChanged: {
        if (visible) {
            retorno = Window.window ? Window.window.activeFocusItem : null
            rolagem.contentY = 0
            tabela.contentY = 0
            botaoFechar.forceActiveFocus(Qt.TabFocusReason)
        } else {
            // Depois da reação das outras bindings ao `aberto` (a página de trás volta a ficar habilitada).
            Qt.callLater(devolverAoRetorno)
        }
    }
    function devolverAoRetorno() {
        if (visible) return
        if (retorno && retorno.visible && retorno.enabled) retorno.forceActiveFocus(Qt.TabFocusReason)
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

    MouseArea { anchors.fill: parent } // o que está embaixo não recebe cliques

    component BotaoDoPeriodo: Button {
        id: botao
        focusPolicy: Qt.StrongFocus
        implicitHeight: 34
        leftPadding: 16
        rightPadding: 16
        Accessible.role: Accessible.RadioButton
        Accessible.checked: checked
        contentItem: Text {
            text: botao.text
            textFormat: Text.PlainText
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            color: botao.checked ? "white" : Tema.texto
            font { family: Tema.fonte; pixelSize: 14 }
        }
        background: Rectangle {
            radius: 6
            color: botao.checked ? Tema.destaque : botao.down ? Tema.pressionado : botao.hovered ? Tema.botaoSobre : Tema.superficie
            border { width: botao.visualFocus ? 2 : 1; color: botao.visualFocus ? Tema.texto : Tema.borda }
        }
    }

    component BotaoDeIcone: Button {
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

    Rectangle {
        id: cartao
        objectName: "cartaoDoHistorico"
        anchors.centerIn: parent
        width: Math.min(1040, parent.width - 48)
        height: Math.min(parent.height - 48, conteudo.implicitHeight)
        radius: 8
        color: Tema.fundo
        border.color: Tema.botaoSobre
        clip: true
        // Com a confirmação ou as Preferências na frente, nada daqui recebe o mouse nem o Tab.
        enabled: !confirmacao.visible && !preferencias.aberto

        Flickable {
            id: rolagem
            anchors.fill: parent
            contentWidth: width
            contentHeight: conteudo.implicitHeight
            boundsBehavior: Flickable.StopAtBounds
            clip: true
            ScrollBar.vertical: BarraDeRolagem {}

            ColumnLayout {
                id: conteudo
                width: rolagem.width
                spacing: 12

                // A faixa de cima: só o botão de fechar, à direita.
                Item {
                    Layout.fillWidth: true
                    implicitHeight: 40
                    BotaoDeIcone {
                        id: botaoFechar
                        objectName: "botaoFecharHistorico"
                        anchors { right: parent.right; rightMargin: 8; verticalCenter: parent.verticalCenter }
                        glifo: ""  // fechar
                        dica: "Fechar"
                        onClicked: historico.fechar()
                    }
                }

                // O logo (até 992×120) ou o nome, nunca os dois.
                CabecalhoDoJogo {
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
                    objectName: "resumoDoHistorico"
                    Layout.fillWidth: true
                    Layout.leftMargin: 24
                    Layout.rightMargin: 24
                    text: historico.resumo
                    textFormat: Text.PlainText
                    wrapMode: Text.Wrap
                    horizontalAlignment: Text.AlignHCenter
                    color: Tema.textoSecundario
                    font { family: Tema.fonte; pixelSize: 14 }
                }

                // A tabela e o painel do gráfico: o painel tem sempre a altura da faixa, e a faixa segue a da tabela.
                RowLayout {
                    objectName: "colunasDoHistorico"
                    visible: !historico.vazio
                    Layout.fillWidth: true
                    Layout.leftMargin: 24
                    Layout.rightMargin: 24
                    Layout.bottomMargin: 24
                    Layout.topMargin: 12
                    spacing: 24

                    // Rola a partir de 440 de altura em vez de esticar a caixa para fora da janela.
                    Flickable {
                        id: tabela
                        objectName: "tabelaDeSessoes"
                        Layout.preferredWidth: 440
                        Layout.maximumWidth: 440
                        Layout.preferredHeight: Math.min(contentHeight, 440)
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

                            Rectangle {
                                width: parent.width
                                height: lista.implicitHeight
                                radius: 12
                                color: Tema.superficie
                                border { width: 1; color: Tema.borda }
                                clip: true
                                Column {
                                    id: lista
                                    width: parent.width
                                    Repeater {
                                        model: historico.sessoes
                                        delegate: Item {
                                            id: linha
                                            objectName: "linhaDaSessao"
                                            required property var modelData
                                            required property int index
                                            width: lista.width
                                            height: 56
                                            Rectangle { width: parent.width; height: 1; color: Tema.borda; visible: linha.index > 0 }
                                            Column {
                                                anchors { left: parent.left; leftMargin: 16; right: lixeira.left; rightMargin: 8; verticalCenter: parent.verticalCenter }
                                                Text {
                                                    objectName: "tituloDaSessao"
                                                    width: parent.width
                                                    text: linha.modelData.titulo
                                                    textFormat: Text.PlainText
                                                    elide: Text.ElideRight
                                                    color: Tema.texto
                                                    font { family: Tema.fonte; pixelSize: 15 }
                                                }
                                                Text {
                                                    objectName: "subtituloDaSessao"
                                                    width: parent.width
                                                    text: linha.modelData.subtitulo
                                                    textFormat: Text.PlainText
                                                    elide: Text.ElideRight
                                                    color: Tema.textoSecundario
                                                    font { family: Tema.fonte; pixelSize: 12 }
                                                }
                                            }
                                            BotaoDeIcone {
                                                id: lixeira
                                                objectName: "botaoExcluirSessao"
                                                anchors { right: parent.right; rightMargin: 12; verticalCenter: parent.verticalCenter }
                                                glifo: ""  // lixeira
                                                dica: "Excluir esta sessão"
                                                onClicked: dialogo.pedirExclusao(linha.modelData)
                                            }
                                        }
                                    }
                                }
                            }
                            Button {
                                id: botaoMais
                                objectName: "botaoMostrarMais"
                                visible: historico.haMais
                                anchors.horizontalCenter: parent.horizontalCenter
                                focusPolicy: Qt.StrongFocus
                                text: "Mostrar mais sessões"
                                implicitHeight: 34
                                leftPadding: 16
                                rightPadding: 16
                                onClicked: {
                                    historico.mostrarMais()
                                    Qt.callLater(dialogo.garantirFoco)
                                }
                                contentItem: Text {
                                    text: botaoMais.text
                                    textFormat: Text.PlainText
                                    horizontalAlignment: Text.AlignHCenter
                                    verticalAlignment: Text.AlignVCenter
                                    color: Tema.texto
                                    font { family: Tema.fonte; pixelSize: 14 }
                                }
                                background: Rectangle {
                                    radius: 6
                                    color: botaoMais.down ? Tema.pressionado : botaoMais.hovered ? Tema.botaoSobre : "transparent"
                                    border { width: botaoMais.visualFocus ? 2 : 0; color: Tema.destaque }
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

                        Row {
                            Layout.alignment: Qt.AlignHCenter
                            spacing: 4
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
                        Text {
                            objectName: "totalDoPeriodo"
                            Layout.alignment: Qt.AlignHCenter
                            text: historico.totalDoPeriodo
                            textFormat: Text.PlainText
                            color: Tema.textoSecundario
                            font { family: Tema.fonte; pixelSize: 14 }
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
