import QtQuick
import QtQuick.Controls.Basic

// O botão do app. `estilo`: "normal", "plano", "sugestao", "destrutivo"; `pilula`, `circular`, `icone` (nome em
// `data/icones`), `dica`.
Button {
    id: botao

    property string estilo: "normal"
    property bool pilula: false
    property bool circular: false
    property string icone
    property int tamanhoDoIcone: 16
    property string dica
    property bool sublinharPrimeira: false
    property bool cortarRotulo: false
    property bool dicaAtiva: hovered
    property bool dicaSomeAoClicar: true
    property bool semRealce: false
    property real raio: pilula || circular ? height / 2 : 9
    property real afastamentoDoAnel: estilo === "plano" ? -2 : 1
    property color corDoTexto: estilo === "sugestao" ? Tema.textoDoDestaque : estilo === "destrutivo" ? Tema.destrutivoTexto : Tema.texto

    readonly property bool _soIcone: text === "" && icone !== ""

    hoverEnabled: true
    focusPolicy: Qt.StrongFocus
    Accessible.name: text !== "" ? text : dica
    Keys.onReturnPressed: click()
    Keys.onEnterPressed: click()
    // Dentro de uma linha apagada só vale o apagado dela: somados, dariam 25%.
    readonly property bool _dentroDeLinhaApagada: {
        for (let p = parent; p; p = p.parent)
            if (p.linhaApagada === true) return true
        return false
    }
    opacity: enabled || _dentroDeLinhaApagada ? 1 : Tema.opacidadeDesabilitado
    implicitHeight: pilula ? 44 : 34
    implicitWidth: _soIcone ? implicitHeight : Math.max(contentItem.implicitWidth + leftPadding + rightPadding, 34)
    leftPadding: pilula ? 32 : _soIcone ? 5 : icone !== "" ? 9 : 17
    rightPadding: leftPadding
    topPadding: 0
    bottomPadding: 0

    // A largura do rótulo inteiro: com `cortarRotulo` o `Text` encolhe, e o `implicitWidth` do botão não pode encolher
    // junto.
    Loader {
        id: medida
        active: botao.cortarRotulo
        sourceComponent: TextMetrics {
            text: botao.text
            font { family: Tema.fonte; pixelSize: Tema.corpo; weight: Tema.pesoForte }
        }
    }
    readonly property real _larguraDoRotulo: medida.item ? medida.item.advanceWidth : 0

    contentItem: Item {
        implicitWidth: botao.cortarRotulo ? botao._larguraDoRotulo + (botao.icone !== "" ? botao.tamanhoDoIcone + conteudo.spacing : 0) : conteudo.implicitWidth
        implicitHeight: conteudo.implicitHeight
        Row {
            id: conteudo
            anchors.centerIn: parent
            spacing: 6
            Icone {
                anchors.verticalCenter: parent.verticalCenter
                visible: botao.icone !== ""
                nome: botao.icone
                tamanho: botao.tamanhoDoIcone
                cor: botao.corDoTexto
            }
            Text {
                anchors.verticalCenter: parent.verticalCenter
                visible: text !== ""
                width: botao.cortarRotulo ? Math.min(botao._larguraDoRotulo, Math.max(0, botao.availableWidth - (botao.icone !== "" ? botao.tamanhoDoIcone + conteudo.spacing : 0))) : implicitWidth
                elide: botao.cortarRotulo ? Text.ElideRight : Text.ElideNone
                text: botao.sublinharPrimeira ? "<u>" + botao.text.charAt(0) + "</u>" + botao.text.slice(1) : botao.text
                textFormat: botao.sublinharPrimeira ? Text.StyledText : Text.PlainText
                color: botao.corDoTexto
                font { family: Tema.fonte; pixelSize: Tema.corpo; weight: Tema.pesoForte }
            }
        }
    }

    background: Rectangle {
        radius: botao.raio
        color: {
            if (botao.estilo === "sugestao") return Tema.destaque
            const apertado = botao.down && !botao.semRealce
            const ligado = apertado || botao.checked
            const sobre = botao.hovered && !botao.semRealce
            const alfa = botao.estilo === "plano" ? (apertado ? 0.16 : botao.checked ? 0.10 : sobre ? 0.07 : 0)
                : botao.estilo === "destrutivo" ? (ligado ? 0.35 : sobre ? 0.20 : 0.15)
                : (ligado ? 0.30 : sobre ? 0.15 : 0.10)
            return Qt.alpha(botao.corDoTexto, botao.corDoTexto.a * alfa)
        }
        Behavior on color { ColorAnimation { duration: Tema.duracaoCurta; easing { type: Easing.Bezier; bezierCurve: Tema.curva } } }
        Rectangle {
            anchors.fill: parent
            radius: parent.radius
            opacity: botao.estilo === "sugestao" && (botao.hovered || botao.down) ? 1 : 0
            visible: opacity > 0
            color: botao.down ? Qt.rgba(0, 0, 6 / 255, 0.2) : Qt.rgba(1, 1, 1, 0.1)
            Behavior on opacity { NumberAnimation { duration: Tema.duracaoCurta; easing { type: Easing.Bezier; bezierCurve: Tema.curva } } }
        }
        AnelDeFoco { ativo: botao.visualFocus; raio: parent.radius; afastamento: botao.afastamentoDoAnel }
    }

    Dica { texto: botao.dica; ativa: botao.dicaAtiva; someAoClicar: botao.dicaSomeAoClicar }
}
