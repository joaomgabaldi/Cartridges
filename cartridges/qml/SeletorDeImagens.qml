import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Effects
import QtQuick.Layouts

// O seletor de capa ou de logo do SteamGridDB: um campo de busca e uma grade de miniaturas (`Adw.Dialog` de 720x620).
// Só desenha: a busca, as miniaturas e o download são do `seletor` (cartridges/modelos/seletores.py).
// Modal para o mouse, o teclado e o controle (abre por cima do diálogo de edição, que fica desabilitado);
// o foco volta ao botão que o abriu.
SeletorBase {
    id: seletorDeImagens

    // O SeletorDoSgdb ou o SeletorDeLogo.
    property QtObject seletor
    // O botão do canto: "Animadas" (alterna) na capa, "Usar o título" (age) no logo.
    property string rotuloDoAtalho
    property string dicaDoAtalho
    property bool atalhoAlterna: false
    // O logo é um letreiro horizontal: células de 300x110, uma ou duas por linha. A capa tem 140x210, de duas a quatro.
    property bool horizontal: false

    readonly property int larguraDaCelula: horizontal ? 300 : 140
    readonly property int alturaDaCelula: horizontal ? 110 : 210
    readonly property int colunas: Math.max(horizontal ? 1 : 2,
        Math.min(horizontal ? 2 : 4, Math.floor((conteudo.width - 24 + 12) / (larguraDaCelula + 12))))

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

    // A seta numa célula leva o foco à vizinha; para cima da primeira linha, ao campo de busca.
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

        // Buscando e ainda sem nenhuma miniatura: o spinner central, até chegar a primeira.
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

        // A tela "Baixando…" da imagem escolhida.
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

            GridView {
                id: grade
                objectName: seletorDeImagens.objectName + "Grade"
                // `FlowBox homogeneous` centrado: células de largura fixa mais 12, o conjunto no meio.
                // Ocupa a largura toda (a barra de rolagem fica na borda); as colunas ficam centradas pela margem.
                anchors.fill: parent
                leftMargin: Math.max(0, (width - seletorDeImagens.colunas * cellWidth) / 2)
                topMargin: 6
                bottomMargin: 6
                model: seletorDeImagens.seletor
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                cellWidth: seletorDeImagens.larguraDaCelula + 12
                cellHeight: seletorDeImagens.alturaDaCelula + 12
                ScrollBar.vertical: BarraDeRolagem {}

                delegate: Item {
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
                        hoverEnabled: false  // `.no-hover`: a célula não reage ao mouse
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

                        // O contorno do foco é o da `flowboxchild`; o logo ganha o fundo escuro da página de destino
                        // (`.logo-preview`: preto a 55%, raio 12), porque a maioria dos logos é branca sobre transparência.
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
                            // A capa: cortada em raio 12, preenchendo a célula.
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
                                // As prévias animadas tocam todas, na cópia reduzida que o seletor pede.
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
                            // O logo: com 12 de folga, sem ampliar (`SCALE_DOWN`).
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
