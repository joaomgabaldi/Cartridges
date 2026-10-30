import QtQuick
import QtQuick.Controls.Basic

// Uma linha que é só um botão com o título centralizado (o `Adw.ButtonRow`); `destrutivo` pinta de erro.
Item {
    id: linha

    // `aparece` é a regra de cada linha (ex.: só com um interruptor ligado); a busca esconde mais, nunca mostra o que a regra esconde.
    // O grupo conta por estas duas propriedades, não pelo `visible` efetivo (que depende do próprio grupo: laço, D58).
    property bool aparece: true
    // Só as linhas das Preferências são buscáveis (`buscavel: true`); as dos assistentes e do editor ignoram a busca.
    // Nas Preferências use `aparece` para a regra da linha, nunca `visible` (um `visible:` de instância desliga o filtro).
    property bool buscavel: false
    readonly property bool passaNoFiltro: !buscavel || BuscaDasPreferencias.passa(linha.titulo, "")
    visible: aparece && passaNoFiltro

    property string titulo
    property bool destrutivo: false

    signal acionada()

    width: parent ? parent.width : implicitWidth
    implicitHeight: 48

    Rectangle {
        width: parent.width
        height: 1
        color: Tema.borda
        visible: linha.y > 0
    }

    Button {
        id: botao
        objectName: linha.objectName + "Botao"
        anchors.fill: parent
        focusPolicy: Qt.StrongFocus
        Accessible.name: linha.titulo
        Keys.onReturnPressed: click()
        Keys.onEnterPressed: click()
        onClicked: linha.acionada()
        contentItem: Text {
            text: linha.titulo
            textFormat: Text.PlainText
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            color: linha.destrutivo ? Tema.erro : Tema.texto
            font { family: Tema.fonte; pixelSize: 15 }
        }
        background: Rectangle {
            radius: 8
            color: botao.down ? Tema.pressionado : botao.hovered ? Tema.botaoSobre : "transparent"
            border { width: botao.visualFocus ? 2 : 0; color: Tema.destaque }
        }
    }
}
