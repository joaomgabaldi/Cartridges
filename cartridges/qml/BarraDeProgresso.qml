import QtQuick
import QtQuick.Controls.Basic

// A barra de progresso (GtkProgressBar): trilha de 8 px e raio 99 a 15% do texto, e o preenchimento na cor de destaque. `value` vai de 0 a 1.
ProgressBar {
    id: barra

    from: 0
    to: 1
    property color corDaTrilha: Tema.botaoSobre  // `currentColor` a 15%; a tela da sessão, sempre escura, passa branco a 15%

    implicitHeight: 8  // GtkProgressBar: 8 px, raio 99
    background: Rectangle { radius: height / 2; color: barra.corDaTrilha }
    contentItem: Item {
        Rectangle {
            width: barra.visualPosition * parent.width
            height: parent.height
            radius: height / 2
            color: Tema.destaque
        }
    }
}
