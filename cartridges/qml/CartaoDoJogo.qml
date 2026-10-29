import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Effects
import QtQuick.Window

// Um jogo da grade, no desenho da versão anterior: a capa e o nome dentro do mesmo cartão arredondado.
// Ao passar o mouse (ou com o foco do teclado na grade): jogar no canto superior esquerdo e "Mais opções" no direito.
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
    // "Animar capas" (com os efeitos de animação do Windows ligados): a única forma de a capa animar.
    // Animar ao passar o mouse não existe na `main`; fica como proposta, aguardando a aprovação do usuário.
    property bool tocarSempre: false
    // Sem animação o cartão mostra a capa parada; fora da vista, janela minimizada ou oculta, nada toca
    // e o arquivo da cópia é largado.
    readonly property bool animando: capaAnimada !== "" && naVista && tocarSempre
        && Window.visibility !== Window.Minimized && Window.visibility !== Window.Hidden
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
    readonly property int alturaDoNome: 50
    readonly property bool mostrarBotoes: !zerado && (passagem.hovered || focado || menuAberto)
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
    color: Tema.superficie
    border { width: focado ? 2 : 0; color: Tema.destaque }

    Accessible.role: Accessible.Button
    Accessible.name: nome
    Accessible.onPressAction: abrirDetalhes(jogoId)

    HoverHandler { id: passagem }

    // Clique na capa: detalhes. Clique direito: Editar (como na `main`).
    TapHandler {
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
        layer.enabled: true
        layer.effect: MultiEffect {
            maskEnabled: true
            maskSource: mascara
            maskThresholdMin: 0.5  // borda suave nos cantos arredondados
            maskSpreadAtMin: 1.0
        }

        Image {
            id: imagem
            anchors.fill: parent
            source: cartao.capa !== "" ? cartao.capa : (cartao.modelo ? cartao.modelo.placeholder : "")
            fillMode: Image.PreserveAspectCrop
            asynchronous: true
            // Na resolução real da tela, para a capa não ficar borrada em DPI alto.
            sourceSize: Qt.size(cartao.larguraDaCapa * Screen.devicePixelRatio,
                                cartao.alturaDaCapa * Screen.devicePixelRatio)
        }

        AnimatedImage {
            id: animada
            objectName: "capaAnimada"
            anchors.fill: parent
            source: cartao.animando ? cartao.capaAnimada : ""
            playing: cartao.animando
            visible: status === AnimatedImage.Ready
            fillMode: Image.PreserveAspectCrop
            asynchronous: true
            cache: false
        }
    }

    BusyIndicator {
        objectName: "carregando"
        anchors { horizontalCenter: capa.horizontalCenter; verticalCenter: capa.verticalCenter }
        running: cartao.carregando
        visible: cartao.carregando
        palette.dark: Tema.destaque
    }

    Text {
        anchors { left: parent.left; right: parent.right; bottom: parent.bottom; leftMargin: 12; rightMargin: 12 }
        height: cartao.alturaDoNome
        verticalAlignment: Text.AlignVCenter
        text: cartao.nome
        textFormat: Text.PlainText
        color: Tema.texto
        font { family: Tema.fonte; pixelSize: 14 }
        elide: Text.ElideRight
    }

    // Os botões só existem fora de um zerado (que não joga nem tem menu).
    Loader {
        id: carregadorDosBotoes
        anchors.fill: parent
        active: !cartao.zerado
        sourceComponent: Item {
            readonly property Item ancoraDoMenu: botaoMais
            opacity: cartao.mostrarBotoes ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: Tema.duracaoCurta } }

            component BotaoRedondo: Rectangle {
                id: botao
                property string glifo
                property string dica
                signal clicado()
                width: 36; height: width; radius: width / 2
                color: pressao.pressed ? "#cc000000" : (pressao.containsMouse ? "#b3000000" : "#99000000")
                Accessible.role: Accessible.Button
                Accessible.name: dica
                Text {
                    anchors.centerIn: parent
                    text: botao.glifo
                    color: "white"
                    font { family: Tema.fonteDeIcones; pixelSize: 16 }
                }
                // MouseArea, não TapHandler: o clique no botão não pode chegar ao cartão.
                MouseArea {
                    id: pressao
                    anchors.fill: parent
                    enabled: cartao.mostrarBotoes
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: botao.clicado()
                }
                ToolTip.visible: pressao.containsMouse && ToolTip.text !== ""
                ToolTip.delay: 600
                ToolTip.text: dica
            }

            BotaoRedondo {
                id: botaoJogar
                objectName: "botaoJogar"
                x: 6; y: 6
                glifo: ""
                dica: "Jogar"
                onClicado: if (cartao.modelo) cartao.modelo.iniciar(cartao.jogoId)
            }
            BotaoRedondo {
                id: botaoMais
                objectName: "botaoMais"
                x: cartao.larguraDaCapa - width - 6; y: 6
                glifo: ""
                dica: "Mais opções"
                onClicado: cartao.abrirMenu()
            }
        }
    }
}
