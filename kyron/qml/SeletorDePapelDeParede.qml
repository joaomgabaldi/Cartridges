import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Effects
import QtQuick.Layouts

// O seletor do papel de parede da sessão: grade de candidatos do wallhaven já cortados no formato dos monitores e, depois da escolha, a barra que desliza a faixa de cada monitor.
SeletorBase {
    id: seletorDePapel

    property QtObject seletor

    readonly property int colunas: Math.max(1, Math.min(4, Math.floor((conteudo.width - 24 - 12) / (seletor.larguraDaCelula + 18))))

    aberto: seletor.aberto
    largura: 860
    altura: 700
    titulo: "Escolher papel de parede"
    placeholder: "Buscar no wallhaven…"
    nomeDaBusca: "Buscar no wallhaven"
    comBusca: !seletor.soArquivo
    rolado: grade.contentY > -grade.topMargin + 1
    // O primeiro foco do diálogo: "Não trocar" na grade do wallhaven; nada, com arquivo do disco; nada forçado depois.
    focoInicial: seletor.soArquivo ? null : botaoNaoTrocar
    onFecharPedido: seletor.fechar()
    onBuscaEditada: texto => seletor.busca = texto
    onBuscaConfirmada: seletor.buscarAgora()
    onSetaParaBaixo: moverFoco(0)

    Binding { target: seletorDePapel.campo; property: "text"; value: seletorDePapel.seletor.busca }

    function moverFoco(indice) {
        if (indice < 0) { campo.forceActiveFocus(Qt.BacktabFocusReason); return }
        if (indice >= grade.count) return
        grade.positionViewAtIndex(indice, GridView.Contain)
        var item = grade.itemAtIndex(indice)
        if (item) item.forceActiveFocus(Qt.TabFocusReason)
    }

    fim: [
        Botao {
            id: botaoNaoTrocar
            objectName: seletorDePapel.objectName + "NaoTrocar"
            visible: !seletorDePapel.seletor.soArquivo
            text: "Não trocar"
            dica: "Não alterar o papel de parede quando este jogo rodar"
            Accessible.name: dica
            onClicked: seletorDePapel.seletor.naoTrocar()
        }
    ]

    Item {
        id: conteudo
        Layout.fillWidth: true
        Layout.fillHeight: true

        PaginaDoSeletor {
            ativa: seletorDePapel.seletor.buscando && grade.count === 0 && !seletorDePapel.seletor.vazio
                && !seletorDePapel.seletor.baixando && !seletorDePapel.seletor.ajustando
            Girador {
                objectName: seletorDePapel.objectName + "Carregando"
                anchors.centerIn: parent
                width: 32
                height: 32
                running: parent.visible
            }
        }

        PaginaDoSeletor {
            ativa: seletorDePapel.seletor.vazio
            EstadoVazio {
                objectName: seletorDePapel.objectName + "Vazio"
                anchors.fill: parent
                icone: "image-x-generic"
                titulo: seletorDePapel.seletor.tituloDoEstado
                descricao: seletorDePapel.seletor.descricaoDoEstado
            }
        }

        PaginaDoSeletor {
            ativa: seletorDePapel.seletor.baixando
            TelaDeDownload {
                objectName: seletorDePapel.objectName + "Baixando"
                anchors.centerIn: parent
                progresso: seletorDePapel.seletor.progresso
                texto: seletorDePapel.seletor.textoDoProgresso
            }
        }

        PaginaDoSeletor {
            ativa: !seletorDePapel.seletor.vazio && !seletorDePapel.seletor.baixando && !seletorDePapel.seletor.ajustando
                && !seletorDePapel.seletor.soArquivo && grade.count > 0

            // As laterais e a barra também rolam com a roda, no passo do `GridView` (linhas * 24); sobre a grade, o limite anula o giro na ponta.
            WheelHandler {
                acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
                onWheel: event => grade.contentY = Math.max(-grade.topMargin, Math.min(grade.contentHeight - grade.height + grade.bottomMargin,
                    grade.contentY - event.angleDelta.y / 120 * Qt.styleHints.wheelScrollLines * 24))
            }

            GridView {
                id: grade
                objectName: seletorDePapel.objectName + "Grade"
                width: seletorDePapel.colunas * cellWidth
                height: parent.height
                anchors.horizontalCenter: parent.horizontalCenter
                topMargin: 6
                bottomMargin: 6
                model: seletorDePapel.seletor
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                cellWidth: seletorDePapel.seletor.larguraDaCelula + 18
                cellHeight: seletorDePapel.seletor.alturaDaCelula + 18
                ScrollBar.vertical: BarraDeRolagem {
                    objectName: seletorDePapel.objectName + "Rolagem"
                    parent: grade.parent
                    anchors.top: parent.top
                    anchors.bottom: parent.bottom
                    anchors.right: parent.right
                }

                // `FocusScope`: o foco que `moverFoco` dá à célula desce ao botão, com o anel e o Enter.
                delegate: FocusScope {
                    id: celula
                    required property int index
                    required property string miniatura
                    width: grade.cellWidth
                    height: grade.cellHeight

                    Button {
                        id: botao
                        objectName: seletorDePapel.objectName + "Miniatura" + celula.index
                        anchors.centerIn: parent
                        width: seletorDePapel.seletor.larguraDaCelula
                        height: seletorDePapel.seletor.alturaDaCelula
                        padding: 0
                        hoverEnabled: false
                        focus: true
                        focusPolicy: Qt.StrongFocus
                        Accessible.name: "Papel de parede " + (celula.index + 1)
                        Accessible.role: Accessible.Button
                        Keys.onReturnPressed: click()
                        Keys.onEnterPressed: click()
                        Keys.onRightPressed: seletorDePapel.moverFoco(celula.index + 1)
                        Keys.onLeftPressed: seletorDePapel.moverFoco(celula.index - 1)
                        Keys.onDownPressed: seletorDePapel.moverFoco(celula.index + seletorDePapel.colunas)
                        Keys.onUpPressed: seletorDePapel.moverFoco(celula.index - seletorDePapel.colunas)
                        onClicked: seletorDePapel.seletor.escolher(celula.index)

                        background: Item { AnelDeFoco { ativo: botao.visualFocus; raio: 8; afastamento: 0 } }
                        contentItem: Item {
                            Item {
                                id: mascara
                                anchors.fill: parent
                                visible: false
                                layer.enabled: true
                                Rectangle { anchors.fill: parent; radius: 8 }
                            }
                            Image {
                                anchors.fill: parent
                                source: celula.miniatura
                                fillMode: Image.PreserveAspectCrop
                                asynchronous: true
                                cache: false
                                layer.enabled: true
                                layer.effect: MultiEffect {
                                    maskEnabled: true
                                    maskSource: mascara
                                    maskThresholdMin: 0.5
                                    maskSpreadAtMin: 1.0
                                }
                            }
                        }
                    }
                }
            }
        }

        // A segunda etapa: um corte por orientação dos monitores, cada um com a sua barra.
        PaginaDoSeletor {
            id: ajuste
            objectName: seletorDePapel.objectName + "Ajuste"
            ativa: seletorDePapel.seletor.ajustando

            Column {
                anchors.centerIn: parent
                spacing: 12

                Row {
                    anchors.horizontalCenter: parent.horizontalCenter
                    spacing: 12
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
                            spacing: 12

                            Image {
                                objectName: seletorDePapel.objectName + "Previa" + corte.index
                                anchors.horizontalCenter: parent.horizontalCenter
                                width: corte.larguraDaPrevia
                                height: corte.alturaDaPrevia
                                source: corte.previa
                                fillMode: Image.PreserveAspectFit
                                cache: false
                            }
                            Text {
                                width: corte.larguraDaPrevia
                                visible: corte.desliza
                                text: corte.dica
                                textFormat: Text.PlainText
                                wrapMode: Text.WordWrap
                                horizontalAlignment: Text.AlignHCenter
                                color: Tema.textoSecundario
                                font { family: Tema.fonte; pixelSize: Tema.legenda }
                            }
                            // O controle deslizante: calha de 10, trecho andado na cor de destaque e marcador branco de 20 com contorno e sombra.
                            Slider {
                                id: barra
                                objectName: seletorDePapel.objectName + "Barra" + corte.index
                                width: corte.larguraDaPrevia
                                visible: corte.desliza
                                from: 0
                                to: 100
                                stepSize: 1
                                value: corte.posicao
                                hoverEnabled: true
                                focusPolicy: Qt.StrongFocus
                                padding: 12
                                Accessible.name: corte.dica
                                onMoved: seletorDePapel.seletor.definirPosicao(corte.index, value)
                                background: Rectangle {
                                    x: barra.leftPadding
                                    y: barra.topPadding + barra.availableHeight / 2 - height / 2
                                    width: barra.availableWidth
                                    height: 10
                                    radius: 5
                                    color: Tema.mistura(barra.hovered || barra.pressed ? 0.20 : 0.15)
                                    Rectangle { width: barra.visualPosition * parent.width; height: parent.height; radius: 5; color: Tema.destaque }
                                }
                                handle: Rectangle {
                                    x: barra.leftPadding + barra.visualPosition * (barra.availableWidth - width)
                                    y: barra.topPadding + barra.availableHeight / 2 - height / 2
                                    width: 20
                                    height: 20
                                    radius: 10
                                    color: Qt.tint("#1d1d20", Qt.rgba(1, 1, 1, 0.8))
                                    Sombra { camadas: [[0, 0, 1, 0, 0, 6 / 255, 0.10], [2, 4, 0, 0, 0, 6 / 255, 0.20]]; raio: 10 }
                                    AnelDeFoco { ativo: barra.visualFocus; raio: 10; afastamento: 0 }
                                }
                            }
                        }
                    }
                }

                Row {
                    anchors.horizontalCenter: parent.horizontalCenter
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
                        estilo: "sugestao"
                        text: "Usar esta imagem"
                        onClicked: seletorDePapel.seletor.usarEstaImagem()
                    }
                }
            }
        }
    }
}
