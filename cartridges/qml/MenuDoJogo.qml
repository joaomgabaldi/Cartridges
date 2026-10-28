import QtQuick
import QtQuick.Controls.Basic

// O menu de um jogo. "Editar" entra com o plano 3 e "Restaurar save" com o plano 8.
MenuDoTema {
    id: menu

    // O jogo a que o menu se refere; a grade o troca antes de abrir.
    property string jogoId
    // O modelo da biblioteca (ModeloDaBiblioteca ou o proxy da página).
    property QtObject modelo

    ItemDoMenu {
        objectName: "itemRemover"
        text: "Remover"
        onTriggered: if (menu.modelo) menu.modelo.remover(menu.jogoId)
    }
}
