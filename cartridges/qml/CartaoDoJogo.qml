import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Effects
import QtQuick.Window

// Um jogo da grade, no desenho da versão anterior: a capa e o nome dentro do mesmo cartão arredondado.
// Ao passar o mouse: jogar no canto superior esquerdo e "Mais opções" no direito (`toggle_play` da `main`: só o ponteiro).
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
    // Como na `main` (`game_cover.py:531`): passar o mouse toca a capa animada com ou sem "Animar capas", também em
    // Jogos Zerados. Sem animação o cartão mostra a capa parada; fora da vista, janela minimizada ou oculta, nada toca
    // e o arquivo da cópia é largado.
    readonly property bool animando: capaAnimada !== "" && naVista && (tocarSempre || passando)
        && Window.visibility !== Window.Minimized && Window.visibility !== Window.Hidden
    // Parar pausa no quadro atual (`tocador_capas.py`): o arquivo da cópia fica aberto por 30 s, e só então a capa volta
    // ao primeiro quadro; a grade limita as pausadas a 8 (`liberar`). Retomar segue de onde parou.
    // O ponteiro está sobre o cartão. Propriedade comum (não só `passagem.hovered`) para os testes, que no offscreen não
    // conseguem produzir o hover, a poderem ligar.
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
    // O cartão sob o foco do teclado na grade (o delegate liga).
    property bool focado: false
    // O modelo da biblioteca: só `iniciar` é chamado nele; o QML nunca vê um Jogo.
    property QtObject modelo

    // O clique na capa abre os detalhes.
    signal abrirDetalhes(string jogoId)
    // O clique direito no cartão pede o diálogo Editar.
    signal editar(string jogoId)
    // O botão "Mais opções" (ou a tecla de menu) pede o menu do jogo, ancorado no item.
    signal menuPedido(string jogoId, Item ancora)

    readonly property int larguraDaCapa: 200
    readonly property int alturaDaCapa: 300
    // 15 + a linha de 17 + 15.
    readonly property int alturaDoNome: 47
    // Só o ponteiro e o menu aberto mostram os botões (`game.py:564`): o foco do teclado e o controle não.
    readonly property bool mostrarBotoes: !zerado && (passando || menuAberto)
    // O menu do jogo está aberto a partir deste cartão: os botões ficam à vista enquanto ele durar.
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

    // `.card`, ou o realce do ponteiro (`#cover_button:hover`), ou o halo da atualização: cada regra troca o
    // `box-shadow` inteiro, e o halo vem por último e vence o ponteiro.
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
    // O véu do `button:hover`: 4% do texto ao passar, 8% pressionado, atrás da capa (só o rodapé o mostra).
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

    // Clique na capa: detalhes. Clique direito: Editar (como na `main`).
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

    // A capa parada e, por cima dela, a animada; os cantos arredondados valem para as duas.
    Item {
        id: capa
        width: cartao.larguraDaCapa
        height: cartao.alturaDaCapa
        // Carregando, a capa some e o girador aparece (`set_loading`).
        opacity: cartao.carregando ? 0 : 1
        layer.enabled: true
        layer.effect: MultiEffect {
            maskEnabled: true
            maskSource: mascara
            maskThresholdMin: 0.5  // borda suave nos cantos arredondados
            maskSpreadAtMin: 1.0
        }

        Image {
            id: imagem
            objectName: "capaParada"
            // A URL que não se leu (arquivo quebrado): no lugar dela, o placeholder, como na `main`. Uma capa nova muda a URL (`?v=`).
            property string ilegivel: ""
            // Para a `CortinaDaAbertura` (Python), que não lê o enum do `status`.
            readonly property bool carregandoArquivo: status === Image.Loading
            anchors.fill: parent
            source: cartao.capa !== "" && cartao.capa !== ilegivel ? cartao.capa : (cartao.modelo ? cartao.modelo.placeholder : "")
            onStatusChanged: if (status === Image.Error && source.toString() === cartao.capa) ilegivel = cartao.capa
            // A capa que não é 2:3 é esticada para 200x300 (`new_from_file_at_scale(..., False)`); o placeholder também.
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

    // O foco do teclado: contorno de 2 px em destaque a 50%, afastado -1 (CSS 382), por cima da capa.
    AnelDeFoco { ativo: cartao.focado; raio: cartao.radius; afastamento: -1 }

    // Os botões só existem fora de um zerado (que não joga nem tem menu).
    Loader {
        id: carregadorDosBotoes
        anchors.fill: parent
        active: !cartao.zerado
        sourceComponent: Item {
            readonly property Item ancoraDoMenu: botaoMais
            opacity: cartao.mostrarBotoes ? 1 : 0
            // `Revealer` crossfade: 250 ms.
            Behavior on opacity { NumberAnimation { duration: 250 } }

            // `.circular.osd`: 34x34, fundo preto a 65%; ao passar, 15% de branco na mistura; pressionado, 25%.
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
                // Sem dica visível (`game.blp`): o nome é só para quem usa leitor de tela.
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
