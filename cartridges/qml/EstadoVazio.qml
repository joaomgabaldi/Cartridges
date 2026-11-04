import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Shapes

// O aviso de página sem jogos, como o Adw.StatusPage da versão anterior: ícone de 128 px a 55%, título `.title-1`,
// descrição de 12 px e, se houver, o botão em pílula. Espaços de 36, 12 e 36 (CSS 1921-1929).
Item {
    id: estado

    // O nome do ícone simbólico (`data/icones/<nome>-symbolic.svg`), como o `icon-name` da `main`.
    property string icone
    // O ícone simbólico do app (o da `main` em "Nenhum jogo").
    property bool iconeDoApp: false
    property string titulo
    property string descricao
    // Sem texto, não há botão.
    property string rotuloDoBotao
    property bool botaoHabilitado: true
    // O Big Picture usa o aviso em branco sobre o fundo preto.
    property color corDoTitulo: Tema.texto
    property color corDaDescricao: Tema.texto
    property color corDoIcone: Tema.texto
    signal botaoClicado()
    // O controle alcança o botão (a `main` o põe na ordem do foco da página vazia).
    readonly property bool botaoFocado: botao.activeFocus
    function focarBotao() { botao.forceActiveFocus(Qt.TabFocusReason) }
    function acionarBotao() { botao.click() }

    readonly property string nomeDoIcone: icone

    Column {
        anchors.centerIn: parent
        width: Math.min(parent.width - 48, 420)
        spacing: 12

        Item {
            visible: estado.iconeDoApp
            anchors.horizontalCenter: parent.horizontalCenter
            width: 128
            height: 128
            opacity: Tema.opacidadeApagado
            Shape {
                width: 16
                height: 16
                scale: 8
                transformOrigin: Item.TopLeft
                ShapePath {
                    fillColor: estado.corDoIcone
                    strokeColor: "transparent"
                    fillRule: ShapePath.OddEvenFill
                    PathSvg { path: "M3 3C1.89543 3 1 3.89543 1 5V11C1 12.1046 1.89543 13 3 13H13C14.1046 13 15 12.1046 15 11V5C15 3.89543 14.1046 3 13 3H3ZM6 5C5.44772 5 5 5.44772 5 6V10C5 10.5523 5.44772 11 6 11H10C10.5523 11 11 10.5523 11 10V6C11 5.44772 10.5523 5 10 5H6ZM12 8C12 7.44772 12.4477 7 13 7C13.5523 7 14 7.44772 14 8C14 8.55228 13.5523 9 13 9C12.4477 9 12 8.55228 12 8ZM3 7C2.44772 7 2 7.44772 2 8C2 8.55228 2.44772 9 3 9C3.55228 9 4 8.55228 4 8C4 7.44772 3.55228 7 3 7Z" }
                }
            }
        }
        Icone {
            objectName: "iconeDoEstado"
            visible: estado.nomeDoIcone !== "" && !estado.iconeDoApp
            anchors.horizontalCenter: parent.horizontalCenter
            nome: estado.nomeDoIcone
            tamanho: 128
            cor: estado.corDoIcone
            opacity: Tema.opacidadeApagado
        }
        // Do ícone ao título são 36 (12 do espaçamento e 24 daqui); do título à descrição, 12.
        Text {
            width: parent.width
            topPadding: estado.iconeDoApp || estado.nomeDoIcone !== "" ? 24 : 0
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
            textFormat: Text.PlainText
            text: estado.titulo
            color: estado.corDoTitulo
            font { family: Tema.fonte; pixelSize: Tema.titulo1; weight: Tema.pesoTitulo1 }
        }
        Text {
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
            textFormat: Text.PlainText
            text: estado.descricao
            color: estado.corDaDescricao
            font { family: Tema.fonte; pixelSize: Tema.corpo }
        }
        // Da descrição ao botão, 36.
        Item {
            visible: estado.rotuloDoBotao !== ""
            anchors.horizontalCenter: parent.horizontalCenter
            width: botao.width
            height: botao.height + 24
            Botao {
                id: botao
                anchors.bottom: parent.bottom
                estilo: "sugestao"
                pilula: true
                enabled: estado.botaoHabilitado
                text: estado.rotuloDoBotao
                onClicked: estado.botaoClicado()
            }
        }
    }
}
