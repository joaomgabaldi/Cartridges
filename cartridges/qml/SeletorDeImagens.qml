import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Window

// O seletor de capa ou de logo do SteamGridDB: um campo de busca e uma grade de miniaturas.
// Só desenha: a busca, as miniaturas e o download são do `seletor` (cartridges/modelos/seletores.py).
// Modal para o mouse, o teclado e o controle (abre por cima do diálogo de edição, que fica desabilitado);
// o foco volta ao botão que o abriu.
Rectangle {
    id: seletorDeImagens

    // O SeletorDoSgdb ou o SeletorDeLogo.
    property QtObject seletor
    property string titulo
    // O botão do canto: "Animadas" (alterna) na capa, "Usar o título" (age) no logo.
    property string rotuloDoAtalho
    property string dicaDoAtalho
    property bool atalhoAlterna: false
    // O logo é um letreiro horizontal: células largas, uma ou duas por linha.
    property bool horizontal: false

    readonly property int larguraDaCelula: horizontal ? 300 : 140
    readonly property int alturaDaCelula: horizontal ? 110 : 210
    readonly property int colunas: Math.max(horizontal ? 1 : 2,
        Math.min(horizontal ? 2 : 4, Math.floor(grade.width / (larguraDaCelula + 12))))

    signal atalhoClicado()

    // Quem tinha o foco ao abrir: volta a tê-lo ao fechar.
    property Item retorno: null
    signal retornoPerdido()

    anchors.fill: parent
    z: 5
    visible: seletor.aberto
    color: "#80000000"
    Keys.onEscapePressed: seletor.fechar()
    // Modal para o teclado e o controle: nenhuma tecla chega ao diálogo de trás.
    Keys.onPressed: event => event.accepted = true

    onVisibleChanged: {
        if (visible) {
            retorno = Window.window ? Window.window.activeFocusItem : null
            campoDeBusca.forceActiveFocus(Qt.TabFocusReason)
        } else {
            // Depois de o diálogo de trás voltar a ficar habilitado.
            Qt.callLater(devolverAoRetorno)
        }
    }
    function devolverAoRetorno() {
        if (visible) return
        if (retorno && retorno.visible && retorno.enabled) retorno.forceActiveFocus(Qt.TabFocusReason)
        else seletorDeImagens.retornoPerdido()
    }

    // A seta numa célula leva o foco à vizinha; para cima da primeira linha, ao campo de busca.
    function moverFoco(indice) {
        if (indice < 0) { campoDeBusca.forceActiveFocus(Qt.BacktabFocusReason); return }
        if (indice >= grade.count) return
        grade.positionViewAtIndex(indice, GridView.Contain)
        var item = grade.itemAtIndex(indice)
        if (item) item.forceActiveFocus(Qt.TabFocusReason)
    }

    MouseArea { anchors.fill: parent } // o que está embaixo não recebe cliques

    Rectangle {
        anchors.centerIn: parent
        width: Math.min(720, parent.width - 48)
        height: Math.min(620, parent.height - 48)
        radius: 8
        color: Tema.fundo
        border.color: Tema.botaoSobre
        clip: true

        component BotaoDoCabecalho: Button {
            id: botao
            property color cor: Tema.superficie
            property color corDoTexto: Tema.texto
            property string dica
            ToolTip.visible: hovered && dica !== ""
            ToolTip.text: dica
            ToolTip.delay: 600
            focusPolicy: Qt.StrongFocus
            implicitHeight: 34
            leftPadding: 18
            rightPadding: 18
            Keys.onReturnPressed: click()
            Keys.onEnterPressed: click()
            contentItem: Text {
                text: botao.text
                textFormat: Text.PlainText
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
                color: botao.corDoTexto
                font { family: Tema.fonte; pixelSize: 14 }
            }
            background: Rectangle {
                radius: 6
                color: botao.cor
                opacity: botao.down ? 0.75 : botao.hovered ? 0.9 : 1
                border { width: botao.visualFocus ? 2 : 1; color: botao.visualFocus ? Tema.texto : Tema.borda }
            }
        }

        // O cabeçalho vem primeiro: a ordem do Tab é "Fechar", o atalho, o campo e as miniaturas.
        Rectangle {
            id: cabecalho
            anchors { left: parent.left; right: parent.right; top: parent.top }
            height: 56
            color: Tema.fundo

            BotaoDoCabecalho {
                id: botaoFechar
                objectName: seletorDeImagens.objectName + "Fechar"
                anchors { left: parent.left; leftMargin: 12; verticalCenter: parent.verticalCenter }
                text: "Fechar"
                onClicked: seletorDeImagens.seletor.fechar()
            }
            Text {
                objectName: seletorDeImagens.objectName + "Titulo"
                anchors { left: botaoFechar.right; right: botaoDoAtalho.left; leftMargin: 8; rightMargin: 8; verticalCenter: parent.verticalCenter }
                text: seletorDeImagens.titulo
                textFormat: Text.PlainText
                horizontalAlignment: Text.AlignHCenter
                elide: Text.ElideRight
                color: Tema.texto
                font { family: Tema.fonte; pixelSize: 16; weight: Font.DemiBold }
                Accessible.role: Accessible.Heading
                Accessible.name: text
            }
            BotaoDoCabecalho {
                id: botaoDoAtalho
                objectName: seletorDeImagens.objectName + "Atalho"
                anchors { right: parent.right; rightMargin: 12; verticalCenter: parent.verticalCenter }
                text: seletorDeImagens.rotuloDoAtalho
                checkable: seletorDeImagens.atalhoAlterna
                checked: seletorDeImagens.atalhoAlterna && seletorDeImagens.seletor.animadas
                enabled: !seletorDeImagens.seletor.baixando
                cor: checked ? Tema.destaque : Tema.superficie
                corDoTexto: checked ? "white" : Tema.texto
                dica: seletorDeImagens.dicaDoAtalho
                Accessible.name: dica
                onClicked: seletorDeImagens.atalhoClicado()
            }
        }

        Rectangle {
            id: campo
            anchors { left: parent.left; right: parent.right; top: cabecalho.bottom; margins: 12; topMargin: 0 }
            height: 40
            radius: 8
            color: Tema.superficie
            border { width: campoDeBusca.activeFocus ? 2 : 1; color: campoDeBusca.activeFocus ? Tema.destaque : Tema.borda }
            enabled: !seletorDeImagens.seletor.baixando
            opacity: enabled ? 1 : 0.5

            TextField {
                id: campoDeBusca
                objectName: seletorDeImagens.objectName + "Campo"
                anchors { fill: parent; leftMargin: 12; rightMargin: 12 }
                selectByMouse: true
                placeholderText: "Buscar jogo…"
                placeholderTextColor: Tema.textoSecundario
                color: Tema.texto
                selectionColor: Tema.destaque
                selectedTextColor: "white"
                font { family: Tema.fonte; pixelSize: 15 }
                background: null
                verticalAlignment: TextInput.AlignVCenter
                text: seletorDeImagens.seletor.busca
                Accessible.name: "Buscar jogo"
                onTextEdited: seletorDeImagens.seletor.busca = text
                onAccepted: seletorDeImagens.seletor.buscarAgora()
                Keys.onDownPressed: seletorDeImagens.moverFoco(0)
            }
        }

        Item {
            id: conteudo
            anchors { left: parent.left; right: parent.right; top: campo.bottom; bottom: parent.bottom; topMargin: 8 }

            // Buscando e ainda sem nenhuma miniatura.
            BusyIndicator {
                objectName: seletorDeImagens.objectName + "Carregando"
                anchors.centerIn: parent
                width: 32
                height: 32
                running: visible
                visible: seletorDeImagens.seletor.buscando && grade.count === 0 && !seletorDeImagens.seletor.vazio
            }

            EstadoVazio {
                objectName: seletorDeImagens.objectName + "Vazio"
                anchors.fill: parent
                visible: seletorDeImagens.seletor.vazio
                glifo: ""  // imagem
                titulo: seletorDeImagens.seletor.tituloDoEstado
                descricao: seletorDeImagens.seletor.descricaoDoEstado
                // shortcut: o botão "Preferências" do aviso de chave ausente ou inválida entra com a tela de preferências (plano 7, D42).
            }

            // A tela "Baixando…" da imagem escolhida.
            Column {
                objectName: seletorDeImagens.objectName + "Baixando"
                anchors.centerIn: parent
                width: Math.min(parent.width - 48, 320)
                spacing: 10
                visible: seletorDeImagens.seletor.baixando
                Text {
                    width: parent.width
                    text: "Baixando…"
                    textFormat: Text.PlainText
                    horizontalAlignment: Text.AlignHCenter
                    color: Tema.texto
                    font { family: Tema.fonte; pixelSize: 20; weight: Font.DemiBold }
                }
                ProgressBar {
                    width: parent.width
                    from: 0
                    to: 1
                    indeterminate: seletorDeImagens.seletor.progresso < 0 || seletorDeImagens.seletor.textoDoProgresso === ""
                    value: Math.max(0, seletorDeImagens.seletor.progresso)
                }
                Text {
                    width: parent.width
                    text: seletorDeImagens.seletor.textoDoProgresso
                    textFormat: Text.PlainText
                    horizontalAlignment: Text.AlignHCenter
                    color: Tema.textoSecundario
                    font { family: Tema.fonte; pixelSize: 13 }
                }
            }

            GridView {
                id: grade
                objectName: seletorDeImagens.objectName + "Grade"
                anchors { fill: parent; leftMargin: 12; rightMargin: 12 }
                visible: !seletorDeImagens.seletor.vazio && !seletorDeImagens.seletor.baixando
                model: seletorDeImagens.seletor
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                cellWidth: Math.floor(width / seletorDeImagens.colunas)
                cellHeight: seletorDeImagens.alturaDaCelula + 12
                ScrollBar.vertical: BarraDeRolagem {}

                delegate: Item {
                    id: celula
                    required property int index
                    required property string miniatura
                    required property bool animada
                    required property bool carregando
                    width: grade.cellWidth
                    height: grade.cellHeight

                    Button {
                        id: botao
                        objectName: seletorDeImagens.objectName + "Miniatura" + celula.index
                        anchors.centerIn: parent
                        width: seletorDeImagens.larguraDaCelula
                        height: seletorDeImagens.alturaDaCelula
                        padding: 0
                        focusPolicy: Qt.StrongFocus
                        enabled: !celula.carregando
                        // Só o foco ou o mouse tocam a prévia animada: uma imagem de até 200 MB por célula,
                        // tocando todas, travaria a janela.
                        readonly property bool tocando: celula.animada && (hovered || activeFocus)
                        Accessible.name: "Miniatura " + (celula.index + 1)
                        Accessible.role: Accessible.Button
                        Keys.onReturnPressed: click()
                        Keys.onEnterPressed: click()
                        Keys.onRightPressed: seletorDeImagens.moverFoco(celula.index + 1)
                        Keys.onLeftPressed: seletorDeImagens.moverFoco(celula.index - 1)
                        Keys.onDownPressed: seletorDeImagens.moverFoco(celula.index + seletorDeImagens.colunas)
                        Keys.onUpPressed: seletorDeImagens.moverFoco(celula.index - seletorDeImagens.colunas)
                        onClicked: seletorDeImagens.seletor.escolher(celula.index)

                        // O fundo do logo imita a página escura de destino: a maioria dos logos é branca sobre transparência.
                        background: Rectangle {
                            radius: 8
                            color: seletorDeImagens.horizontal ? "#1b1b1f" : Tema.superficie
                            border { width: botao.visualFocus ? 3 : botao.hovered ? 2 : 1; color: botao.visualFocus || botao.hovered ? Tema.destaque : Tema.borda }
                        }
                        contentItem: Item {
                            clip: true
                            Image {
                                anchors.fill: parent
                                anchors.margins: 1
                                source: celula.miniatura
                                sourceSize.width: seletorDeImagens.larguraDaCelula * 2
                                sourceSize.height: seletorDeImagens.alturaDaCelula * 2
                                fillMode: seletorDeImagens.horizontal ? Image.PreserveAspectFit : Image.PreserveAspectCrop
                                asynchronous: true
                                cache: false
                            }
                            Loader {
                                anchors.fill: parent
                                anchors.margins: 1
                                active: botao.tocando
                                sourceComponent: AnimatedImage {
                                    source: celula.miniatura
                                    fillMode: Image.PreserveAspectCrop
                                    cache: false
                                }
                            }
                            BusyIndicator {
                                anchors.centerIn: parent
                                width: 28
                                height: 28
                                running: celula.carregando
                                visible: running
                            }
                        }
                    }
                }
            }
        }
    }
}
