import QtQuick
import QtQuick.Controls.Basic

// O botão da libadwaita. `estilo`: "normal" (10% do texto), "plano" (.flat), "sugestao" (.suggested-action),
// "destrutivo" (.destructive-action). `pilula` (.pill), `circular` (.circular), `icone` (nome de `data/icones`), `dica`.
// Altura 34, raio 9, texto em negrito; desabilitado a 50%. Enter e Espaço acionam; o foco do teclado desenha o `AnelDeFoco`.
Button {
    id: botao

    property string estilo: "normal"
    property bool pilula: false
    property bool circular: false
    property string icone
    property int tamanhoDoIcone: 16
    property string dica
    // O mnemônico é a primeira letra: sublinhada enquanto o Alt está seguro (o texto é do app, nunca de terceiros).
    property bool sublinharPrimeira: false
    property bool dicaAtiva: hovered
    // Sem o realce do ponteiro (o botão insensível da `main`, que ainda mostra a dica).
    property bool semRealce: false
    property real raio: pilula || circular ? height / 2 : 9
    property real afastamentoDoAnel: estilo === "plano" ? -2 : 1
    // A cor do texto e do ícone; quem precisa de outra (o aviso, branco) a troca.
    property color corDoTexto: estilo === "sugestao" ? Tema.textoDoDestaque : estilo === "destrutivo" ? Tema.destrutivoTexto : Tema.texto

    readonly property bool _soIcone: text === "" && icone !== ""

    hoverEnabled: true
    focusPolicy: Qt.StrongFocus
    Accessible.name: text !== "" ? text : dica
    Keys.onReturnPressed: click()
    Keys.onEnterPressed: click()
    opacity: enabled ? 1 : Tema.opacidadeDesabilitado
    implicitHeight: pilula ? 44 : 34
    implicitWidth: _soIcone ? implicitHeight : Math.max(contentItem.implicitWidth + leftPadding + rightPadding, 34)
    // .text-button 5/17; .image-text 5/9; .pill 10/32.
    leftPadding: pilula ? 32 : _soIcone ? 5 : icone !== "" ? 9 : 17
    rightPadding: leftPadding
    topPadding: 0
    bottomPadding: 0

    contentItem: Item {
        implicitWidth: conteudo.implicitWidth
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
            // Tudo é `currentColor`: a cor do texto do próprio botão, com o alfa do estado.
            if (botao.estilo === "sugestao") return Tema.destaque
            const apertado = botao.down && !botao.semRealce  // o botão insensível da `main` não reage ao aperto
            const ligado = apertado || botao.checked
            const sobre = botao.hovered && !botao.semRealce
            const alfa = botao.estilo === "plano" ? (apertado ? 0.16 : botao.checked ? 0.10 : sobre ? 0.07 : 0)
                : botao.estilo === "destrutivo" ? (ligado ? 0.35 : sobre ? 0.20 : 0.15)
                : (ligado ? 0.30 : sobre ? 0.15 : 0.10)
            return Qt.alpha(botao.corDoTexto, botao.corDoTexto.a * alfa)
        }
        Behavior on color { ColorAnimation { duration: Tema.duracaoCurta; easing { type: Easing.Bezier; bezierCurve: Tema.curva } } }
        // .suggested-action: claro a 10% ao passar, escuro a 20% pressionado.
        Rectangle {
            anchors.fill: parent
            radius: parent.radius
            opacity: botao.estilo === "sugestao" && (botao.hovered || botao.down) ? 1 : 0
            visible: opacity > 0
            color: botao.down ? Qt.rgba(0, 0, 6 / 255, 0.2) : Qt.rgba(1, 1, 1, 0.1)
            Behavior on opacity { NumberAnimation { duration: Tema.duracaoCurta; easing { type: Easing.Bezier; bezierCurve: Tema.curva } } }  // transição de 200 ms
        }
        AnelDeFoco { ativo: botao.visualFocus; raio: parent.radius; afastamento: botao.afastamentoDoAnel }
    }

    Dica { texto: botao.dica; ativa: botao.dicaAtiva }
}
