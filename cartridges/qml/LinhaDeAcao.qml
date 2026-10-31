import QtQuick
import QtQuick.Controls.Basic

// Uma linha com título, subtítulo e, à direita, um glifo ou o rótulo de um botão. A linha inteira aciona
// (como o `activatable-widget` do Adwaita). Os textos vão em PlainText: o subtítulo pode ser um caminho.
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
    property string glifo
    property string rotulo
    property string dica
    // Um segundo botão, à esquerda do rótulo (ex.: "Usar a padrão"); só existe com `rotuloSecundario`.
    property string rotuloSecundario
    property bool secundarioAtivo: true

    // O botão da linha inteira: quem hospeda a linha leva o foco até ele.
    property alias botaoDaLinha: botao

    signal acionada()
    signal secundaria()

    width: parent ? parent.width : implicitWidth
    implicitHeight: Math.max(textos.implicitHeight, 34) + 24

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
        Accessible.name: linha.dica !== "" ? linha.dica : linha.titulo
        Accessible.role: Accessible.Button
        ToolTip.visible: hovered && linha.dica !== ""
        ToolTip.text: linha.dica
        ToolTip.delay: 600
        Keys.onReturnPressed: click()
        Keys.onEnterPressed: click()
        onClicked: linha.acionada()
        contentItem: Item {}
        background: Rectangle {
            radius: 8
            color: botao.down ? Tema.pressionado : botao.hovered ? Tema.botaoSobre : "transparent"
            border { width: botao.visualFocus ? 2 : 0; color: Tema.destaque }
        }
    }

    Column {
        id: textos
        anchors { left: parent.left; leftMargin: 16; right: botaoSecundario.visible ? botaoSecundario.left : lado.left; rightMargin: 12; verticalCenter: parent.verticalCenter }
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
            objectName: linha.objectName + "Subtitulo"
            width: parent.width
            visible: text !== ""
            text: linha.subtitulo
            textFormat: Text.PlainText
            wrapMode: Text.WrapAnywhere
            color: Tema.textoSecundario
            font { family: Tema.fonte; pixelSize: 12 }
        }
    }

    Text {
        id: lado
        anchors { right: parent.right; rightMargin: 16; verticalCenter: parent.verticalCenter }
        text: linha.glifo !== "" ? linha.glifo : linha.rotulo
        textFormat: Text.PlainText
        color: Tema.texto
        font { family: linha.glifo !== "" ? Tema.fonteDeIcones : Tema.fonte; pixelSize: linha.glifo !== "" ? 16 : 14 }
    }

    // Acima do botão da linha inteira (fica depois dele na ordem de pintura).
    Button {
        id: botaoSecundario
        objectName: linha.objectName + "BotaoSecundario"
        visible: linha.rotuloSecundario !== ""
        enabled: linha.secundarioAtivo
        anchors { right: lado.left; rightMargin: 12; verticalCenter: parent.verticalCenter }
        focusPolicy: Qt.StrongFocus
        Accessible.name: linha.rotuloSecundario
        Keys.onReturnPressed: click()
        Keys.onEnterPressed: click()
        onClicked: linha.secundaria()
        contentItem: Text {
            text: linha.rotuloSecundario
            textFormat: Text.PlainText
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            opacity: botaoSecundario.enabled ? 1 : 0.4
            color: Tema.texto
            font { family: Tema.fonte; pixelSize: 14 }
        }
        background: Rectangle {
            radius: 8
            color: botaoSecundario.down ? Tema.pressionado : botaoSecundario.hovered ? Tema.botaoSobre : Tema.barra
            border { width: botaoSecundario.visualFocus ? 2 : 1; color: botaoSecundario.visualFocus ? Tema.destaque : Tema.borda }
        }
    }
}
