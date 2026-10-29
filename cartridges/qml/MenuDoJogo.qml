import QtQuick
import QtQuick.Controls.Basic

// O menu de um jogo. "Restaurar save" entra com o plano 8.
MenuDoTema {
    id: menu

    // O jogo a que o menu se refere; a grade o troca antes de abrir.
    property string jogoId
    // O modelo da biblioteca (ModeloDaBiblioteca ou o proxy da página).
    property QtObject modelo

    // "Editar" só pede: quem abre o diálogo é a janela.
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
}
