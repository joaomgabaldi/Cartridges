import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import QtQuick.Window

// A lista completa de conquistas de um jogo: o logo (ou o nome), o resumo e a barra no topo, e os grupos "Desbloqueadas"
// (da mais recente para a mais antiga) e "Bloqueadas", apagadas. Só desenha: o estado é do `conquistasDoJogo`
// (cartridges/modelos/conquistas.py). Modal para o mouse, o teclado e o controle; o foco volta a quem o abriu. Sem título
// visível: o logo (ou o nome) é a manchete, e o título só vive no nome acessível. Todo texto de conquista é de terceiros:
// texto puro.
MolduraDoDialogo {
    id: dialogo
    objectName: "dialogoDeConquistas"

    function contem(pai, item) {
        for (var p = item; p; p = p.parent) // `parent`: o `parentItem` do C++ não existe no QML
            if (p === pai) return true
        return false
    }
    function trazer(item) {
        var topo = item.mapToItem(rolagem.contentItem, 0, 0).y
        var base = topo + item.height
        if (topo < rolagem.contentY) rolagem.contentY = Math.max(0, topo - 8)
        else if (base > rolagem.contentY + rolagem.height) rolagem.contentY = base - rolagem.height + 8
    }
    // As setas andam entre as fileiras, na ordem do Tab, e nunca saem da lista (o X do cabeçalho fica de fora).
    function irParaVizinha(de, adiante) {
        var proximo = de.nextItemInFocusChain(adiante)
        if (proximo && contem(rolagem.contentItem, proximo)) proximo.forceActiveFocus(Qt.TabFocusReason)
    }

    aberto: conquistasDoJogo.aberto
    largura: 520
    altura: 640
    focoInicial: cabecalho.botaoFechar
    nomeAcessivel: "Conquistas"
    onFecharPedido: conquistasDoJogo.fechar()
    // Fechado a partir de um menu, o foco não tem para onde voltar: vai à página à vista.
    onRetornoPerdido: if (Window.window && Window.window.paginaDoControle) Window.window.paginaDoControle.focarGrade()
    onAbertoChanged: if (aberto) rolagem.contentY = 0

    Connections {
        target: dialogo.Window.window
        function onActiveFocusItemChanged() {
            var foco = dialogo.Window.window.activeFocusItem
            if (dialogo.visible && foco && dialogo.contem(rolagem.contentItem, foco)) dialogo.trazer(foco)
        }
    }

    component Secao: ColumnLayout {
        id: secao
        property string titulo
        property var fileiras: []
        visible: fileiras.length > 0
        spacing: 12

        Text {
            Layout.fillWidth: true
            text: secao.titulo
            textFormat: Text.PlainText
            color: Tema.texto
            font { family: Tema.fonte; pixelSize: Tema.corpo; weight: Tema.pesoForte }
            Accessible.role: Accessible.Heading
            Accessible.name: text
        }
        GrupoDeLinhas {
            Layout.fillWidth: true
            // A seção já some sem linhas; o grupo escondido pela altura zero nunca mediria as que o Repeater cria.
            visible: true
            Repeater {
                // Só a contagem: o lote de ícones refaz a lista inteira e não deve recriar as fileiras.
                model: secao.fileiras.length
                delegate: LinhaDoGrupo {
                    id: fileira
                    objectName: "fileiraDeConquista"
                    required property int index
                    readonly property var modelData: secao.fileiras[index] || ({})
                    property alias alvo: alvoDaLinha
                    comTextos: false
                    // Ícone de 36 e, no mínimo, 50 + 4; o texto longo alarga a fileira.
                    alturaMinima: Math.max(50, linha.implicitHeight + 12)
                    opacity: modelData.desbloqueada ? 1 : Tema.opacidadeApagado

                    RowLayout {
                        id: linha
                        anchors {
                            left: parent.left; leftMargin: 14
                            right: parent.right; rightMargin: 14
                            verticalCenter: parent.verticalCenter; verticalCenterOffset: fileira._separador / 2
                        }
                        spacing: 12

                        IconeDaConquista {
                            Layout.alignment: Qt.AlignVCenter
                            tamanho: 36
                            interrogacao: 24
                            url: fileira.modelData.icone.url
                            cinza: fileira.modelData.icone.cinza
                            oculta: fileira.modelData.icone.oculta
                        }
                        ColumnLayout {
                            Layout.fillWidth: true
                            Layout.alignment: Qt.AlignVCenter
                            spacing: 3
                            Text {
                                objectName: "tituloDaConquista"
                                Layout.fillWidth: true
                                text: fileira.modelData.titulo
                                textFormat: Text.PlainText
                                wrapMode: Text.Wrap
                                lineHeightMode: Text.FixedHeight
                                lineHeight: Tema.alturaDoCorpo
                                color: Tema.texto
                                font { family: Tema.fonte; pixelSize: Tema.corpo }
                            }
                            Text {
                                objectName: "subtituloDaConquista"
                                Layout.fillWidth: true
                                visible: text !== ""
                                text: fileira.modelData.subtitulo
                                textFormat: Text.PlainText
                                wrapMode: Text.Wrap
                                lineHeightMode: Text.FixedHeight
                                lineHeight: Tema.alturaDaLegenda
                                color: Tema.textoSecundario
                                font { family: Tema.fonte; pixelSize: Tema.legenda }
                            }
                        }
                        ColumnLayout {
                            Layout.alignment: Qt.AlignVCenter
                            spacing: 0
                            Text {
                                objectName: "dataDaConquista"
                                Layout.alignment: Qt.AlignRight
                                visible: text !== ""
                                text: fileira.modelData.data
                                textFormat: Text.PlainText
                                color: Tema.textoSecundario
                                font { family: Tema.fonte; pixelSize: Tema.corpo }
                            }
                            Text {
                                objectName: "porcentagemDaConquista"
                                Layout.alignment: Qt.AlignRight
                                visible: text !== ""
                                text: fileira.modelData.porcentagem
                                textFormat: Text.PlainText
                                color: fileira.modelData.rara ? "#e5a50a" : Tema.textoSecundario
                                font { family: Tema.fonte; pixelSize: Tema.corpo; weight: fileira.modelData.rara ? Font.Bold : Font.Normal }
                            }
                        }
                    }

                    Button {
                        id: alvoDaLinha
                        objectName: "alvoDaFileiraDeConquista"
                        anchors.fill: parent
                        focusPolicy: Qt.StrongFocus  // um `Control`: o anel só aparece com o teclado (`visualFocus`)
                        contentItem: Item {}
                        background: Item {}
                        Binding { target: fileira; property: "foco"; value: alvoDaLinha.visualFocus }
                        Accessible.role: Accessible.ListItem
                        Accessible.name: [fileira.modelData.titulo, fileira.modelData.subtitulo].filter(Boolean).join(". ")
                        Keys.onUpPressed: dialogo.irParaVizinha(alvoDaLinha, false)
                        Keys.onDownPressed: dialogo.irParaVizinha(alvoDaLinha, true)
                    }
                }
            }
        }
    }

    CabecalhoDoDialogo {
        id: cabecalho
        titulo: ""
        sombra: rolagem.contentY > 0
        enabled: !preferencias.aberto
        onFechar: conquistasDoJogo.fechar()
    }

    Flickable {
        id: rolagem
        objectName: "rolagemDeConquistas"
        Layout.fillWidth: true
        Layout.fillHeight: true
        Layout.preferredHeight: contentHeight
        Layout.minimumHeight: 0
        enabled: !preferencias.aberto
        contentWidth: width
        contentHeight: conteudo.implicitHeight + 48
        boundsBehavior: Flickable.StopAtBounds
        RolagemDaRoda { alvo: rolagem }
        clip: true
        ScrollBar.vertical: BarraDeRolagem {}
        Keys.onPressed: event => {
            var passo = event.key === Qt.Key_PageUp ? -rolagem.height : event.key === Qt.Key_PageDown ? rolagem.height : 0
            if (passo === 0) return
            rolagem.contentY = Math.max(0, Math.min(rolagem.contentHeight - rolagem.height, rolagem.contentY + passo))
            event.accepted = true
        }

        ColumnLayout {
            id: conteudo
            x: 24
            y: 24
            width: rolagem.width - 48
            spacing: 12

            CabecalhoDoJogo {
                Layout.fillWidth: true
                logo: conquistasDoJogo.logo
                larguraDoLogo: conquistasDoJogo.larguraDoLogo
                nome: conquistasDoJogo.nome
                nomeDoLogo: "logoDasConquistas"
                nomeDoTexto: "nomeDasConquistas"
            }
            Text {
                objectName: "resumoDasConquistas"
                Layout.fillWidth: true
                text: conquistasDoJogo.resumo
                textFormat: Text.PlainText
                elide: Text.ElideRight
                horizontalAlignment: Text.AlignHCenter
                color: Tema.textoSecundario
                font { family: Tema.fonte; pixelSize: Tema.corpo }
            }
            BarraDeProgresso {
                objectName: "barraDasConquistas"
                Layout.fillWidth: true
                value: conquistasDoJogo.fracao
            }
            Secao {
                objectName: "secaoDesbloqueadas"
                Layout.fillWidth: true
                Layout.topMargin: 12
                titulo: "Desbloqueadas"
                fileiras: conquistasDoJogo.desbloqueadas
            }
            Secao {
                objectName: "secaoBloqueadas"
                Layout.fillWidth: true
                Layout.topMargin: 12
                titulo: "Bloqueadas"
                fileiras: conquistasDoJogo.bloqueadas
            }
        }
    }
}
