import QtQuick
import QtQuick.Controls.Basic

// Uma linha de texto do diálogo de edição: o rótulo pequeno em cima, o campo embaixo e, à direita,
// os botões que a linha receber (`acessorios`). O texto vai sempre em PlainText.
FocusScope {
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
    property alias text: campo.text
    property alias inputMethodHints: campo.inputMethodHints
    // Para o que não deve aparecer na tela (TextInput.Password).
    property alias echoMode: campo.echoMode
    // O campo recusado pela validação aparece com o destaque de erro.
    property bool erro: false
    default property alias acessorios: lado.data

    // O texto mudou por ação da pessoa; Enter no campo.
    signal editado()
    signal confirmado()

    width: parent ? parent.width : implicitWidth
    implicitHeight: 58

    // O separador entre as linhas de um grupo.
    Rectangle {
        width: parent.width
        height: 1
        color: Tema.borda
        visible: linha.y > 0
    }

    Column {
        anchors { left: parent.left; leftMargin: 16; right: lado.left; rightMargin: 8; verticalCenter: parent.verticalCenter }
        Text {
            width: parent.width
            text: linha.titulo
            textFormat: Text.PlainText
            elide: Text.ElideRight
            color: linha.erro ? Tema.botaoFechar : Tema.textoSecundario
            font { family: Tema.fonte; pixelSize: 12 }
        }
        TextField {
            id: campo
            width: parent.width
            focus: true
            padding: 0
            topPadding: 2
            selectByMouse: true
            color: Tema.texto
            selectionColor: Tema.destaque
            selectedTextColor: "white"
            font { family: Tema.fonte; pixelSize: 15 }
            background: null
            Accessible.name: linha.titulo
            onTextEdited: linha.editado()
            onAccepted: linha.confirmado()
        }
    }

    Row {
        id: lado
        anchors { right: parent.right; rightMargin: 8; verticalCenter: parent.verticalCenter }
        spacing: 4
    }

    // Um clique em qualquer ponto da linha leva o cursor ao campo.
    TapHandler { onTapped: campo.forceActiveFocus(Qt.MouseFocusReason) }
}
