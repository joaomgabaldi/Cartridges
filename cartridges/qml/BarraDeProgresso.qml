import QtQuick
import QtQuick.Controls.Basic

// A barra de progresso das conquistas: a trilha apagada e o preenchimento na cor de destaque. `value` vai de 0 a 1.
ProgressBar {
    id: barra

    from: 0
    to: 1
    property color corDaTrilha: Tema.botaoSobre  // a da tela da sessão, sempre escura, não segue o tema

    implicitHeight: 8  // GtkProgressBar: 8 px, raio 99
    background: Rectangle { radius: 4; color: barra.corDaTrilha }
    contentItem: Item {
        Rectangle {
            width: barra.visualPosition * parent.width
            height: parent.height
            radius: 4
            color: Tema.destaque
        }
    }
}
