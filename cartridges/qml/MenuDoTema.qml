import QtQuick
import QtQuick.Controls.Basic

// O popover dos menus: raio 15, sombra, 6 de respiro, largura natural (mínimo 120). Todo menu do app,
// inclusive os submenus, é um MenuDoTema: o `delegate` e o `background` valem só para o menu que os declara.
// `setaEm`: o x do centro da seta, em relação ao menu; negativo, sem seta.
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
    Component.onCompleted: medirItens()
    implicitWidth: Math.max(120, larguraDosItens + leftPadding + rightPadding)

    // Dentro da janela, não numa janela à parte: o menu acompanha a barra sem moldura.
    popupType: Popup.Item
    delegate: ItemDoMenu {}
    padding: 6
    overlap: 0
    // Use `fechamento` no lugar de `closePolicy`. Na animação de saída o menu ainda está visível, e um popup com
    // CloseOnEscape segura os atalhos da janela: o Alt fecha o menu e o Alt+← logo depois não voltaria a página.
    property int fechamento: Popup.CloseOnEscape | Popup.CloseOnPressOutside
    property bool _saindo: false
    onAboutToHide: _saindo = true
    onAboutToShow: { _saindo = false; medirItens() }
    closePolicy: _saindo ? Popup.NoAutoClose : fechamento
    // Abre e fecha com um leve esmaecer e crescer a partir da seta.
    transformOrigin: Popup.Top
    enter: Transition {
        NumberAnimation { property: "opacity"; from: 0; to: 1; duration: Tema.animacoes ? 100 : 0; easing.type: Easing.OutCubic }
        NumberAnimation { property: "scale"; from: 0.94; to: 1; duration: Tema.animacoes ? 100 : 0; easing.type: Easing.OutCubic }
    }
    exit: Transition {
        NumberAnimation { property: "opacity"; from: 1; to: 0; duration: Tema.animacoes ? 100 : 0; easing.type: Easing.InCubic }
        NumberAnimation { property: "scale"; from: 1; to: 0.94; duration: Tema.animacoes ? 100 : 0; easing.type: Easing.InCubic }
    }
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
