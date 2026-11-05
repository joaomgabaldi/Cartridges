import QtQuick
import QtQuick.Controls.Basic

LinhaDoGrupo {
    id: linha

    property alias text: campo.text
    property alias inputMethodHints: campo.inputMethodHints
    property alias echoMode: campo.echoMode
    property bool erro: false
    // Texto de exemplo do campo vazio, visível com o campo em foco (sem foco o título ocupa o lugar).
    property string exemplo
    default property alias acessorios: lado.data

    signal editado()
    signal confirmado()
    // Fim da edição: Enter ou saída do campo (para quem grava o valor só ao terminar, não a cada tecla).
    signal terminado()

    readonly property bool _rotuloEmCima: campo.activeFocus || campo.text !== ""
    // A dica (a regra do campo) só aparece durante a edição ou com erro.
    readonly property bool _dicaVisivel: subtitulo !== "" && (campo.activeFocus || erro)

    comTextos: false
    // Com a dica visível, ela fica sob o campo e a linha cresce.
    alturaMinima: _dicaVisivel ? 70 : 50
    sobre: areaDaLinha.containsMouse && !campo.activeFocus
    foco: campo.activeFocus

    MouseArea {
        id: areaDaLinha
        anchors.fill: parent
        hoverEnabled: true
        onClicked: campo.forceActiveFocus(Qt.MouseFocusReason)
    }

    Item {
        anchors { left: parent.left; leftMargin: 14; right: lado.left; rightMargin: 6; top: parent.top; bottom: parent.bottom }

        Text {
            anchors.left: parent.left
            y: linha._rotuloEmCima ? 10 : (parent.height - height) / 2
            width: parent.width
            text: linha.titulo
            textFormat: Text.PlainText
            elide: Text.ElideRight
            color: linha.erro ? Tema.destrutivoTexto : linha.enabled ? Tema.textoSecundario : Tema.texto
            font { family: Tema.fonte; pixelSize: linha._rotuloEmCima ? Tema.legenda : Tema.corpo }
            Behavior on y { NumberAnimation { duration: Tema.duracaoCurta; easing { type: Easing.Bezier; bezierCurve: Tema.curva } } }
        }
        TextField {
            id: campo
            anchors { left: parent.left; right: parent.right; bottom: parent.bottom; bottomMargin: 9 + (dica.visible ? 20 : 0) }
            focus: true
            padding: 0
            // O estilo Basic soma 4 ao recuo da esquerda: o texto saía 4 px à direita do rótulo.
            leftPadding: 0
            rightPadding: 0
            selectByMouse: true
            placeholderText: linha._rotuloEmCima ? linha.exemplo : ""
            placeholderTextColor: Tema.textoSecundario
            color: linha.erro ? Tema.destrutivoTexto : Tema.texto
            selectionColor: Qt.alpha(Tema.destaque, 0.25)
            selectedTextColor: Tema.texto
            font { family: Tema.fonte; pixelSize: Tema.corpo }
            background: null
            Accessible.name: linha.titulo
            // O foco do teclado ou o dado por código seleciona o texto; o clique só põe o cursor (colar não pode trocar o
            // texto todo).
            onActiveFocusChanged: if (activeFocus && focusReason !== Qt.MouseFocusReason
                && focusReason !== Qt.ActiveWindowFocusReason && focusReason !== Qt.PopupFocusReason) selectAll()
            // Fora de foco o texto longo mostra o começo; no Qt o cursor iria ao fim e cortaria o início.
            onTextChanged: if (!activeFocus) cursorPosition = 0
            onTextEdited: linha.editado()
            onAccepted: linha.confirmado()
            onEditingFinished: linha.terminado()
        }
        Text {
            id: dica
            objectName: linha.objectName + "Subtitulo"
            anchors { left: parent.left; right: parent.right; bottom: parent.bottom; bottomMargin: 9 }
            visible: linha._dicaVisivel
            text: linha.subtitulo
            textFormat: Text.PlainText
            elide: Text.ElideRight
            color: linha.erro ? Tema.destrutivoTexto : Tema.textoSecundario
            font { family: Tema.fonte; pixelSize: Tema.legenda }
        }
    }

    Row {
        id: lado
        anchors { right: lapis.visible ? lapis.left : parent.right; rightMargin: lapis.visible ? 0 : 14; verticalCenter: parent.verticalCenter }
        spacing: 6
    }
    Icone {
        id: lapis
        anchors { right: parent.right; rightMargin: 14; verticalCenter: parent.verticalCenter }
        visible: !campo.activeFocus && lado.children.length === 0
        nome: "document-edit"
        opacity: linha.enabled ? 1 : 0.6
    }
}
