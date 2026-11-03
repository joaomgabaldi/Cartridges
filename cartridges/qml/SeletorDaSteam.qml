import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// O seletor do jogo da Steam: um campo de busca e a lista de candidatos da loja (`Adw.Dialog` de 560x520, a lista num
// `boxed-list` de até 500). Só desenha: a busca e a escolha são do `seletor` (SeletorDaSteam, cartridges/modelos/seletores.py).
// Modal para o mouse, o teclado e o controle (abre por cima do diálogo de edição, que fica desabilitado);
// o foco volta ao botão que o abriu.
SeletorBase {
    id: seletorDaSteam

    property QtObject seletor

    aberto: seletor.aberto
    largura: 560
    altura: 520
    titulo: "Escolher jogo na Steam"
    placeholder: "Buscar jogo…"
    rolado: lista.contentY > 0
    onFecharPedido: seletor.fechar()
    onBuscaEditada: texto => seletor.busca = texto
    onBuscaConfirmada: seletor.buscarAgora()
    onSetaParaBaixo: moverFoco(0)

    Binding { target: seletorDaSteam.campo; property: "text"; value: seletorDaSteam.seletor.busca }

    // A seta numa linha leva o foco à vizinha; para cima da primeira, ao campo de busca.
    function moverFoco(indice) {
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
            ativa: seletorDaSteam.seletor.buscando && !seletorDaSteam.seletor.vazio
            Girador {
                objectName: seletorDaSteam.objectName + "Carregando"
                anchors.centerIn: parent
                width: 32
                height: 32
                running: parent.visible
            }
        }

        PaginaDoSeletor {
            ativa: seletorDaSteam.seletor.vazio
            EstadoVazio {
                objectName: seletorDaSteam.objectName + "Vazio"
                anchors.fill: parent
                icone: "system-search"
                titulo: seletorDaSteam.seletor.tituloDoEstado
                descricao: seletorDaSteam.seletor.descricaoDoEstado
            }
        }

        PaginaDoSeletor {
            ativa: !seletorDaSteam.seletor.vazio && !seletorDaSteam.seletor.buscando

            Flickable {
                id: lista
                objectName: seletorDaSteam.objectName + "Lista"
                anchors.fill: parent
                contentWidth: width
                contentHeight: grupo.height + 24
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                RolagemDaRoda { alvo: lista }
                ScrollBar.vertical: BarraDeRolagem {}

                // `Adw.Clamp` de 500 com 12 de margem: a `boxed-list` contínua, as linhas coladas com separador.
                GrupoDeLinhas {
                    id: grupo
                    x: (lista.width - width) / 2
                    y: 12
                    width: Math.min(500, lista.width - 24)

                    Repeater {
                        id: linhas
                        model: seletorDaSteam.seletor
                        delegate: LinhaDeAcao {
                            id: linha
                            required property int index
                            required property string nome
                            required property string appid
                            required property string ano
                            objectName: seletorDaSteam.objectName + "Linha" + index
                            titulo: nome
                            subtitulo: "ID na Steam: " + appid + (ano !== "" ? " (" + ano + ")" : "")
                            icone: "go-next"
                            dica: ""
                            Accessible.description: "ID na Steam: " + appid
                            Keys.onDownPressed: seletorDaSteam.moverFoco(index + 1)
                            Keys.onUpPressed: seletorDaSteam.moverFoco(index - 1)
                            onAcionada: seletorDaSteam.seletor.escolher(index)
                        }
                    }
                }
            }
        }
    }
}
