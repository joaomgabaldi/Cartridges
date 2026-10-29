import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Window

// O seletor do papel de parede da sessão: uma grade de candidatos do wallhaven já cortados no formato dos monitores
// e, depois da escolha, a barra que desliza a faixa de cada monitor.
// Só desenha: a busca, os cortes e o download são do `seletor` (SeletorDePapelDeParede, cartridges/modelos/seletores.py).
// Modal para o mouse, o teclado e o controle (abre por cima do diálogo de edição, que fica desabilitado);
// o foco volta ao botão que o abriu. Esc fecha o seletor inteiro, como na versão anterior.
Rectangle {
    id: seletorDePapel

    property QtObject seletor

    readonly property int colunas: Math.max(2, Math.floor(grade.width / (seletor.larguraDaCelula + 12)))

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
            focarInicio()
        } else {
            // Depois de o diálogo de trás voltar a ficar habilitado.
            Qt.callLater(devolverAoRetorno)
        }
    }
    function focarInicio() {
        if (seletor.soArquivo) botaoFechar.forceActiveFocus(Qt.TabFocusReason)
        else campoDeBusca.forceActiveFocus(Qt.TabFocusReason)
    }
    function devolverAoRetorno() {
        if (visible) return
        if (retorno && retorno.visible && retorno.enabled) retorno.forceActiveFocus(Qt.TabFocusReason)
        else seletorDePapel.retornoPerdido()
    }
    // Na segunda etapa o foco vai ao botão de confirmar; na volta à grade, ao início.
    Connections {
        target: seletorDePapel.seletor
        function onAjustandoChanged() {
            if (!seletorDePapel.visible) return
            if (seletorDePapel.seletor.ajustando) botaoUsar.forceActiveFocus(Qt.TabFocusReason)
            else seletorDePapel.focarInicio()
        }
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

        component Botao: Button {
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

        // O cabeçalho vem primeiro: a ordem do Tab é "Fechar", "Não trocar", o campo e as miniaturas.
        Rectangle {
            id: cabecalho
            anchors { left: parent.left; right: parent.right; top: parent.top }
            height: 56
            color: Tema.fundo

            Botao {
                id: botaoFechar
                objectName: seletorDePapel.objectName + "Fechar"
                anchors { left: parent.left; leftMargin: 12; verticalCenter: parent.verticalCenter }
                text: "Fechar"
                onClicked: seletorDePapel.seletor.fechar()
            }
            Text {
                objectName: seletorDePapel.objectName + "Titulo"
                anchors { left: botaoFechar.right; right: botaoNaoTrocar.left; leftMargin: 8; rightMargin: 8; verticalCenter: parent.verticalCenter }
                text: "Escolher papel de parede"
                textFormat: Text.PlainText
                horizontalAlignment: Text.AlignHCenter
                elide: Text.ElideRight
                color: Tema.texto
                font { family: Tema.fonte; pixelSize: 16; weight: Font.DemiBold }
                Accessible.role: Accessible.Heading
                Accessible.name: text
            }
            // Um arquivo do disco não tem o que "não trocar": só a grade do wallhaven oferece a escolha.
            Botao {
                id: botaoNaoTrocar
                objectName: seletorDePapel.objectName + "NaoTrocar"
                anchors { right: parent.right; rightMargin: 12; verticalCenter: parent.verticalCenter }
                visible: !seletorDePapel.seletor.soArquivo
                width: visible ? implicitWidth : 0
                text: "Não trocar"
                enabled: !seletorDePapel.seletor.baixando && !seletorDePapel.seletor.ajustando
                dica: "Não alterar o papel de parede quando este jogo rodar"
                Accessible.name: dica
                onClicked: seletorDePapel.seletor.naoTrocar()
            }
        }

        Rectangle {
            id: campo
            anchors { left: parent.left; right: parent.right; top: cabecalho.bottom; margins: 12; topMargin: 0 }
            height: seletorDePapel.seletor.soArquivo ? 0 : 40
            visible: !seletorDePapel.seletor.soArquivo
            radius: 8
            color: Tema.superficie
            border { width: campoDeBusca.activeFocus ? 2 : 1; color: campoDeBusca.activeFocus ? Tema.destaque : Tema.borda }
            enabled: !seletorDePapel.seletor.baixando && !seletorDePapel.seletor.ajustando
            opacity: enabled ? 1 : 0.5

            TextField {
                id: campoDeBusca
                objectName: seletorDePapel.objectName + "Campo"
                anchors { fill: parent; leftMargin: 12; rightMargin: 12 }
                selectByMouse: true
                placeholderText: "Buscar no wallhaven…"
                placeholderTextColor: Tema.textoSecundario
                color: Tema.texto
                selectionColor: Tema.destaque
                selectedTextColor: "white"
                font { family: Tema.fonte; pixelSize: 15 }
                background: null
                verticalAlignment: TextInput.AlignVCenter
                text: seletorDePapel.seletor.busca
                Accessible.name: "Buscar no wallhaven"
                onTextEdited: seletorDePapel.seletor.busca = text
                onAccepted: seletorDePapel.seletor.buscarAgora()
                Keys.onDownPressed: seletorDePapel.moverFoco(0)
            }
        }

        Item {
            id: conteudo
            anchors { left: parent.left; right: parent.right; top: campo.bottom; bottom: parent.bottom; topMargin: 8 }

            // Buscando e ainda sem nenhuma miniatura (ou abrindo um arquivo).
            BusyIndicator {
                objectName: seletorDePapel.objectName + "Carregando"
                anchors.centerIn: parent
                width: 32
                height: 32
                running: visible
                visible: seletorDePapel.seletor.buscando && grade.count === 0 && !seletorDePapel.seletor.vazio
            }

            EstadoVazio {
                objectName: seletorDePapel.objectName + "Vazio"
                anchors.fill: parent
                visible: seletorDePapel.seletor.vazio
                glifo: ""  // imagem
                titulo: seletorDePapel.seletor.tituloDoEstado
                descricao: seletorDePapel.seletor.descricaoDoEstado
            }

            // A tela "Baixando…" da imagem escolhida.
            Column {
                objectName: seletorDePapel.objectName + "Baixando"
                anchors.centerIn: parent
                width: Math.min(parent.width - 48, 320)
                spacing: 10
                visible: seletorDePapel.seletor.baixando
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
                    indeterminate: seletorDePapel.seletor.progresso < 0 || seletorDePapel.seletor.textoDoProgresso === ""
                    value: Math.max(0, seletorDePapel.seletor.progresso)
                }
                Text {
                    width: parent.width
                    text: seletorDePapel.seletor.textoDoProgresso
                    textFormat: Text.PlainText
                    horizontalAlignment: Text.AlignHCenter
                    color: Tema.textoSecundario
                    font { family: Tema.fonte; pixelSize: 13 }
                }
            }

            GridView {
                id: grade
                objectName: seletorDePapel.objectName + "Grade"
                anchors { fill: parent; leftMargin: 12; rightMargin: 12 }
                visible: !seletorDePapel.seletor.vazio && !seletorDePapel.seletor.baixando && !seletorDePapel.seletor.ajustando
                    && !seletorDePapel.seletor.soArquivo
                model: seletorDePapel.seletor
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                cellWidth: Math.floor(width / seletorDePapel.colunas)
                cellHeight: seletorDePapel.seletor.alturaDaCelula + 12
                ScrollBar.vertical: BarraDeRolagem {}

                delegate: Item {
                    id: celula
                    required property int index
                    required property string miniatura
                    required property bool carregando
                    width: grade.cellWidth
                    height: grade.cellHeight

                    Button {
                        id: botao
                        objectName: seletorDePapel.objectName + "Miniatura" + celula.index
                        anchors.centerIn: parent
                        width: seletorDePapel.seletor.larguraDaCelula
                        height: seletorDePapel.seletor.alturaDaCelula
                        padding: 0
                        focusPolicy: Qt.StrongFocus
                        enabled: !celula.carregando
                        Accessible.name: "Papel de parede " + (celula.index + 1)
                        Accessible.role: Accessible.Button
                        Keys.onReturnPressed: click()
                        Keys.onEnterPressed: click()
                        Keys.onRightPressed: seletorDePapel.moverFoco(celula.index + 1)
                        Keys.onLeftPressed: seletorDePapel.moverFoco(celula.index - 1)
                        Keys.onDownPressed: seletorDePapel.moverFoco(celula.index + seletorDePapel.colunas)
                        Keys.onUpPressed: seletorDePapel.moverFoco(celula.index - seletorDePapel.colunas)
                        onClicked: seletorDePapel.seletor.escolher(celula.index)

                        background: Rectangle {
                            radius: 8
                            color: Tema.superficie
                            border { width: botao.visualFocus ? 3 : botao.hovered ? 2 : 1; color: botao.visualFocus || botao.hovered ? Tema.destaque : Tema.borda }
                        }
                        // A miniatura já vem cortada no formato do monitor (a mesma `enquadrar` do arquivo final).
                        contentItem: Item {
                            clip: true
                            Image {
                                anchors.fill: parent
                                anchors.margins: 1
                                source: celula.miniatura
                                fillMode: Image.PreserveAspectCrop
                                asynchronous: true
                                cache: false
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

            // A segunda etapa: um corte por orientação dos monitores, cada um com a sua barra.
            Item {
                id: ajuste
                objectName: seletorDePapel.objectName + "Ajuste"
                anchors { fill: parent; bottomMargin: 64 }
                visible: seletorDePapel.seletor.ajustando

                Row {
                    anchors.centerIn: parent
                    spacing: 24
                    Repeater {
                        model: seletorDePapel.seletor.cortes
                        delegate: Column {
                            id: corte
                            required property int index
                            required property string previa
                            required property real posicao
                            required property bool desliza
                            required property string dica
                            required property int larguraDaPrevia
                            required property int alturaDaPrevia
                            required property string orientacao
                            spacing: 10

                            Image {
                                objectName: seletorDePapel.objectName + "Previa" + corte.index
                                width: corte.larguraDaPrevia
                                height: corte.alturaDaPrevia
                                source: corte.previa
                                fillMode: Image.PreserveAspectFit
                                cache: false
                                Rectangle { anchors.fill: parent; color: "transparent"; border { width: 1; color: Tema.borda } }
                            }
                            Text {
                                width: corte.larguraDaPrevia
                                visible: corte.desliza
                                text: corte.dica
                                textFormat: Text.PlainText
                                wrapMode: Text.WordWrap
                                horizontalAlignment: Text.AlignHCenter
                                color: Tema.textoSecundario
                                font { family: Tema.fonte; pixelSize: 13 }
                            }
                            Slider {
                                id: barra
                                objectName: seletorDePapel.objectName + "Barra" + corte.index
                                width: corte.larguraDaPrevia
                                visible: corte.desliza
                                from: 0
                                to: 100
                                stepSize: 1
                                value: corte.posicao
                                focusPolicy: Qt.StrongFocus
                                Accessible.name: corte.dica
                                onMoved: seletorDePapel.seletor.definirPosicao(corte.index, value)
                                background: Rectangle {
                                    x: barra.leftPadding
                                    y: barra.topPadding + barra.availableHeight / 2 - height / 2
                                    width: barra.availableWidth
                                    height: 4
                                    radius: 2
                                    color: Tema.borda
                                    Rectangle { width: barra.visualPosition * parent.width; height: parent.height; radius: 2; color: Tema.destaque }
                                }
                                handle: Rectangle {
                                    x: barra.leftPadding + barra.visualPosition * (barra.availableWidth - width)
                                    y: barra.topPadding + barra.availableHeight / 2 - height / 2
                                    width: 18
                                    height: 18
                                    radius: 9
                                    color: Tema.destaque
                                    border { width: barra.visualFocus ? 3 : 1; color: barra.visualFocus ? Tema.texto : Tema.borda }
                                }
                            }
                        }
                    }
                }

                Row {
                    anchors { horizontalCenter: parent.horizontalCenter; top: parent.bottom; topMargin: 14 }
                    spacing: 12
                    Botao {
                        id: botaoVoltar
                        objectName: seletorDePapel.objectName + "Voltar"
                        text: "Voltar"
                        onClicked: seletorDePapel.seletor.voltar()
                    }
                    Botao {
                        id: botaoUsar
                        objectName: seletorDePapel.objectName + "Usar"
                        text: "Usar esta imagem"
                        cor: Tema.destaque
                        corDoTexto: "white"
                        onClicked: seletorDePapel.seletor.usarEstaImagem()
                    }
                }
            }
        }
    }
}
