import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// "Adicionar a Jogos Zerados": busca na Steam e lista dos desinstalados (ou dos resultados). Nome de jogo e aviso, texto de terceiros, em PlainText.
SeletorBase {
    id: seletor
    objectName: "seletorDeZerados"
    prefixoDosObjetos: "zerados"

    property QtObject modelo

    aberto: !!modelo && modelo.aberto
    largura: 460
    altura: 520
    titulo: "Adicionar a Jogos Zerados"
    placeholder: "Buscar na Steam"
    nomeDaBusca: "Buscar na Steam"
    larguraDoCampo: 10000
    margemDoCampo: 12
    rolado: lista.contentY > 0
    onFecharPedido: modelo.fechar()
    // A busca na Steam só começa com Enter (a loja limita as requisições); apagar o campo volta aos desinstalados.
    onBuscaEditada: texto => modelo.mudouBusca(texto)
    onBuscaConfirmada: modelo.buscar(campo.text)
    onSetaParaBaixo: moverFoco(0)
    onAbertoChanged: if (aberto) campo.text = ""

    // A seta numa linha leva o foco à vizinha ativa (a que já está na lista fica fora do foco); para cima da primeira, ao campo.
    function moverFoco(indice, passo) {
        passo = passo === undefined ? 1 : passo
        while (indice >= 0 && indice < linhas.count && !linhas.itemAt(indice).enabled) indice += passo
        if (indice < 0) { campo.forceActiveFocus(Qt.BacktabFocusReason); return }
        var linha = linhas.itemAt(indice)
        if (!linha) return
        var topo = linha.mapToItem(lista.contentItem, 0, 0).y
        if (topo < lista.contentY) lista.contentY = Math.max(0, topo - 12)
        else if (topo + linha.height > lista.contentY + lista.height) lista.contentY = topo + linha.height - lista.height + 12
        linha.botaoDaLinha.forceActiveFocus(Qt.TabFocusReason)
    }

    Item {
        Layout.fillWidth: true
        Layout.fillHeight: true

        PaginaDoSeletor {
            ativa: !!seletor.modelo && seletor.modelo.estado === "carregando"
            Girador {
                objectName: "zeradosCarregando"
                anchors.centerIn: parent
                width: 32
                height: 32
                running: parent.visible
            }
        }

        PaginaDoSeletor {
            ativa: !!seletor.modelo && seletor.modelo.estado === "vazio"
            EstadoVazio {
                objectName: "zeradosVazio"
                anchors.fill: parent
                icone: "object-select"
                titulo: "Nenhum jogo disponível"
                descricao: "Busque um jogo na Steam para adicioná-lo."
            }
        }

        PaginaDoSeletor {
            ativa: !!seletor.modelo && seletor.modelo.estado === "lista"

            Flickable {
                id: lista
                objectName: "zeradosLista"
                anchors.fill: parent
                contentWidth: width
                contentHeight: conteudoDaLista.height + 24
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: BarraDeRolagem {}
                RolagemPorMola { alvo: lista; ativa: Tema.animacoes }

                Column {
                    id: conteudoDaLista
                    x: (lista.width - width) / 2
                    y: 12
                    width: Math.min(600, lista.width - 24)

                    Text {
                        objectName: "zeradosAviso"
                        width: parent.width
                        visible: !!seletor.modelo && seletor.modelo.aviso !== ""
                        height: visible ? implicitHeight + 12 : 0
                        text: seletor.modelo ? seletor.modelo.aviso : ""
                        textFormat: Text.PlainText
                        wrapMode: Text.Wrap
                        color: Tema.textoSecundario
                        font { family: Tema.fonte; pixelSize: Tema.corpo }
                    }
                    GrupoDeLinhas {
                        width: parent.width

                        Repeater {
                            id: linhas
                            model: seletor.modelo ? seletor.modelo.linhas : []
                            delegate: LinhaDeAcao {
                                id: linha
                                required property int index
                                required property var modelData
                                objectName: "zeradosLinha" + index
                                titulo: modelData.titulo
                                subtitulo: modelData.subtitulo
                                icone: modelData.ativa ? "list-add" : ""
                                enabled: modelData.ativa
                                Accessible.description: modelData.subtitulo
                                Keys.onDownPressed: seletor.moverFoco(index + 1, 1)
                                Keys.onUpPressed: seletor.moverFoco(index - 1, -1)
                                onAcionada: seletor.modelo.escolher(modelData.chave)
                            }
                        }
                    }
                }
            }
        }
    }
}
