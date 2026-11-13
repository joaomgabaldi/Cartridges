import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Effects
import QtQuick.Window

// Um jogo da grade: a capa e o nome no mesmo cartão arredondado; ao passar o mouse, jogar e "Mais opções".
Rectangle {
    id: cartao

    required property string jogoId
    required property string nome
    required property string capa
    required property bool zerado
    required property bool carregando
    property string capaAnimada: ""
    // A capa já reduzida ao tamanho da grade (`miniaturas.py`); vazia, ou ilegível, a imagem usa a `capa`.
    property string miniatura: ""
    property bool naVista: true
    property bool tocarSempre: false
    property bool temAtualizacao: false
    readonly property bool animando: capaAnimada !== "" && naVista && (tocarSempre || passando)
        && Window.visibility !== Window.Minimized && Window.visibility !== Window.Hidden
    // Parar pausa no quadro atual (`tocador_capas.py`): o arquivo da cópia fica aberto por 30 s, e só então a capa volta
    // ao primeiro quadro.
    // O ponteiro está sobre o cartão. Propriedade comum (não só `passagem.hovered`) porque os testes não produzem hover
    // no offscreen.
    property bool passando: passagem.hovered
    property bool retendo: false
    signal pausou()
    function liberar() { retendo = false; retencao.stop() }
    onAnimandoChanged: {
        if (animando) {
            retendo = false
            retencao.stop()
        } else if (capaAnimada !== "" && animada.status === AnimatedImage.Ready) {
            retendo = true
            retencao.restart()
            pausou()
        }
    }
    Timer { id: retencao; interval: 30000; onTriggered: cartao.retendo = false }
    property bool focado: false
    property QtObject modelo
    // A máscara dos cantos da capa que a `Grade` divide entre os cartões; sem ela, o cartão cria a própria.
    property Item mascaraCompartilhada: null

    signal abrirDetalhes(string jogoId)
    signal editar(string jogoId)
    signal menuPedido(string jogoId, Item ancora)

    readonly property int larguraDaCapa: 200
    readonly property int alturaDaCapa: 300
    readonly property int alturaDoNome: 47
    readonly property bool mostrarBotoes: !zerado && (passando || menuAberto)
    property bool menuAberto: false
    readonly property string nomeAcessivel: Accessible.name
    readonly property string papelAcessivel: Accessible.role === Accessible.Button ? "Button" : ""

    function abrirMenu() {
        if (!zerado) menuPedido(jogoId, ancoraDoMenu)
    }

    width: larguraDaCapa
    height: alturaDaCapa + alturaDoNome
    radius: 12
    color: Tema.cartao
    readonly property bool pressionado: toque.pressed

    Sombra {
        visible: !cartao.temAtualizacao
        opacity: passagem.hovered ? 0 : 1
        Behavior on opacity { NumberAnimation { duration: Tema.duracaoCurta } }
        camadas: Tema.sombraCartao
        raio: cartao.radius
    }
    Loader {
        anchors.fill: parent
        z: -1
        active: !cartao.temAtualizacao && (passagem.hovered || opacity > 0)
        opacity: passagem.hovered ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: Tema.duracaoCurta } }
        sourceComponent: Sombra { camadas: [[6, 16, 2, 0, 0, 0, 0.25]]; raio: cartao.radius }
    }
    Loader {
        anchors.fill: parent
        z: -1
        active: cartao.temAtualizacao
        sourceComponent: Sombra { objectName: "haloDaAtualizacao"; camadas: [[0, 22, 5, 245 / 255, 184 / 255, 32 / 255, 0.8]]; raio: cartao.radius }
    }
    Rectangle {
        anchors.fill: parent
        radius: cartao.radius
        color: cartao.pressionado ? Tema.mistura(0.08) : passagem.hovered ? Tema.mistura(0.04) : "transparent"
        Behavior on color { ColorAnimation { duration: Tema.duracaoCurta } }
    }

    Accessible.role: Accessible.Button
    Accessible.name: nome
    Accessible.onPressAction: abrirDetalhes(jogoId)

    HoverHandler { id: passagem }

    TapHandler {
        id: toque
        onTapped: cartao.abrirDetalhes(cartao.jogoId)
    }
    TapHandler {
        acceptedButtons: Qt.RightButton
        onTapped: cartao.editar(cartao.jogoId)
    }

    Loader {
        id: mascaraPropria
        active: cartao.mascaraCompartilhada === null
        sourceComponent: Item {
            objectName: "mascaraDaCapa"
            width: cartao.larguraDaCapa
            height: cartao.alturaDaCapa
            visible: false
            layer.enabled: true
            Rectangle { width: parent.width; height: parent.height + cartao.radius; radius: cartao.radius }
        }
    }

    Item {
        id: capa
        width: cartao.larguraDaCapa
        height: cartao.alturaDaCapa
        opacity: cartao.carregando ? 0 : 1
        layer.enabled: true
        layer.effect: MultiEffect {
            maskEnabled: true
            maskSource: cartao.mascaraCompartilhada ?? mascaraPropria.item
            maskThresholdMin: 0.5
            maskSpreadAtMin: 1.0
        }

        Image {
            id: imagem
            objectName: "capaParada"
            property string ilegivel: ""
            property string miniaturaIlegivel: ""
            // Para a `CortinaDaAbertura` (Python), que não lê o enum do `status`.
            readonly property bool carregandoArquivo: status === Image.Loading
            anchors.fill: parent
            source: cartao.miniatura !== "" && cartao.miniatura !== miniaturaIlegivel ? cartao.miniatura
                : cartao.capa !== "" && cartao.capa !== ilegivel ? cartao.capa : (cartao.modelo ? cartao.modelo.placeholder : "")
            onStatusChanged: {
                if (status !== Image.Error) return
                const atual = source.toString()
                if (atual === cartao.miniatura) miniaturaIlegivel = cartao.miniatura
                else if (atual === cartao.capa) ilegivel = cartao.capa
            }
            fillMode: Image.Stretch
            asynchronous: true
            sourceSize: Qt.size(cartao.larguraDaCapa * Screen.devicePixelRatio,
                                cartao.alturaDaCapa * Screen.devicePixelRatio)
        }

        AnimatedImage {
            id: animada
            objectName: "capaAnimada"
            anchors.fill: parent
            source: cartao.animando || cartao.retendo ? cartao.capaAnimada : ""
            playing: cartao.animando
            visible: status === AnimatedImage.Ready
            fillMode: Image.Stretch
            asynchronous: true
            cache: false
        }
    }

    Girador {
        objectName: "carregando"
        anchors { horizontalCenter: capa.horizontalCenter; verticalCenter: capa.verticalCenter }
        running: cartao.carregando
        visible: cartao.carregando
    }

    Text {
        anchors { left: parent.left; right: parent.right; bottom: parent.bottom; leftMargin: 12; rightMargin: 12 }
        height: cartao.alturaDoNome
        verticalAlignment: Text.AlignVCenter
        text: cartao.nome
        textFormat: Text.PlainText
        color: Tema.texto
        font { family: Tema.fonte; pixelSize: Tema.corpo }
        elide: Text.ElideRight
    }

    AnelDeFoco { ativo: cartao.focado; raio: cartao.radius; afastamento: -1 }

    // Onde o botão "Mais opções" fica; o menu aberto pelo teclado ou pelo controle nasce aqui, com ou sem o botão criado.
    Item { id: ancoraDoMenu; x: cartao.larguraDaCapa - width - 6; y: 6; width: 34; height: 34 }

    // Os botões só existem com o ponteiro em cima (ou no fade de saída): são dois ícones e duas áreas por cartão.
    Loader {
        id: carregadorDosBotoes
        anchors.fill: parent
        active: !cartao.zerado && (cartao.mostrarBotoes || opacity > 0)
        opacity: cartao.mostrarBotoes ? 1 : 0
        Behavior on opacity { NumberAnimation { duration: 250 } }
        sourceComponent: Item {
            component BotaoRedondo: Rectangle {
                id: botao
                property string icone
                property string dica
                signal clicado()
                width: 34; height: width; radius: width / 2
                color: pressao.pressed ? Qt.rgba(0.25, 0.25, 0.25, 0.65)
                    : (pressao.containsMouse ? Qt.rgba(0.15, 0.15, 0.15, 0.65) : Qt.rgba(0, 0, 0, 0.65))
                Behavior on color { ColorAnimation { duration: Tema.duracaoCurta } }
                Accessible.role: Accessible.Button
                Accessible.name: dica
                Icone {
                    anchors.centerIn: parent
                    nome: botao.icone
                    cor: "white"
                    opacity: 0.9
                }
                // MouseArea, não TapHandler: o clique no botão não pode chegar ao cartão.
                MouseArea {
                    id: pressao
                    anchors.fill: parent
                    enabled: cartao.mostrarBotoes
                    hoverEnabled: true
                    onClicked: botao.clicado()
                }
            }

            BotaoRedondo {
                id: botaoJogar
                objectName: "botaoJogar"
                x: 6; y: 6
                icone: "media-playback-start"
                dica: "Iniciar"
                onClicado: if (cartao.modelo) cartao.modelo.iniciar(cartao.jogoId)
            }
            BotaoRedondo {
                id: botaoMais
                objectName: "botaoMais"
                x: ancoraDoMenu.x; y: ancoraDoMenu.y
                icone: "view-more"
                dica: "Mais opções"
                onClicado: cartao.abrirMenu()
            }
        }
    }
}
