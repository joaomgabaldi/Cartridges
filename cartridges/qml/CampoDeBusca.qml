import QtQuick
import QtQuick.Controls.Basic

// O `Gtk.SearchEntry` da `main`: 34 de altura, raio 9, fundo a 10% do texto, a lupa à esquerda (`edit-find`) e, com texto,
// o botão de limpar à direita (`edit-clear`), que limpa e mantém o foco. `textEdited` também sai ao limpar.
TextField {
    id: campo

    placeholderTextColor: Tema.textoSecundario
    color: Tema.texto
    selectionColor: Qt.alpha(Tema.destaque, 0.25)
    selectedTextColor: Tema.texto
    selectByMouse: true
    font { family: Tema.fonte; pixelSize: Tema.corpo }
    verticalAlignment: TextInput.AlignVCenter
    implicitHeight: 34
    // padding 9, o ícone de 16 e 6 de espaço; à direita, o botão de limpar quando há texto.
    leftPadding: 9 + 16 + 6
    rightPadding: text !== "" ? 9 + 16 + 6 : 9
    topPadding: 0
    bottomPadding: 0

    Icone {
        x: 9
        anchors.verticalCenter: parent.verticalCenter
        nome: "edit-find"
        opacity: 0.7
    }
    Icone {
        id: limpar
        objectName: campo.objectName + "Limpar"
        visible: campo.text !== ""
        x: parent.width - width - 9
        anchors.verticalCenter: parent.verticalCenter
        nome: "edit-clear"
        opacity: toqueDoLimpar.pressed ? 0.8 : toqueDoLimpar.containsMouse ? 1 : 0.7
        Accessible.role: Accessible.Button
        Accessible.name: "Limpar"
        MouseArea {
            id: toqueDoLimpar
            anchors.fill: parent
            hoverEnabled: true
            onClicked: { campo.text = ""; campo.textEdited(); campo.forceActiveFocus() }
        }
    }
    background: Rectangle {
        radius: 9
        color: Tema.mistura(0.10)
    }
    AnelDeFoco { ativo: campo.activeFocus; raio: 9; afastamento: -2 }
}
