import QtQuick
import QtQuick.Controls.Basic

// O menu do Tema. Todo menu do app, inclusive os submenus, é um MenuDoTema: o `delegate` e o `background`
// valem só para o menu que os declara.
Menu {
    // Dentro da janela, não numa janela à parte: o menu acompanha a barra sem moldura.
    popupType: Popup.Item
    delegate: ItemDoMenu {}
    background: Rectangle {
        implicitWidth: 220
        color: Tema.superficie
        border.color: Tema.borda
        radius: 8
    }
}
