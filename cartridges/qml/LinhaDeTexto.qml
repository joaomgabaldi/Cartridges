import QtQuick
import QtQuick.Controls.Basic

// O `Adw.EntryRow`: o título é o rótulo dentro do campo, que encolhe ao focar ou preencher; lápis à direita enquanto não
// edita, os botões que a linha receber (`acessorios`) e o contorno de destaque com o foco. O texto vai sempre em PlainText.
LinhaDoGrupo {
    id: linha

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

    readonly property bool _rotuloEmCima: campo.activeFocus || campo.text !== ""

    comTextos: false
    alturaMinima: 50
    sobre: areaDaLinha.containsMouse && !campo.activeFocus
    foco: campo.activeFocus

    // Um clique em qualquer ponto da linha leva o cursor ao campo.
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
            // Em cima (legenda) ou no meio da linha (corpo), com a transição da libadwaita.
            y: linha._rotuloEmCima ? 10 : (parent.height - height) / 2
            width: parent.width
            text: linha.titulo
            textFormat: Text.PlainText
            elide: Text.ElideRight
            color: linha.erro ? Tema.destrutivoTexto : Tema.textoSecundario
            font { family: Tema.fonte; pixelSize: linha._rotuloEmCima ? Tema.legenda : Tema.corpo }
            Behavior on y { NumberAnimation { duration: Tema.duracaoCurta; easing { type: Easing.Bezier; bezierCurve: Tema.curva } } }
        }
        TextField {
            id: campo
            anchors { left: parent.left; right: parent.right; bottom: parent.bottom; bottomMargin: 9 }
            focus: true
            padding: 0
            selectByMouse: true
            color: linha.erro ? Tema.destrutivoTexto : Tema.texto
            selectionColor: Qt.alpha(Tema.destaque, 0.25)
            selectedTextColor: Tema.texto
            font { family: Tema.fonte; pixelSize: Tema.corpo }
            background: null
            Accessible.name: linha.titulo
            onTextEdited: linha.editado()
            onAccepted: linha.confirmado()
        }
    }

    // Os acessórios à direita e o lápis (.edit-icon: 24 + 5 de respiro).
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
    }
}
