import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Effects
import QtQuick.Layouts

// O seletor de capa ou de logo do SteamGridDB: só desenha; a busca, as miniaturas e o download são do `seletor`.
SeletorBase {
    id: seletorDeImagens

    property QtObject seletor
    property string rotuloDoAtalho
    property string dicaDoAtalho
    property bool atalhoAlterna: false
    // Logo: células de 323x110, uma ou duas por linha. Capa: 200x210, de duas a quatro.
    property bool horizontal: false

    readonly property int larguraDaCelula: horizontal ? 323 : Math.max(140, Math.min(200, Math.floor((conteudo.width - 36) / 2)))
    readonly property int alturaDaCelula: horizontal ? 110 : 210
    readonly property int colunas: Math.max(horizontal ? 1 : 2,
        Math.min(horizontal ? 2 : 4, Math.floor((conteudo.width - 24 + 12) / ((horizontal ? 323 : 200) + 12))))

    signal atalhoClicado()

    aberto: seletor.aberto
    largura: 720
    altura: 620
    placeholder: "Buscar jogo…"
    rolado: grade.contentY > -grade.topMargin + 1
    focoInicial: botaoDoAtalho.enabled ? botaoDoAtalho : campo
    onFecharPedido: seletor.fechar()
    onBuscaEditada: texto => seletor.busca = texto
    onBuscaConfirmada: seletor.buscarAgora()
    onSetaParaBaixo: moverFoco(0)

    Binding { target: seletorDeImagens.campo; property: "text"; value: seletorDeImagens.seletor.busca }

    function moverFoco(indice) {
        if (indice < 0) { campo.forceActiveFocus(Qt.BacktabFocusReason); return }
        if (indice >= grade.count) return
        grade.positionViewAtIndex(indice, GridView.Contain)
        var item = grade.itemAtIndex(indice)
        if (item) item.forceActiveFocus(Qt.TabFocusReason)
    }

    fim: [
        Botao {
            id: botaoDoAtalho
            objectName: seletorDeImagens.objectName + "Atalho"
            text: seletorDeImagens.rotuloDoAtalho
            checkable: seletorDeImagens.atalhoAlterna
            checked: seletorDeImagens.atalhoAlterna && seletorDeImagens.seletor.animadas
            dica: seletorDeImagens.dicaDoAtalho
            Accessible.name: dica
            onClicked: seletorDeImagens.atalhoClicado()
        }
    ]

    Item {
        id: conteudo
        Layout.fillWidth: true
        Layout.fillHeight: true

        PaginaDoSeletor {
            ativa: seletorDeImagens.seletor.buscando && grade.count === 0 && !seletorDeImagens.seletor.vazio
            Girador {
                objectName: seletorDeImagens.objectName + "Carregando"
                anchors.centerIn: parent
                width: 32
                height: 32
                running: parent.visible
            }
        }

        PaginaDoSeletor {
            ativa: seletorDeImagens.seletor.vazio
            EstadoVazio {
                objectName: seletorDeImagens.objectName + "Vazio"
                anchors.fill: parent
                icone: "image-x-generic"
                titulo: seletorDeImagens.seletor.tituloDoEstado
                descricao: seletorDeImagens.seletor.descricaoDoEstado
            }
        }

        PaginaDoSeletor {
            ativa: seletorDeImagens.seletor.baixando
            TelaDeDownload {
                objectName: seletorDeImagens.objectName + "Baixando"
                anchors.centerIn: parent
                progresso: seletorDeImagens.seletor.progresso
                texto: seletorDeImagens.seletor.textoDoProgresso
                nomeDaBarra: seletorDeImagens.objectName + "Barra"
            }
        }

        PaginaDoSeletor {
            ativa: !seletorDeImagens.seletor.vazio && !seletorDeImagens.seletor.baixando && grade.count > 0

            // As laterais e a barra também rolam com a roda, no passo do `GridView` (linhas * 24); sobre a grade, o limite anula o giro na ponta.
            WheelHandler {
                acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
                onWheel: event => grade.contentY = Math.max(-grade.topMargin, Math.min(grade.contentHeight - grade.height + grade.bottomMargin,
                    grade.contentY - event.angleDelta.y / 120 * Qt.styleHints.wheelScrollLines * 24))
            }

            GridView {
                id: grade
                objectName: seletorDeImagens.objectName + "Grade"
                width: seletorDeImagens.colunas * cellWidth
                height: parent.height
                anchors.horizontalCenter: parent.horizontalCenter
                topMargin: 6
                bottomMargin: 6
                model: seletorDeImagens.seletor
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                cellWidth: seletorDeImagens.larguraDaCelula + 12
                cellHeight: seletorDeImagens.alturaDaCelula + 12
                ScrollBar.vertical: BarraDeRolagem {
                    objectName: seletorDeImagens.objectName + "Rolagem"
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
                    required property bool animada
                    required property string copiaAnimada
                    width: grade.cellWidth
                    height: grade.cellHeight

                    Button {
                        id: botao
                        objectName: seletorDeImagens.objectName + "Miniatura" + celula.index
                        anchors.centerIn: parent
                        width: seletorDeImagens.larguraDaCelula
                        height: seletorDeImagens.alturaDaCelula
                        padding: 0
                        hoverEnabled: false
                        focus: true
                        focusPolicy: Qt.StrongFocus
                        Accessible.name: "Miniatura " + (celula.index + 1)
                        Accessible.role: Accessible.Button
                        Keys.onReturnPressed: click()
                        Keys.onEnterPressed: click()
                        Keys.onRightPressed: seletorDeImagens.moverFoco(celula.index + 1)
                        Keys.onLeftPressed: seletorDeImagens.moverFoco(celula.index - 1)
                        Keys.onDownPressed: seletorDeImagens.moverFoco(celula.index + seletorDeImagens.colunas)
                        Keys.onUpPressed: seletorDeImagens.moverFoco(celula.index - seletorDeImagens.colunas)
                        onClicked: seletorDeImagens.seletor.escolher(celula.index)

                        // O logo ganha fundo escuro (preto a 55%, raio 12): a maioria dos logos é branca sobre transparência.
                        background: Item {
                            Sombra { visible: !seletorDeImagens.horizontal; camadas: Tema.sombraCartao; raio: 12 }
                            Rectangle {
                                anchors.fill: parent
                                visible: seletorDeImagens.horizontal
                                radius: 12
                                color: Qt.rgba(0, 0, 0, 0.55)
                            }
                            AnelDeFoco { ativo: botao.visualFocus; raio: 12; afastamento: 0 }
                        }
                        contentItem: Item {
                            Item {
                                id: mascara
                                anchors.fill: parent
                                visible: false
                                layer.enabled: true
                                Rectangle { anchors.fill: parent; radius: 12 }
                            }
                            Item {
                                anchors.fill: parent
                                visible: !seletorDeImagens.horizontal
                                layer.enabled: visible
                                layer.effect: MultiEffect {
                                    maskEnabled: true
                                    maskSource: mascara
                                    maskThresholdMin: 0.5
                                    maskSpreadAtMin: 1.0
                                }
                                Image {
                                    anchors.fill: parent
                                    source: celula.miniatura
                                    sourceSize.width: seletorDeImagens.larguraDaCelula * 2
                                    sourceSize.height: seletorDeImagens.alturaDaCelula * 2
                                    fillMode: Image.PreserveAspectCrop
                                    asynchronous: true
                                    cache: false
                                }
                                Loader {
                                    anchors.fill: parent
                                    // Só a cópia reduzida toca; a original (até 200 MB) fica só como primeiro quadro.
                                    active: celula.animada && celula.copiaAnimada !== ""
                                    sourceComponent: AnimatedImage {
                                        source: celula.copiaAnimada
                                        fillMode: Image.PreserveAspectCrop
                                        cache: false
                                    }
                                }
                            }
                            Image {
                                anchors.centerIn: parent
                                visible: seletorDeImagens.horizontal
                                // Decodifica no máximo o dobro da célula (sem ampliar o que é menor).
                                sourceSize: Qt.size(seletorDeImagens.larguraDaCelula * 2, seletorDeImagens.alturaDaCelula * 2)
                                width: Math.min(implicitWidth, parent.width - 24)
                                height: Math.min(implicitHeight, parent.height - 24)
                                source: seletorDeImagens.horizontal ? celula.miniatura : ""
                                fillMode: Image.PreserveAspectFit
                                asynchronous: true
                                cache: false
                            }
                        }
                    }
                }
            }
        }
    }
}
