import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// O seletor do jogo do Ludusavi: só desenha; a leitura da lista e o filtro são do `seletor`.
SeletorBase {
    id: seletorDoLudusavi

    property QtObject seletor

    aberto: seletor.aberto
    largura: 480
    altura: 560
    titulo: "Jogo no Ludusavi"
    placeholder: "Buscar jogo"
    larguraDoCampo: 10000
    margemDoCampo: 12
    onFecharPedido: seletor.fechar()
    onBuscaEditada: texto => seletor.busca = texto
    onSetaParaBaixo: nenhum.botaoDaLinha.forceActiveFocus(Qt.TabFocusReason)

    Binding { target: seletorDoLudusavi.campo; property: "text"; value: seletorDoLudusavi.seletor.busca }

    function moverFoco(indice) {
        if (indice < 0) { nenhum.botaoDaLinha.forceActiveFocus(Qt.BacktabFocusReason); return }
        if (indice >= lista.count) return
        lista.positionViewAtIndex(indice, ListView.Contain)
        var item = lista.itemAtIndex(indice)
        if (item) item.forceActiveFocus(Qt.TabFocusReason)
    }

    Connections {
        target: seletorDoLudusavi.seletor
        function onEstadoChanged() {
            if (!seletorDoLudusavi.seletor.carregando && seletorDoLudusavi.seletor.busca === "" && seletorDoLudusavi.seletor.indiceAtual >= 0)
                lista.positionViewAtIndex(seletorDoLudusavi.seletor.indiceAtual, ListView.Center)
        }
    }

    Item {
        Layout.fillWidth: true
        implicitHeight: nenhum.height + 6
        z: 1  // a lista rola por baixo do "Nenhum", não da busca: a sombra cai daqui
        SombraDeRolagem { objectName: seletorDoLudusavi.objectName + "Sombra"; ativa: lista.contentY > 0 }
        GrupoDeLinhas {
            x: 12
            width: parent.width - 24
            LinhaDeAcao {
                id: nenhum
                objectName: seletorDoLudusavi.objectName + "Nenhum"
                titulo: "Nenhum (desliga o backup)"
                Keys.onUpPressed: seletorDoLudusavi.campo.forceActiveFocus(Qt.BacktabFocusReason)
                Keys.onDownPressed: seletorDoLudusavi.moverFoco(0)
                onAcionada: seletorDoLudusavi.seletor.escolherNenhum()
            }
        }
    }

    Item {
        Layout.fillWidth: true
        Layout.fillHeight: true

        PaginaDoSeletor {
            ativa: seletorDoLudusavi.seletor.carregando
            Girador {
                objectName: seletorDoLudusavi.objectName + "Carregando"
                anchors.centerIn: parent
                width: 32
                height: 32
                running: parent.visible
            }
        }

        PaginaDoSeletor {
            ativa: seletorDoLudusavi.seletor.erro || seletorDoLudusavi.seletor.vazio
            EstadoVazio {
                objectName: seletorDoLudusavi.objectName + "Vazio"
                anchors.fill: parent
                icone: seletorDoLudusavi.seletor.erro ? "dialog-warning" : "system-search"
                titulo: seletorDoLudusavi.seletor.tituloDoEstado
            }
        }

        PaginaDoSeletor {
            ativa: !seletorDoLudusavi.seletor.carregando && !seletorDoLudusavi.seletor.erro

            ListView {
                id: lista
                objectName: seletorDoLudusavi.objectName + "Lista"
                anchors.fill: parent
                model: seletorDoLudusavi.seletor
                clip: true
                reuseItems: true
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: BarraDeRolagem {}

                delegate: Button {
                    id: linha
                    required property int index
                    required property string nome
                    readonly property bool atual: index === seletorDoLudusavi.seletor.indiceAtual
                    objectName: seletorDoLudusavi.objectName + "Linha" + index
                    width: lista.width
                    implicitHeight: 8 + Tema.alturaDoCorpo + 8
                    padding: 0
                    hoverEnabled: true
                    focusPolicy: Qt.StrongFocus
                    Accessible.name: nome
                    Accessible.role: Accessible.Button
                    Keys.onReturnPressed: click()
                    Keys.onEnterPressed: click()
                    Keys.onDownPressed: seletorDoLudusavi.moverFoco(index + 1)
                    Keys.onUpPressed: seletorDoLudusavi.moverFoco(index - 1)
                    onClicked: seletorDoLudusavi.seletor.escolher(index)

                    background: Rectangle {
                        color: linha.down ? Tema.linhaPressionada : linha.atual ? Tema.mistura(0.10) : linha.hovered ? Tema.linhaSobre : "transparent"
                        AnelDeFoco { ativo: linha.visualFocus; raio: 0; afastamento: -2 }
                    }
                    contentItem: Text {
                        leftPadding: 12
                        rightPadding: 12
                        text: linha.nome
                        textFormat: Text.PlainText
                        elide: Text.ElideRight
                        verticalAlignment: Text.AlignVCenter
                        color: Tema.texto
                        font { family: Tema.fonte; pixelSize: Tema.corpo }
                    }
                }
            }
        }
    }
}
