import QtQuick
import QtQuick.Controls.Basic

// O popover da libadwaita (popover.menu): raio 15, sombra, 6 de respiro, largura natural (mínimo 120). Todo menu do app,
// inclusive os submenus, é um MenuDoTema: o `delegate` e o `background` valem só para o menu que os declara.
// `setaEm`: o x do centro da seta, em relação ao menu (como o `has-arrow` do GTK); negativo, sem seta.
Menu {
    id: menu

    property real setaEm: -1
    // O Menu não mede os itens: a largura natural é a do maior, recalculada a cada abertura.
    property real larguraDosItens: 0
    function medirItens() {
        var maior = 0
        for (var i = 0; i < count; ++i)
            if (itemAt(i)) maior = Math.max(maior, itemAt(i).implicitWidth)
        larguraDosItens = maior
    }
    onAboutToShow: medirItens()
    Component.onCompleted: medirItens()
    implicitWidth: Math.max(120, larguraDosItens + leftPadding + rightPadding)

    // Dentro da janela, não numa janela à parte: o menu acompanha a barra sem moldura.
    popupType: Popup.Item
    delegate: ItemDoMenu {}
    padding: 6
    overlap: 0
    background: Rectangle {
        implicitWidth: 120
        color: Tema.popover
        radius: 15
        Sombra { camadas: Tema.sombraPopover; raio: 15 }
        Rectangle {
            visible: menu.setaEm >= 0
            x: menu.setaEm - width / 2
            y: -width / 2 + 1
            width: 14
            height: 14
            rotation: 45
            color: Tema.popover
        }
    }
}
