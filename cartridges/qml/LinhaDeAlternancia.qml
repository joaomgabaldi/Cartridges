import QtQuick
import QtQuick.Controls.Basic

// Uma linha com título, explicação e uma chave liga/desliga, do diálogo de edição.
Item {
    id: linha

    // `aparece` é a regra de cada linha (ex.: só com um interruptor ligado); a busca esconde mais, nunca mostra o que a regra esconde.
    // O grupo conta por estas duas propriedades, não pelo `visible` efetivo (que depende do próprio grupo: laço, D58).
    property bool aparece: true
    // Só as linhas das Preferências são buscáveis (`buscavel: true`); as dos assistentes e do editor ignoram a busca.
    // Nas Preferências use `aparece` para a regra da linha, nunca `visible` (um `visible:` de instância desliga o filtro).
    property bool buscavel: false
    readonly property bool passaNoFiltro: !buscavel || BuscaDasPreferencias.passa(linha.titulo, linha.subtitulo)
    visible: aparece && passaNoFiltro

    property string titulo
    property string subtitulo
    property alias checked: chave.checked

    // A pessoa ligou ou desligou a chave.
    signal alternado()

    width: parent ? parent.width : implicitWidth
    implicitHeight: textos.implicitHeight + 24

    Rectangle {
        width: parent.width
        height: 1
        color: Tema.borda
        visible: linha.y > 0
    }

    Column {
        id: textos
        anchors { left: parent.left; leftMargin: 16; right: chave.left; rightMargin: 12; verticalCenter: parent.verticalCenter }
        spacing: 2
        Text {
            width: parent.width
            text: linha.titulo
            textFormat: Text.PlainText
            wrapMode: Text.Wrap
            color: Tema.texto
            font { family: Tema.fonte; pixelSize: 15 }
        }
        Text {
            width: parent.width
            visible: text !== ""
            text: linha.subtitulo
            textFormat: Text.PlainText
            wrapMode: Text.Wrap
            color: Tema.textoSecundario
            font { family: Tema.fonte; pixelSize: 12 }
        }
        // O clique no texto liga a chave, como na linha do Adwaita.
        TapHandler { onTapped: { chave.forceActiveFocus(Qt.MouseFocusReason); chave.click() } }
    }

    Switch {
        id: chave
        objectName: linha.objectName + "Chave"
        anchors { right: parent.right; rightMargin: 16; verticalCenter: parent.verticalCenter }
        focusPolicy: Qt.StrongFocus
        Accessible.name: linha.titulo
        onToggled: linha.alternado()
        indicator: Rectangle {
            implicitWidth: 44
            implicitHeight: 22
            x: chave.leftPadding
            y: (chave.height - height) / 2
            radius: height / 2
            color: chave.checked ? Tema.destaque : Tema.botaoSobre
            border { width: chave.visualFocus ? 2 : 1; color: chave.visualFocus ? Tema.texto : Tema.borda }
            Rectangle {
                x: chave.checked ? parent.width - width - 3 : 3
                y: 3
                width: parent.height - 6
                height: width
                radius: width / 2
                color: chave.checked ? "white" : Tema.textoSecundario
                Behavior on x { NumberAnimation { duration: Tema.duracaoCurta } }
            }
        }
    }
}
