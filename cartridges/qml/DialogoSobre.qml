import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Window
import QtCore
import QtQuick.Dialogs

// "Sobre o Cartridges" (D84): as páginas do `Adw.AboutDialog`, num modal de 420×560. Só desenha: os textos, a página à
// vista e as ações são do `modelo` (o `Sobre`, cartridges/modelos/sobre.py). Texto de terceiros (o log) em PlainText; a
// licença é a única em StyledText, e só o link dela é aberto. Esc volta uma página e, na principal, fecha; o foco volta
// a quem abriu.
Rectangle {
    id: dialogo
    objectName: "dialogoSobre"

    property QtObject modelo
    readonly property string pagina: modelo ? modelo.pagina : "principal"
    // Quem tinha o foco ao abrir: volta a tê-lo ao fechar.
    property Item retorno: null
    // A página de onde se veio, para o foco voltar à linha dela.
    property string paginaAnterior: "principal"
    readonly property var linhas: ({ novidades: linhaNovidades, detalhes: linhaDetalhes, creditos: linhaCreditos,
                                     legal: linhaLegal, problemas: linhaProblemas })

    Accessible.role: Accessible.Dialog
    Accessible.name: "Sobre o Cartridges"

    anchors.fill: parent
    visible: !!modelo && modelo.aberto
    color: "#80000000"
    Keys.onEscapePressed: pagina === "principal" ? modelo.fechar() : modelo.voltar()
    // Modal para o teclado e o controle: nenhuma tecla chega à página de trás. O Tab passa, para circular.
    Keys.onPressed: event => event.accepted = event.key !== Qt.Key_Tab && event.key !== Qt.Key_Backtab

    function focar(de) {
        if (!visible) return
        var alvo = pagina !== "principal" ? botaoVoltar : (linhas[de] && linhas[de].visible ? linhas[de]
            : (linhaNovidades.visible ? linhaNovidades : linhaDetalhes))
        alvo.forceActiveFocus(Qt.TabFocusReason)
    }
    function devolverAoRetorno() {
        if (visible) return
        // Quem abriu pode ter sumido (o item do menu fechou ao escolher "Sobre o Cartridges"), ou ter perdido o foco para
        // a janela quando o fundo ficou desabilitado: o foco vai à página à vista.
        if (retorno && retorno !== Window.contentItem && retorno.visible && retorno.enabled) retorno.forceActiveFocus(Qt.TabFocusReason)
        else dialogo.retornoPerdido()
    }
    signal retornoPerdido()

    onVisibleChanged: {
        if (visible) {
            retorno = Window.window ? Window.window.activeFocusItem : null
            paginaAnterior = "principal"
            rolagem.contentY = 0
            // Adiado: o item acabou de ficar visível e só então aceita o foco.
            Qt.callLater(() => dialogo.focar("principal"))
        } else {
            // Depois de a página de trás voltar a ficar habilitada.
            Qt.callLater(devolverAoRetorno)
        }
    }
    onPaginaChanged: {
        var de = paginaAnterior
        paginaAnterior = pagina
        rolagem.contentY = 0
        Qt.callLater(() => dialogo.focar(de))
    }

    MouseArea { anchors.fill: parent } // o que está embaixo não recebe cliques

    // Criado só ao clicar: o seletor nativo não precisa existir antes. O nome do log na pasta Documentos (um nome solto
    // abriria o seletor na pasta do aplicativo).
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

    Rectangle {
        id: cartao
        anchors.centerIn: parent
        width: Math.min(420, parent.width - 48)
        height: Math.min(560, parent.height - 48)
        radius: 8
        color: Tema.fundo
        border.color: Tema.botaoSobre
        clip: true

        // O botão de ícone do cabeçalho (voltar e fechar).
        component BotaoDoCabecalho: Button {
            id: botaoDeIcone
            property string glifo
            implicitWidth: 34
            implicitHeight: 34
            focusPolicy: Qt.StrongFocus
            Keys.onReturnPressed: click()
            Keys.onEnterPressed: click()
            contentItem: Text {
                text: botaoDeIcone.glifo
                textFormat: Text.PlainText
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
                color: Tema.texto
                font { family: Tema.fonteDeIcones; pixelSize: 14 }
            }
            background: Rectangle {
                radius: 6
                color: botaoDeIcone.down ? Tema.pressionado : botaoDeIcone.hovered ? Tema.botaoSobre : "transparent"
                border { width: botaoDeIcone.visualFocus ? 2 : 0; color: Tema.texto }
            }
        }

        // O botão de texto do corpo.
        component BotaoDoSobre: Button {
            id: botaoDeTexto
            focusPolicy: Qt.StrongFocus
            implicitHeight: 36
            leftPadding: 20
            rightPadding: 20
            Keys.onReturnPressed: click()
            Keys.onEnterPressed: click()
            contentItem: Text {
                text: botaoDeTexto.text
                textFormat: Text.PlainText
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
                color: Tema.texto
                font { family: Tema.fonte; pixelSize: 14 }
            }
            background: Rectangle {
                radius: 6
                color: Tema.superficie
                opacity: botaoDeTexto.down ? 0.75 : botaoDeTexto.hovered ? 0.9 : 1
                border { width: botaoDeTexto.visualFocus ? 2 : 1; color: botaoDeTexto.visualFocus ? Tema.texto : Tema.borda }
            }
        }

        // Uma linha da página principal: o rótulo e a seta para a página.
        component LinhaDoSobre: Button {
            id: linha
            property string destino
            width: parent.width
            implicitHeight: 48
            focusPolicy: Qt.StrongFocus
            leftPadding: 16
            rightPadding: 16
            text: dialogo.modelo ? dialogo.modelo.titulos[destino] : ""
            Keys.onReturnPressed: click()
            Keys.onEnterPressed: click()
            onClicked: dialogo.modelo.irPara(destino)
            contentItem: Item {
                Text {
                    anchors { left: parent.left; right: seta.left; rightMargin: 8; verticalCenter: parent.verticalCenter }
                    text: linha.text
                    textFormat: Text.PlainText
                    elide: Text.ElideRight
                    color: Tema.texto
                    font { family: Tema.fonte; pixelSize: 14 }
                }
                Text {
                    id: seta
                    anchors { right: parent.right; verticalCenter: parent.verticalCenter }
                    text: ""  // seta para a direita
                    textFormat: Text.PlainText
                    color: Tema.textoSecundario
                    font { family: Tema.fonteDeIcones; pixelSize: 12 }
                }
            }
            background: Rectangle {
                color: linha.down ? Tema.pressionado : linha.hovered ? Tema.botaoSobre : "transparent"
                border { width: linha.visualFocus ? 2 : 0; color: Tema.texto }
            }
        }

        Item {
            id: cabecalho
            width: parent.width
            height: 56

            BotaoDoCabecalho {
                id: botaoVoltar
                objectName: "botaoVoltarDoSobre"
                anchors { left: parent.left; leftMargin: 12; verticalCenter: parent.verticalCenter }
                visible: dialogo.pagina !== "principal"
                glifo: ""  // seta para a esquerda
                Accessible.name: "Voltar"
                onClicked: dialogo.modelo.voltar()
            }
            Text {
                objectName: "tituloDaPaginaDoSobre"
                anchors { left: parent.left; leftMargin: 56; right: botaoFechar.left; rightMargin: 8; verticalCenter: parent.verticalCenter }
                horizontalAlignment: Text.AlignHCenter
                text: dialogo.modelo ? dialogo.modelo.titulos[dialogo.pagina] : ""
                textFormat: Text.PlainText
                elide: Text.ElideRight
                color: Tema.texto
                font { family: Tema.fonte; pixelSize: 15; weight: Font.DemiBold }
                Accessible.role: Accessible.Heading
                Accessible.name: text
            }
            BotaoDoCabecalho {
                id: botaoFechar
                objectName: "botaoFecharDoSobre"
                anchors { right: parent.right; rightMargin: 12; verticalCenter: parent.verticalCenter }
                glifo: ""  // X
                Accessible.name: "Fechar"
                onClicked: dialogo.modelo.fechar()
            }
        }

        Flickable {
            id: rolagem
            anchors { left: parent.left; right: parent.right; top: cabecalho.bottom; bottom: parent.bottom }
            contentWidth: width
            contentHeight: corpo.implicitHeight + 24
            clip: true
            interactive: contentHeight > height
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: BarraDeRolagem {}

            Column {
                id: corpo
                x: 24
                width: rolagem.width - 48
                spacing: 12

                // --- principal ---
                Column {
                    visible: dialogo.pagina === "principal"
                    width: parent.width
                    spacing: 6

                    Image {
                        anchors.horizontalCenter: parent.horizontalCenter
                        width: 96
                        height: 96
                        source: dialogo.modelo ? dialogo.modelo.icone : ""
                        sourceSize: Qt.size(192, 192)
                        fillMode: Image.PreserveAspectFit
                        Accessible.ignored: true
                    }
                    Text {
                        objectName: "nomeDoApp"
                        width: parent.width
                        horizontalAlignment: Text.AlignHCenter
                        text: "Cartridges"
                        textFormat: Text.PlainText
                        color: Tema.texto
                        font { family: Tema.fonte; pixelSize: 24; weight: Font.DemiBold }
                    }
                    Text {
                        objectName: "desenvolvedorDoApp"
                        width: parent.width
                        horizontalAlignment: Text.AlignHCenter
                        text: dialogo.modelo ? dialogo.modelo.desenvolvedor : ""
                        textFormat: Text.PlainText
                        color: Tema.textoSecundario
                        font { family: Tema.fonte; pixelSize: 14 }
                    }
                    Rectangle {
                        anchors.horizontalCenter: parent.horizontalCenter
                        width: selo.implicitWidth + 24
                        height: 26
                        radius: 13
                        color: Tema.botaoSobre
                        Text {
                            id: selo
                            objectName: "versaoDoApp"
                            anchors.centerIn: parent
                            text: dialogo.modelo ? dialogo.modelo.versao : ""
                            textFormat: Text.PlainText
                            color: Tema.texto
                            font { family: Tema.fonte; pixelSize: 13 }
                        }
                    }
                    Item { width: 1; height: 12 }
                    Column {
                        width: parent.width
                        LinhaDoSobre { id: linhaNovidades; objectName: "linhaNovidades"; destino: "novidades"; visible: !!dialogo.modelo && dialogo.modelo.temNovidades; height: visible ? implicitHeight : 0 }
                        LinhaDoSobre { id: linhaDetalhes; objectName: "linhaDetalhes"; destino: "detalhes" }
                        LinhaDoSobre { id: linhaCreditos; objectName: "linhaCreditos"; destino: "creditos" }
                        LinhaDoSobre { id: linhaLegal; objectName: "linhaLegal"; destino: "legal" }
                        LinhaDoSobre { id: linhaProblemas; objectName: "linhaProblemas"; destino: "problemas" }
                    }
                }

                // --- novidades da versão ---
                Column {
                    visible: dialogo.pagina === "novidades"
                    width: parent.width
                    spacing: 8

                    Text {
                        objectName: "cabecalhoDaVersao"
                        width: parent.width
                        text: "Versão " + (dialogo.modelo ? dialogo.modelo.versao : "")
                        textFormat: Text.PlainText
                        wrapMode: Text.Wrap
                        color: Tema.texto
                        font { family: Tema.fonte; pixelSize: 16; weight: Font.Bold }
                    }
                    Repeater {
                        model: dialogo.modelo ? dialogo.modelo.novidades : []
                        Row {
                            id: novidade
                            required property int index
                            required property var modelData
                            width: corpo.width
                            spacing: 8
                            Text {
                                id: marcador
                                visible: novidade.modelData.tipo === "li"
                                text: "•"
                                textFormat: Text.PlainText
                                color: Tema.texto
                                font { family: Tema.fonte; pixelSize: 14 }
                            }
                            Text {
                                objectName: "itemDeNovidade-" + novidade.index
                                width: novidade.width - (marcador.visible ? marcador.width + novidade.spacing : 0)
                                text: novidade.modelData.texto
                                textFormat: Text.PlainText
                                wrapMode: Text.Wrap
                                color: Tema.texto
                                font { family: Tema.fonte; pixelSize: 14 }
                            }
                        }
                    }
                }

                // --- detalhes ---
                Column {
                    visible: dialogo.pagina === "detalhes"
                    width: parent.width
                    spacing: 12

                    Repeater {
                        model: dialogo.modelo ? dialogo.modelo.detalhes : []
                        Text {
                            required property string modelData
                            width: corpo.width
                            text: modelData
                            textFormat: Text.PlainText
                            wrapMode: Text.Wrap
                            color: Tema.texto
                            font { family: Tema.fonte; pixelSize: 14 }
                        }
                    }
                }

                // --- créditos ---
                Column {
                    visible: dialogo.pagina === "creditos"
                    width: parent.width
                    spacing: 16

                    Repeater {
                        model: dialogo.modelo ? dialogo.modelo.creditos : []
                        Column {
                            id: secao
                            required property var modelData
                            width: corpo.width
                            spacing: 6
                            Text {
                                // Só a seção com título leva o nome; o título é uma frase e quebra a linha, sem "…".
                                objectName: secao.modelData.titulo !== "" ? "tituloDosAgradecimentos" : ""
                                visible: text !== ""
                                width: parent.width
                                text: secao.modelData.titulo
                                textFormat: Text.PlainText
                                wrapMode: Text.Wrap
                                elide: Text.ElideNone
                                color: Tema.texto
                                font { family: Tema.fonte; pixelSize: 14; weight: Font.DemiBold }
                            }
                            Repeater {
                                model: secao.modelData.nomes
                                Text {
                                    required property string modelData
                                    objectName: "nomeDoCredito-" + modelData
                                    width: secao.width
                                    text: modelData
                                    textFormat: Text.PlainText
                                    wrapMode: Text.Wrap
                                    color: Tema.textoSecundario
                                    font { family: Tema.fonte; pixelSize: 14 }
                                }
                            }
                        }
                    }
                }

                // --- aviso legal ---
                Column {
                    visible: dialogo.pagina === "legal"
                    width: parent.width
                    spacing: 16

                    Text {
                        objectName: "copyrightDoApp"
                        width: parent.width
                        text: dialogo.modelo ? dialogo.modelo.copyright : ""
                        textFormat: Text.PlainText
                        wrapMode: Text.Wrap
                        color: Tema.texto
                        font { family: Tema.fonte; pixelSize: 14 }
                    }
                    // shortcut: o link só abre com o mouse (um Text não o põe na ordem do Tab), quando houver mais de um link.
                    Text {
                        objectName: "licencaDoApp"
                        width: parent.width
                        text: dialogo.modelo ? dialogo.modelo.licenca : ""
                        textFormat: Text.StyledText
                        wrapMode: Text.Wrap
                        linkColor: Tema.destaque
                        color: Tema.texto
                        font { family: Tema.fonte; pixelSize: 14 }
                        onLinkActivated: link => dialogo.modelo.abrirLicenca(link)
                    }
                }

                // --- solução de problemas ---
                Column {
                    visible: dialogo.pagina === "problemas"
                    width: parent.width
                    spacing: 12

                    Text {
                        objectName: "textoDeSuporte"
                        width: parent.width
                        text: dialogo.modelo ? dialogo.modelo.textoDeSuporte : ""
                        textFormat: Text.PlainText
                        wrapMode: Text.Wrap
                        color: Tema.texto
                        font { family: Tema.fonte; pixelSize: 14 }
                    }
                    Text {
                        width: parent.width
                        text: "Informações de depuração"
                        textFormat: Text.PlainText
                        color: Tema.texto
                        font { family: Tema.fonte; pixelSize: 14; weight: Font.DemiBold }
                        Accessible.role: Accessible.Heading
                        Accessible.name: text
                    }
                    Rectangle {
                        width: parent.width
                        height: 220
                        radius: 6
                        color: Tema.superficie
                        border.color: Tema.borda
                        clip: true

                        Flickable {
                            id: logRolavel
                            objectName: "rolagemDaDepuracao"
                            anchors { fill: parent; margins: 8 }
                            contentWidth: width
                            contentHeight: depuracao.implicitHeight
                            clip: true
                            boundsBehavior: Flickable.StopAtBounds
                            activeFocusOnTab: true
                            Accessible.name: "Informações de depuração"
                            ScrollBar.vertical: BarraDeRolagem {}
                            function rolar(delta) {
                                contentY = Math.max(0, Math.min(contentHeight - height, contentY + delta))
                            }
                            Keys.onUpPressed: rolar(-40)
                            Keys.onDownPressed: rolar(40)
                            Keys.onPressed: event => {
                                if (event.key === Qt.Key_PageUp) { rolar(-height); event.accepted = true }
                                else if (event.key === Qt.Key_PageDown) { rolar(height); event.accepted = true }
                            }

                            Text {
                                id: depuracao
                                objectName: "textoDaDepuracao"
                                width: logRolavel.width - 12
                                text: dialogo.modelo ? dialogo.modelo.depuracao : ""
                                textFormat: Text.PlainText
                                wrapMode: Text.WrapAnywhere
                                color: Tema.texto
                                font { family: "Consolas"; pixelSize: 12 }
                            }
                        }
                    }
                    Row {
                        spacing: 8
                        BotaoDoSobre {
                            objectName: "botaoCopiarTexto"
                            text: "Copiar texto"
                            onClicked: dialogo.modelo.copiar()
                        }
                        BotaoDoSobre {
                            objectName: "botaoSalvarComo"
                            text: "Salvar como…"
                            onClicked: {
                                if (cargaDoSalvar.item) cargaDoSalvar.item.open(); else cargaDoSalvar.active = true
                            }
                        }
                    }
                }
            }
        }
    }
}
