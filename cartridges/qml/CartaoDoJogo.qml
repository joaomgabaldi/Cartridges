import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Effects
import QtQuick.Window

// Um jogo da grade: a capa e o nome dentro do mesmo cartão arredondado. Ao passar o mouse: jogar no canto superior
// esquerdo e "Mais opções" no direito (só o ponteiro).
Rectangle {
    id: cartao

    required property string jogoId
    required property string nome
    required property string capa
    required property bool zerado
    required property bool carregando
    // A cópia WebP animada no tamanho da grade; "" se a capa é parada ou a cópia ainda não saiu.
    property string capaAnimada: ""
    // O cartão está dentro da janela visível da grade (o delegate liga).
    property bool naVista: true
    // "Animar capas" (com os efeitos de animação do Windows ligados): as capas à vista tocam sem o mouse.
    property bool tocarSempre: false
    // Há um patch esperando no feed (e o jogo não é zerado): o halo dourado em volta do cartão.
    property bool temAtualizacao: false
    // Passar o mouse toca a capa animada com ou sem "Animar capas", também em Jogos Zerados. Sem animação o cartão mostra
    // a capa parada; fora da vista, janela minimizada ou oculta, nada toca e o arquivo da cópia é largado.
    readonly property bool animando: capaAnimada !== "" && naVista && (tocarSempre || passando)
        && Window.visibility !== Window.Minimized && Window.visibility !== Window.Hidden
    // Parar pausa no quadro atual (`tocador_capas.py`): o arquivo da cópia fica aberto por 30 s, e só então a capa volta
    // ao primeiro quadro; a grade limita as pausadas a 8 (`liberar`). Retomar segue de onde parou.
    // O ponteiro está sobre o cartão. Propriedade comum (não só `passagem.hovered`) para os testes, que no offscreen não
    // conseguem produzir o hover, a ligarem.
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
    // O modelo da biblioteca: só `iniciar` é chamado nele; o QML nunca vê um Jogo.
    property QtObject modelo

    signal abrirDetalhes(string jogoId)
    signal editar(string jogoId)
    signal menuPedido(string jogoId, Item ancora)

    readonly property int larguraDaCapa: 200
    readonly property int alturaDaCapa: 300
    readonly property int alturaDoNome: 47
    // Só o ponteiro e o menu aberto mostram os botões: o foco do teclado e o controle não.
    readonly property bool mostrarBotoes: !zerado && (passando || menuAberto)
    property bool menuAberto: false
    readonly property string nomeAcessivel: Accessible.name
    readonly property string papelAcessivel: Accessible.role === Accessible.Button ? "Button" : ""

    function abrirMenu() {
        if (!zerado) menuPedido(jogoId, carregadorDosBotoes.item ? carregadorDosBotoes.item.ancoraDoMenu : cartao)
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

    Item {
        id: mascara
        width: cartao.larguraDaCapa
        height: cartao.alturaDaCapa
        visible: false
        layer.enabled: true
        // Cantos de cima arredondados, os de baixo retos: o retângulo passa do fim para o raio sumir embaixo.
        Rectangle { width: parent.width; height: parent.height + cartao.radius; radius: cartao.radius }
    }

    Item {
        id: capa
        width: cartao.larguraDaCapa
        height: cartao.alturaDaCapa
        opacity: cartao.carregando ? 0 : 1
        layer.enabled: true
        layer.effect: MultiEffect {
            maskEnabled: true
            maskSource: mascara
            maskThresholdMin: 0.5
            maskSpreadAtMin: 1.0
        }

        Image {
            id: imagem
            objectName: "capaParada"
            // A URL que não se leu (arquivo quebrado): no lugar dela, o placeholder. Uma capa nova muda a URL (`?v=`).
            property string ilegivel: ""
            // Para a `CortinaDaAbertura` (Python), que não lê o enum do `status`.
            readonly property bool carregandoArquivo: status === Image.Loading
            anchors.fill: parent
            source: cartao.capa !== "" && cartao.capa !== ilegivel ? cartao.capa : (cartao.modelo ? cartao.modelo.placeholder : "")
            onStatusChanged: if (status === Image.Error && source.toString() === cartao.capa) ilegivel = cartao.capa
            // A capa que não é 2:3 é esticada para 200x300; o placeholder também.
            fillMode: Image.Stretch
            asynchronous: true
            // Na resolução real da tela, para a capa não ficar borrada em DPI alto.
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

    Loader {
        id: carregadorDosBotoes
        anchors.fill: parent
        active: !cartao.zerado
        sourceComponent: Item {
            readonly property Item ancoraDoMenu: botaoMais
            opacity: cartao.mostrarBotoes ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: 250 } }

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
                // Sem dica visível: o nome é só para quem usa leitor de tela.
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
                dica: "Jogar"
                onClicado: if (cartao.modelo) cartao.modelo.iniciar(cartao.jogoId)
            }
            BotaoRedondo {
                id: botaoMais
                objectName: "botaoMais"
                x: cartao.larguraDaCapa - width - 6; y: 6
                icone: "view-more"
                dica: "Mais opções"
                onClicado: cartao.abrirMenu()
            }
        }
    }
}
