import QtQuick
import QtQuick.Controls.Basic

Button {
    id: botao

    property string icone
    property string dica

    hoverEnabled: true
    focusPolicy: Qt.StrongFocus
    implicitWidth: 34
    implicitHeight: 34
    padding: 0
    Accessible.name: dica
    Keys.onReturnPressed: click()
    Keys.onEnterPressed: click()

    contentItem: Item {
        Icone {
            anchors.centerIn: parent
            nome: botao.icone
            cor: "white"
            opacity: 0.9
        }
    }
    background: Rectangle {
        radius: width / 2
        color: botao.down ? Qt.rgba(0.25, 0.25, 0.25, 0.65) : botao.hovered ? Qt.rgba(0.15, 0.15, 0.15, 0.65) : Qt.rgba(0, 0, 0, 0.65)
        Behavior on color { ColorAnimation { duration: Tema.duracaoCurta } }
        AnelDeFoco { ativo: botao.visualFocus; raio: parent.radius }
    }

    Dica { texto: botao.dica; ativa: botao.hovered; someAoClicar: true }
}
