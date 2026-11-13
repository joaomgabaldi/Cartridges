import QtQuick
import QtQuick.Controls.Basic

// Menu do botão direito dos campos de texto, no lugar do menu padrão do Qt (em inglês e com o visual do estilo Basic).
// Uso: `ContextMenu.menu: MenuDeTexto { campo: <o TextField ou TextArea> }`.
MenuDoTema {
    id: menu

    required property Item campo

    // Campo de senha (Password, PasswordEchoOnEdit, NoEcho) não deixa o texto sair para a área de transferência.
    readonly property bool _oculto: campo.echoMode !== undefined && campo.echoMode !== TextInput.Normal
    readonly property bool _editavel: !campo.readOnly && campo.enabled
    readonly property bool _temSelecao: campo.selectedText !== ""

    ItemDoMenu {
        objectName: "recortar"
        text: "Recortar"
        enabled: menu._editavel && menu._temSelecao && !menu._oculto
        onTriggered: menu.campo.cut()
    }
    ItemDoMenu {
        objectName: "copiar"
        text: "Copiar"
        enabled: menu._temSelecao && !menu._oculto
        onTriggered: menu.campo.copy()
    }
    ItemDoMenu {
        objectName: "colar"
        text: "Colar"
        enabled: menu._editavel && menu.campo.canPaste
        onTriggered: menu.campo.paste()
    }
    SeparadorDoMenu {}
    ItemDoMenu {
        objectName: "selecionarTudo"
        text: "Selecionar tudo"
        enabled: menu.campo.text !== ""
        onTriggered: menu.campo.selectAll()
    }
}
