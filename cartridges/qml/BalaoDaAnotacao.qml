import QtQuick
import QtQuick.Controls.Basic

// O balão do "Onde eu parei": carrega `texto` ao abrir e emite `gravar` ao fechar (só se `editavel`).
// Usado pela página de detalhes e pela tela da sessão.
Popup {
    id: raiz
    property string texto
    property bool editavel: true
    signal gravar(string texto)

    width: 320
    padding: 8
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside
    onAboutToShow: campo.text = raiz.texto
    onOpened: campo.forceActiveFocus()
    onClosed: if (raiz.editavel) raiz.gravar(campo.text)
    background: Rectangle {
        color: Tema.superficie
        border.color: Tema.borda
        radius: 8
    }
    contentItem: ScrollView {
        implicitHeight: 120
        TextArea {
            id: campo
            objectName: "campoDaAnotacao"
            readOnly: !raiz.editavel
            wrapMode: TextEdit.Wrap
            textFormat: TextEdit.PlainText
            color: Tema.texto
            selectionColor: Tema.destaque
            font { family: Tema.fonte; pixelSize: 14 }
            Accessible.name: "Onde eu parei"
        }
    }
}
