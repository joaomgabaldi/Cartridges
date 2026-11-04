import QtQuick
import QtQuick.Controls.Basic

// O menu de um jogo. "Restaurar save" só existe para o jogo que tem versões guardadas (lido ao abrir).
MenuDoTema {
    id: menu

    property string jogoId
    property QtObject modelo

    setaEm: width - 17

    signal editar(string jogoId)

    ItemDoMenu {
        objectName: "itemEditar"
        text: "Editar"
        onTriggered: menu.editar(menu.jogoId)
    }
    ItemDoMenu {
        objectName: "itemRemover"
        text: "Remover"
        onTriggered: if (menu.modelo) menu.modelo.remover(menu.jogoId)
    }

    // Lido ao abrir: o backup que termina com o menu aberto só aparece na próxima vez.
    property bool temSave: false
    onAboutToShow: temSave = saves.temBackup(jogoId)
    SeparadorDoMenu {
        visible: menu.temSave
        height: menu.temSave ? implicitHeight : 0
    }
    ItemDoMenu {
        objectName: "itemRestaurarSave"
        visible: menu.temSave
        height: menu.temSave ? implicitHeight : 0
        text: "Restaurar save"
        onTriggered: saves.abrir(menu.jogoId)
    }
}
