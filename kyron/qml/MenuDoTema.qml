import QtQuick
import QtQuick.Controls.Basic

// inclusive os submenus, é um MenuDoTema: o `delegate` e o `background` valem só para o menu que os declara.
// `setaEm`: o x do centro da seta, em relação ao menu; negativo, sem seta.
Menu {
    id: menu

    property real setaEm: -1
    // Menu sob o botão que pode virar: `podeVirar: true` e `y: acima ? -height - 6 : parent.height + 6`.
    // Sem espaço abaixo na janela e com espaço acima, abre acima com a seta embaixo; sem virar, o Qt o
    // empurraria para cima e a seta apontaria para outro item.
    property bool podeVirar: false
    property bool acima: false
    function _cabeAcimaENaoAbaixo() {
        if (!podeVirar || !parent || !parent.Window.window) return false
        var topo = parent.mapToItem(null, 0, 0).y
        return topo + parent.height + 6 + height > parent.Window.height && topo - 6 - height >= 0
    }
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

    popupType: Popup.Item
    delegate: ItemDoMenu {}
    padding: 6
    overlap: 0
    // Use `fechamento` no lugar de `closePolicy`: na animação de saída o menu ainda está visível e CloseOnEscape seguraria os atalhos da janela.
    property int fechamento: Popup.CloseOnEscape | Popup.CloseOnPressOutside
    property bool _saindo: false
    onAboutToHide: _saindo = true
    onAboutToShow: { _saindo = false; medirItens(); acima = _cabeAcimaENaoAbaixo() }
    closePolicy: _saindo ? Popup.NoAutoClose : fechamento
    transformOrigin: acima ? Popup.Bottom : Popup.Top
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
            y: menu.acima ? parent.height - width / 2 - 1 : -width / 2 + 1
            width: 14
            height: 14
            rotation: 45
            color: Tema.popover
        }
    }
}
