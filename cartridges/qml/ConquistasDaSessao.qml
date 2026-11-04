import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// O cartão de conquistas da tela da sessão: o progresso e os ícones de todas as conquistas, para consultar de relance no
// outro monitor. Passivo: nada recebe foco nem clique; passar o mouse num ícone mostra a dica. Só desenha
// `conquistasDoJogo.sessao`.
Rectangle {
    id: cartao
    objectName: "conquistasDaSessao"

    // Com poucos ícones o cartão fica do tamanho deles; com muitos, cresce até aqui e passa a rolar.
    property real larguraMaxima: 600

    readonly property var dados: conquistasDoJogo.sessao
    readonly property int quantos: (dados.icones || []).length
    readonly property int tamanho: 48
    readonly property real larguraDosIcones: quantos * tamanho + Math.max(0, quantos - 1) * lista.spacing

    implicitWidth: Math.min(larguraMaxima, Math.max(topo.implicitWidth, larguraDosIcones) + 32)
    implicitHeight: coluna.implicitHeight + 32
    radius: 12
    color: Qt.rgba(1, 1, 1, 0.08)

    ColumnLayout {
        id: coluna
        anchors { fill: parent; margins: 16 }
        spacing: 12

        RowLayout {
            id: topo
            Layout.fillWidth: true
            spacing: 12
            Text {
                objectName: "tituloDaSessao"
                Layout.fillWidth: true
                text: "Conquistas"
                textFormat: Text.PlainText
                color: "white"
                font { family: Tema.fonte; pixelSize: Tema.corpo; weight: Tema.pesoForte }
            }
            Text {
                objectName: "contagemDaSessao"
                text: cartao.dados.contagem || ""
                textFormat: Text.PlainText
                color: Qt.rgba(1, 1, 1, 0.55)
                font { family: Tema.fonte; pixelSize: Tema.corpo; features: { "tnum": 1 } }
            }
            Text {
                objectName: "porcentagemDaSessao"
                text: cartao.dados.porcentagem || ""
                textFormat: Text.PlainText
                color: Qt.rgba(1, 1, 1, 0.55)
                font { family: Tema.fonte; pixelSize: Tema.corpo; features: { "tnum": 1 } }
            }
        }

        BarraDeProgresso {
            objectName: "barraDaSessao"
            Layout.fillWidth: true
            value: cartao.dados.fracao || 0
            corDaTrilha: Qt.rgba(1, 1, 1, 0.15)  // branco, porque a camada é sempre escura
        }

        // Uma linha só, rolando para os lados: em grade, um jogo com muitas conquistas virava um paredão de ícones que
        // empurrava o resto da tela.
        ListView {
            id: lista
            objectName: "iconesDaSessao"
            Layout.fillWidth: true
            Layout.preferredHeight: cartao.tamanho + 14  // a folga para a barra de rolagem, que fica sobre a borda de baixo
            orientation: ListView.Horizontal
            spacing: 6
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            keyNavigationEnabled: false
            activeFocusOnTab: false
            // Um número, e não a lista: a atualização ao vivo troca os dados de cada ícone sem recriar a fileira nem
            // arrancar a rolagem de quem está lendo.
            model: cartao.quantos

            // A próxima sessão começa do início da lista; a atualização ao vivo, não.
            readonly property string jogo: sessao.jogoId
            onJogoChanged: positionViewAtBeginning()

            delegate: IconeDaConquista {
                id: icone
                required property int index
                readonly property var dados: cartao.dados.icones[index] || ({})
                tamanho: cartao.tamanho
                interrogacao: 24
                corDoLadrilho: "white"
                corDaInterrogacao: "white"
                url: dados.url || ""
                cinza: dados.cinza === true
                oculta: dados.oculta === true

                HoverHandler { id: sobre }
                // A dica do app; o texto já sai escapado por `progresso.dica`, com `<b>` e `<br>`.
                Dica {
                    id: dica
                    objectName: "dicaDaSessao"
                    ativa: sobre.hovered
                    texto: icone.dados.dica || ""
                    contentItem: Text {
                        text: dica.text
                        textFormat: Text.StyledText
                        wrapMode: Text.Wrap
                        color: "white"
                        font { family: Tema.fonte; pixelSize: Tema.corpo }
                    }
                }
            }

            // A roda do mouse rola para os lados com a mola do app (a lista não tem para onde ir na vertical).
            RolagemPorMola { objectName: "molaDaSessao"; alvo: lista; horizontal: true; ativa: Tema.animacoes }
            // O touchpad rola direto: a mola é só do mouse.
            WheelHandler {
                acceptedDevices: Tema.animacoes ? PointerDevice.TouchPad : PointerDevice.Mouse | PointerDevice.TouchPad
                onWheel: evento => {
                    const passo = evento.angleDelta.y !== 0 ? evento.angleDelta.y : evento.angleDelta.x
                    const fim = Math.max(0, cartao.larguraDosIcones - lista.width)
                    lista.contentX = Math.max(0, Math.min(fim, lista.contentX - passo))
                }
            }

            ScrollBar.horizontal: BarraDeRolagem { objectName: "rolagemDaSessao"; cor: "#ffffff" }
        }
    }
}
