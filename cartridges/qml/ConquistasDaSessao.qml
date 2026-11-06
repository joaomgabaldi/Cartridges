import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// O cartão de conquistas da tela da sessão, passivo (nada recebe foco nem clique).
Rectangle {
    id: cartao
    objectName: "conquistasDaSessao"

    property real larguraMaxima: 600
    // No Big Picture, o ícone que chega depois de a fileira estar montada entra deslizando da direita.
    property bool animarNovos: false

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
            corDaTrilha: Qt.rgba(1, 1, 1, 0.15)
        }

        ListView {
            id: lista
            objectName: "iconesDaSessao"
            Layout.fillWidth: true
            Layout.preferredHeight: cartao.tamanho + 14
            orientation: ListView.Horizontal
            spacing: 6
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            keyNavigationEnabled: false
            activeFocusOnTab: false
            // Um número, e não a lista: a atualização ao vivo troca os dados de cada ícone sem recriar a fileira nem
            // arrancar a rolagem.
            model: cartao.quantos

            readonly property string jogo: sessao.jogoId
            onJogoChanged: { positionViewAtBeginning(); montada = false }
            // Verdadeiro um instante depois da primeira leva de ícones: os que já estavam não animam.
            property bool montada: false
            onCountChanged: if (count > 0 && !montada) Qt.callLater(() => montada = count > 0)

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

                transform: Translate { id: deslize }
                NumberAnimation {
                    id: entrada
                    target: deslize
                    property: "x"
                    from: lista.width - icone.x
                    to: 0
                    duration: 600
                    easing.type: Easing.OutBack
                }
                Component.onCompleted: if (cartao.animarNovos && lista.montada) entrada.restart()
                // Um ícone que acabou de ser desbloqueado.
                onCinzaChanged: if (!cinza && cartao.animarNovos && lista.montada) entrada.restart()

                HoverHandler { id: sobre }
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

            RolagemPorMola { objectName: "molaDaSessao"; alvo: lista; horizontal: true; ativa: Tema.animacoes }
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
