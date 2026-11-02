import QtQuick
import QtQuick.Effects
import QtQuick.Shapes

// O cartão do aviso de conquista (o `montar_cartao` da `main`): ícone, rótulo, título e descrição.
// A janela por cima do jogo (`janela_do_aviso.py`) é só ele; o assistente e o "exemplo" das
// Preferências mostram o mesmo cartão. Os textos são de terceiros: sempre texto puro.
Item {
    id: cartao
    objectName: "cartaoDoAviso"

    property string rotulo: ""
    property string titulo: ""
    property string descricao: ""
    property string icone: ""  // URL `file:` do ícone já baixado; vazio = ainda a caminho (ou sem ícone)
    // A estrela é só do aviso que não tem ícone nenhum; com o ícone a caminho (ou que falhou), fica o quadrado vazio de 48 px.
    property bool semIcone: true
    property bool opaco: false  // a reserva sem transparência: fundo cheio e cantos retos
    // O cartão dentro do assistente (`conquista-aviso-cartao-embutido`): contorno branco a 14% e sombra.
    property bool embutido: false
    // O fade segue os efeitos de animação do Windows (`gtk-enable-animations`); a janela do aviso o passa de fora.
    property bool animar: Tema.animacoes
    property real opacidade: 1
    // Mudar anima a opacidade até 1 (true) ou 0 (false); `terminou` no fim de cada animação.
    property bool mostrado: false
    signal terminou()

    readonly property int raio: opaco ? 0 : 12
    // max-width-chars: 36, medido na fonte de cada texto (o caption quebra mais cedo que o título).
    readonly property real larguraMaxima: medidaDoTitulo.averageCharacterWidth * 36

    opacity: opacidade
    implicitWidth: 3 + 12 + Math.max(280, conteudo.implicitWidth) + 16
    implicitHeight: 12 + conteudo.implicitHeight + 12

    onMostradoChanged: {
        animacao.to = mostrado ? 1 : 0
        animacao.restart()
    }

    NumberAnimation {
        id: animacao
        target: cartao
        property: "opacidade"
        duration: cartao.animar ? 250 : 0
        easing.type: Easing.OutCubic  // a curva padrão do `Adw.TimedAnimation`
        onFinished: cartao.terminou()
    }

    FontMetrics { id: medidaDoRotulo; font: textoDoRotulo.font }
    FontMetrics { id: medidaDoTitulo; font: textoDoTitulo.font }
    FontMetrics { id: medidaDaDescricao; font: textoDaDescricao.font }

    Rectangle {
        anchors.fill: parent
        radius: cartao.raio
        color: cartao.opaco ? "#1c1b22" : Qt.rgba(28 / 255, 27 / 255, 34 / 255, 0.94)
        // 0 0 0 1px alpha(white, .14), 0 2px 8px rgba(0, 0, 0, .35)
        Sombra { objectName: "sombraDoAviso"; visible: cartao.embutido; camadas: [[0, 0, 1, 1, 1, 1, 0.14], [2, 8, 0, 0, 0, 0, 0.35]]; raio: cartao.raio }
    }

    // `border-left: 3px solid` com `border-radius: 12px`: a faixa segue a curva e afina até zero no topo e na base (a borda
    // de fora tem raio 12; a de dentro, 9 na horizontal e 12 na vertical).
    Shape {
        objectName: "bordaDoAviso"
        anchors.fill: parent
        visible: !cartao.opaco
        preferredRendererType: Shape.CurveRenderer
        ShapePath {
            fillColor: Tema.destaque
            strokeWidth: -1
            startX: 12; startY: 0
            PathArc { x: 0; y: 12; radiusX: 12; radiusY: 12; direction: PathArc.Counterclockwise }
            PathLine { x: 0; y: cartao.height - 12 }
            PathArc { x: 12; y: cartao.height; radiusX: 12; radiusY: 12; direction: PathArc.Counterclockwise }
            PathArc { x: 3; y: cartao.height - 12; radiusX: 9; radiusY: 12; direction: PathArc.Clockwise }
            PathLine { x: 3; y: 12 }
            PathArc { x: 12; y: 0; radiusX: 9; radiusY: 12; direction: PathArc.Clockwise }
        }
    }
    // A reserva sem transparência tem os cantos retos: a borda é uma faixa reta.
    Rectangle { objectName: "bordaRetaDoAviso"; visible: cartao.opaco; width: 3; height: parent.height; color: Tema.destaque }

    Row {
        id: conteudo
        x: 3 + 12
        y: 12
        spacing: 12

        Item {
            id: lugarDoIcone
            width: 48
            height: 48
            anchors.verticalCenter: parent.verticalCenter

            Item {
                id: mascara
                anchors.fill: parent
                visible: false
                layer.enabled: true
                Rectangle { anchors.fill: parent; radius: 6 }
            }

            Image {
                id: imagem
                objectName: "iconeDoAviso"
                anchors.fill: parent
                visible: cartao.icone !== ""
                source: cartao.icone
                fillMode: Image.PreserveAspectCrop
                sourceSize: Qt.size(48 * Screen.devicePixelRatio, 48 * Screen.devicePixelRatio)
                layer.enabled: true
                layer.effect: MultiEffect {
                    maskEnabled: true
                    maskSource: mascara
                    maskThresholdMin: 0.5  // borda suave nos cantos arredondados
                    maskSpreadAtMin: 1.0
                }
            }

            // O `starred-symbolic` da `main`, branco, no tamanho do ícone.
            Icone {
                objectName: "estrelaDoAviso"
                anchors.centerIn: parent
                visible: cartao.semIcone && cartao.icone === ""
                nome: "starred"
                tamanho: 48
                cor: "#ffffff"
            }
        }

        Column {
            anchors.verticalCenter: parent.verticalCenter

            Text {
                id: textoDoRotulo
                objectName: "rotuloDoAviso"
                visible: text !== ""
                width: Math.min(implicitWidth, 36 * medidaDoRotulo.averageCharacterWidth)
                text: cartao.rotulo
                textFormat: Text.PlainText
                wrapMode: Text.Wrap
                color: "#ffffff"
                opacity: 0.75
                lineHeight: 1.4  // `.caption`: 82% e linha de 140%
                font { family: Tema.fonte; pixelSize: Tema.legenda }
            }

            Text {
                id: textoDoTitulo
                objectName: "tituloDoAviso"
                visible: text !== ""
                width: Math.min(implicitWidth, cartao.larguraMaxima)
                text: cartao.titulo
                textFormat: Text.PlainText
                wrapMode: Text.Wrap
                color: "#ffffff"
                font { family: Tema.fonte; pixelSize: Tema.corpo; weight: Tema.pesoForte }  // .heading
            }

            Text {
                id: textoDaDescricao
                objectName: "descricaoDoAviso"
                visible: text !== ""
                width: Math.min(implicitWidth, 36 * medidaDaDescricao.averageCharacterWidth)
                text: cartao.descricao
                textFormat: Text.PlainText
                wrapMode: Text.Wrap
                color: "#ffffff"
                opacity: 0.55
                lineHeight: 1.4
                font { family: Tema.fonte; pixelSize: Tema.legenda }
            }
        }
    }
}
