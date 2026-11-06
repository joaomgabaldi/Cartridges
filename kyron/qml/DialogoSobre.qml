import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import QtQuick.Window
import QtCore
import QtQuick.Dialogs
import QtQuick.Effects

// As páginas do "Sobre", numa `MolduraDoDialogo`; só desenha, o estado é do `modelo` (kyron/modelos/sobre.py). Texto
// de terceiros (o log) em PlainText; a licença é a única em StyledText, e só o link dela é aberto.
MolduraDoDialogo {
    id: dialogo
    objectName: "dialogoSobre"

    property QtObject modelo
    readonly property string pagina: modelo ? modelo.pagina : "principal"
    property string paginaAnterior: "principal"
    property bool avisoAberto: false
    readonly property var linhas: ({ novidades: linhaNovidades, legal: linhaLegal,
                                     problemas: linhaProblemas, depuracao: linhaDepuracao })

    aberto: !!modelo && modelo.aberto
    largura: 360
    setasMovemOFoco: true
    rolagemDasSetas: rolagem
    focoInicial: linhaNovidades.aparece ? linhaNovidades.botaoDaLinha : linhaProblemas.botaoDaLinha
    nomeAcessivel: "Sobre o Kyron"
    onFecharPedido: pagina === "principal" ? modelo.fechar() : modelo.voltar()
    onAbertoChanged: if (aberto) { paginaAnterior = "principal"; rolagem.contentY = 0 }
    onPaginaChanged: {
        var de = paginaAnterior
        paginaAnterior = pagina
        rolagem.contentY = 0
        var foco = Window.window ? Window.window.activeFocusItem : null
        var teclado = pedidoPorTeclado || (!!foco && foco.visualFocus === true)
        Qt.callLater(() => dialogo.focar(de, teclado))
    }

    function focar(de, teclado) {
        if (!aberto) return
        var alvo = pagina === "problemas" && linhas[de] && linhas[de].visible ? linhas[de].botaoDaLinha
            : pagina !== "principal" ? (pagina === "depuracao" ? botaoCopiar : botaoVoltar)
            : (linhas[de] && linhas[de].visible ? linhas[de].botaoDaLinha : focoInicial)
        alvo.forceActiveFocus(teclado ? Qt.TabFocusReason : Qt.OtherFocusReason)
    }

    Shortcut {
        sequence: "Alt+Left"
        enabled: dialogo.aberto && !dialogo.avisoAberto && dialogo.pagina !== "principal"
        onActivated: { dialogo.pedidoPorTeclado = true; dialogo.modelo.voltar(); dialogo.pedidoPorTeclado = false }
    }

    Loader {
        id: cargaDoSalvar
        active: false
        visible: false
        sourceComponent: FileDialog {
            title: "Salvar como…"
            fileMode: FileDialog.SaveFile
            selectedFile: StandardPaths.writableLocation(StandardPaths.DocumentsLocation) + "/" + dialogo.modelo.nomeDoLog
            onAccepted: dialogo.modelo.salvar(selectedFile)
        }
        onLoaded: item.open()
    }

    component LinhaDoSobre: LinhaDeAcao {
        id: linha
        property string destino
        property string mnemonico
        titulo: dialogo.modelo ? dialogo.modelo.titulos[destino] : ""
        icone: "go-next"
        comTextos: false
        function click() { botaoDaLinha.click() }
        onAcionada: dialogo.modelo.irPara(destino)
        Text {
            objectName: linha.objectName + "Rotulo"
            anchors { left: parent.left; leftMargin: 14; right: parent.right; rightMargin: 14 + 16 + 12; verticalCenter: parent.verticalCenter; verticalCenterOffset: linha._separador / 2 }
            text: dialogo.altSegurado ? "<u>" + linha.titulo.charAt(0) + "</u>" + linha.titulo.slice(1) : linha.titulo
            textFormat: dialogo.altSegurado ? Text.StyledText : Text.PlainText
            elide: Text.ElideRight
            lineHeightMode: Text.FixedHeight
            lineHeight: Tema.alturaDoCorpo
            color: Tema.texto
            font { family: Tema.fonte; pixelSize: Tema.corpo }
        }
        Shortcut {
            sequence: "Alt+" + linha.mnemonico
            enabled: dialogo.aberto && !dialogo.avisoAberto && dialogo.pagina === (destino === "depuracao" ? "problemas" : "principal") && linha.visible
            onActivated: linha.botaoDaLinha.click()
        }
    }

    component TextoDeCorpo: Text {
        Layout.fillWidth: true
        textFormat: Text.PlainText
        wrapMode: Text.Wrap
        lineHeightMode: Text.FixedHeight
        lineHeight: Tema.alturaDoCorpo
        color: Tema.texto
        font { family: Tema.fonte; pixelSize: Tema.corpo }
    }

    CabecalhoDoDialogo {
        id: cabecalho
        titulo: dialogo.pagina === "principal" ? "Kyron" : (dialogo.modelo ? dialogo.modelo.titulos[dialogo.pagina] : "")
        objetoDoTitulo: "tituloDaPaginaDoSobre"
        opacidadeDoTitulo: dialogo.pagina !== "principal" || rolagem.contentY > nomeDoApp.y + nomeDoApp.height ? 1 : 0
        sombra: rolagem.contentY > 0
        onFechar: dialogo.modelo.fechar()
        inicio: [
            Botao {
                id: botaoVoltar
                objectName: "botaoVoltarDoSobre"
                visible: dialogo.pagina !== "principal"
                estilo: "plano"
                icone: "go-previous"
                dica: "Voltar"
                onClicked: dialogo.modelo.voltar()
            }
        ]
    }

    Flickable {
        id: rolagem
        objectName: "rolagemDoSobre"
        Layout.fillWidth: true
        Layout.fillHeight: true
        Layout.preferredHeight: contentHeight
        Layout.minimumHeight: 0
        contentWidth: width
        contentHeight: corpo.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: BarraDeRolagem {}
        RolagemDaRoda { alvo: rolagem }
        Item {
            id: corpo
            width: rolagem.width
            property real alturaDaPrincipal: 0
            implicitHeight: Math.max(alturaDaPrincipal, principal.visible ? principal.implicitHeight : 0, novidades.visible ? novidades.implicitHeight : 0,
                legal.visible ? legal.implicitHeight : 0,
                problemas.visible ? problemas.implicitHeight : 0, depuracao.visible ? depuracao.implicitHeight : 0)

            ColumnLayout {
                id: principal
                visible: dialogo.pagina === "principal"
                x: 12
                width: parent.width - 24
                spacing: 6
                onImplicitHeightChanged: if (visible && implicitHeight > 0) corpo.alturaDaPrincipal = implicitHeight
                onVisibleChanged: if (visible && implicitHeight > 0) corpo.alturaDaPrincipal = implicitHeight

                Image {
                    Layout.alignment: Qt.AlignHCenter
                    Layout.topMargin: 12
                    Layout.preferredWidth: 128
                    Layout.preferredHeight: 128
                    source: dialogo.modelo ? dialogo.modelo.icone : ""
                    sourceSize: Qt.size(256, 256)
                    fillMode: Image.PreserveAspectFit
                    Accessible.ignored: true
                    layer.enabled: true
                    layer.effect: MultiEffect {
                        shadowEnabled: true
                        shadowColor: Qt.rgba(0, 0, 6 / 255, 0.05)
                        blurMax: 12
                        shadowBlur: 1.0
                        shadowVerticalOffset: 1
                    }
                }
                Text {
                    id: nomeDoApp
                    objectName: "nomeDoApp"
                    Layout.fillWidth: true
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.Wrap
                    text: "Kyron"
                    textFormat: Text.PlainText
                    color: Tema.texto
                    font { family: Tema.fonte; pixelSize: Tema.titulo1; weight: Tema.pesoTitulo1 }
                }
                Text {
                    objectName: "desenvolvedorDoApp"
                    Layout.fillWidth: true
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.Wrap
                    text: dialogo.modelo ? dialogo.modelo.desenvolvedor : ""
                    textFormat: Text.PlainText
                    lineHeightMode: Text.FixedHeight
                    lineHeight: Tema.alturaDoCorpo
                    color: Tema.texto
                    font { family: Tema.fonte; pixelSize: Tema.corpo }
                }
                Button {
                    id: botaoDaVersao
                    objectName: "botaoDaVersao"
                    Layout.alignment: Qt.AlignHCenter
                    Layout.topMargin: 3
                    focusPolicy: Qt.StrongFocus
                    hoverEnabled: true
                    topPadding: 3
                    bottomPadding: 3
                    leftPadding: 18
                    rightPadding: 18
                    implicitHeight: Math.max(24, selo.implicitHeight) + topPadding + bottomPadding
                    Accessible.name: "Copiar a versão"
                    Keys.onReturnPressed: click()
                    Keys.onEnterPressed: click()
                    onClicked: dialogo.modelo.copiarVersao()
                    contentItem: Text {
                        id: selo
                        objectName: "versaoDoApp"
                        text: dialogo.modelo ? dialogo.modelo.versao : ""
                        textFormat: Text.PlainText
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                        color: Tema.destaqueTexto
                        font { family: Tema.fonte; pixelSize: Tema.corpo; weight: Tema.pesoForte }
                    }
                    background: Rectangle {
                        radius: height / 2
                        color: Qt.alpha(Tema.destaqueTexto, botaoDaVersao.down ? 0.30 : botaoDaVersao.hovered ? 0.15 : 0.10)
                        AnelDeFoco { ativo: botaoDaVersao.visualFocus; raio: parent.radius; afastamento: 1 }
                    }
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.topMargin: 18
                    Layout.bottomMargin: 18
                    spacing: 18
                    // `visible` explícito em todos: criado com o diálogo escondido, o grupo mediria zero para sempre.
                    GrupoDeLinhas {
                        Layout.fillWidth: true
                        visible: linhaNovidades.aparece
                        LinhaDoSobre { id: linhaNovidades; objectName: "linhaNovidades"; destino: "novidades"; mnemonico: "N"; aparece: !!dialogo.modelo && dialogo.modelo.temNovidades }
                    }
                    GrupoDeLinhas {
                        Layout.fillWidth: true
                        visible: true
                        LinhaDoSobre { id: linhaProblemas; objectName: "linhaProblemas"; destino: "problemas"; mnemonico: "S" }
                    }
                    GrupoDeLinhas {
                        Layout.fillWidth: true
                        visible: true
                        LinhaDoSobre { id: linhaLegal; objectName: "linhaLegal"; destino: "legal"; mnemonico: "A" }
                    }
                }
            }

            ColumnLayout {
                id: novidades
                visible: dialogo.pagina === "novidades"
                x: 12
                width: parent.width - 24
                spacing: 8

                TextEdit {
                    objectName: "cabecalhoDaVersao"
                    Layout.fillWidth: true
                    Layout.topMargin: 18
                    readOnly: true
                    selectByMouse: true
                    text: "Versão " + (dialogo.modelo ? dialogo.modelo.versao : "")
                    textFormat: TextEdit.PlainText
                    wrapMode: TextEdit.Wrap
                    color: Tema.texto
                    selectionColor: Tema.destaque
                    selectedTextColor: Tema.textoDoDestaque
                    font { family: Tema.fonte; pixelSize: Tema.corpo; weight: Font.Bold }
                }
                Repeater {
                    model: dialogo.modelo ? dialogo.modelo.novidades : []
                    RowLayout {
                        id: novidade
                        required property int index
                        required property var modelData
                        Layout.fillWidth: true
                        Layout.bottomMargin: index === (dialogo.modelo ? dialogo.modelo.novidades.length : 0) - 1 ? 18 : 0
                        spacing: 8
                        Text {
                            Layout.alignment: Qt.AlignTop
                            visible: novidade.modelData.tipo === "li"
                            text: "•"
                            textFormat: Text.PlainText
                            color: Tema.texto
                            font { family: Tema.fonte; pixelSize: Tema.corpo }
                        }
                        TextEdit {
                            objectName: "itemDeNovidade-" + novidade.index
                            Layout.fillWidth: true
                            readOnly: true
                            selectByMouse: true
                            text: novidade.modelData.texto
                            textFormat: TextEdit.PlainText
                            wrapMode: TextEdit.Wrap
                            color: Tema.texto
                            selectionColor: Tema.destaque
                            selectedTextColor: Tema.textoDoDestaque
                            font { family: Tema.fonte; pixelSize: Tema.corpo }
                        }
                    }
                }
            }

            ColumnLayout {
                id: legal
                visible: dialogo.pagina === "legal"
                x: 12
                width: parent.width - 24

                // shortcut: o Enter abre sempre a GPL, quando houver mais de um link no texto.
                Text {
                    id: licenca
                    objectName: "licencaDoApp"
                    Layout.fillWidth: true
                    Layout.topMargin: 18
                    Layout.bottomMargin: 18
                    activeFocusOnTab: true
                    Accessible.role: Accessible.Link
                    Keys.onReturnPressed: dialogo.modelo.abrirLicenca(dialogo.modelo.urlDaLicenca)
                    Keys.onEnterPressed: dialogo.modelo.abrirLicenca(dialogo.modelo.urlDaLicenca)
                    text: dialogo.modelo ? dialogo.modelo.copyright.split("\n").join("<br>") + "<br><br>" + dialogo.modelo.licenca : ""
                    textFormat: Text.StyledText
                    wrapMode: Text.Wrap
                    linkColor: Tema.destaqueTexto
                    color: Tema.texto
                    font { family: Tema.fonte; pixelSize: Tema.corpo }
                    onLinkActivated: link => dialogo.modelo.abrirLicenca(link)
                    HoverHandler { cursorShape: licenca.hoveredLink !== "" ? Qt.PointingHandCursor : Qt.ArrowCursor }

                    AnelDeFoco { objectName: "focoDaLicenca"; ativo: licenca.activeFocus; raio: 4; afastamento: -4 }
                }
            }

            ColumnLayout {
                id: problemas
                visible: dialogo.pagina === "problemas"
                x: 12
                width: parent.width - 24
                spacing: 18

                TextoDeCorpo {
                    objectName: "textoDeSuporte"
                    Layout.topMargin: 18
                    text: dialogo.modelo ? dialogo.modelo.textoDeSuporte : ""
                }
                GrupoDeLinhas {
                    Layout.fillWidth: true
                    Layout.bottomMargin: 18
                    visible: true
                    LinhaDoSobre { id: linhaDepuracao; objectName: "linhaDepuracao"; destino: "depuracao"; mnemonico: "I" }
                }
            }

            ColumnLayout {
                id: depuracao
                visible: dialogo.pagina === "depuracao"
                x: 12
                width: parent.width - 24

                TextEdit {
                    id: logDepuracao
                    objectName: "textoDaDepuracao"
                    Layout.fillWidth: true
                    Layout.topMargin: 18
                    Layout.bottomMargin: 18
                    readOnly: true
                    selectByMouse: true
                    activeFocusOnTab: true
                    Accessible.name: "Informações de depuração"
                    text: dialogo.modelo ? dialogo.modelo.depuracao : ""
                    textFormat: TextEdit.PlainText
                    wrapMode: TextEdit.Wrap
                    color: Tema.texto
                    selectionColor: Tema.destaque
                    selectedTextColor: Tema.textoDoDestaque
                    font { family: Tema.fonte; pixelSize: Tema.corpo }
                    Keys.onUpPressed: rolagem.contentY = Math.max(0, rolagem.contentY - 40)
                    Keys.onDownPressed: rolagem.contentY = Math.max(0, Math.min(rolagem.contentHeight - rolagem.height, rolagem.contentY + 40))
                }
            }
        }
    }

    Item {
        id: barraDeAcoes
        objectName: "barraDeAcoesDoSobre"
        Layout.fillWidth: true
        implicitHeight: visible ? 46 : 0
        visible: dialogo.pagina === "depuracao"
        Rectangle { width: parent.width; height: 1; color: Tema.sombraDaBarra }
        Botao {
            id: botaoCopiar
            objectName: "botaoCopiarTexto"
            anchors { left: parent.left; leftMargin: 6; verticalCenter: parent.verticalCenter }
            text: "Copiar texto"
            sublinharPrimeira: dialogo.altSegurado
            onClicked: dialogo.modelo.copiar()
            Shortcut { sequence: "Alt+C"; enabled: barraDeAcoes.visible && dialogo.aberto && !dialogo.avisoAberto; onActivated: botaoCopiar.click() }
        }
        Botao {
            id: botaoSalvar
            objectName: "botaoSalvarComo"
            anchors { right: parent.right; rightMargin: 6; verticalCenter: parent.verticalCenter }
            text: "Salvar como…"
            sublinharPrimeira: dialogo.altSegurado
            onClicked: { if (cargaDoSalvar.item) cargaDoSalvar.item.open(); else cargaDoSalvar.active = true }
            Shortcut { sequence: "Alt+S"; enabled: barraDeAcoes.visible && dialogo.aberto && !dialogo.avisoAberto; onActivated: botaoSalvar.click() }
        }
    }
}
