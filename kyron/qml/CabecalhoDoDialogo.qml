import QtQuick
import QtQuick.Controls
import QtQuick.Layouts

// O cabeçalho dos diálogos: 47 de altura, título centrado e o X circular; botões da página entram em `inicio` e `fim`.
// `sombra`: a linha quando há rolagem.
Item {
    id: cabecalho

    property string titulo
    property bool comFechar: true
    // Sem o título centrado: a página põe o seu próprio em `inicio`.
    property bool comTitulo: true
    property bool sombra: false
    property alias objetoDoTitulo: textoDoTitulo.objectName
    property alias opacidadeDoTitulo: textoDoTitulo.opacity
    property alias inicio: areaDoInicio.data
    property alias fim: areaDoFim.data
    readonly property alias botaoFechar: botaoFechar

    signal fechar()

    Layout.fillWidth: true
    implicitHeight: 47

    Row {
        id: areaDoInicio
        anchors { left: parent.left; leftMargin: 6; verticalCenter: parent.verticalCenter; verticalCenterOffset: -0.5 }
        spacing: 6
    }

    Text {
        id: textoDoTitulo
        objectName: "tituloDoCabecalho"
        visible: cabecalho.comTitulo
        anchors { centerIn: parent; verticalCenterOffset: -1.5 }
        width: Math.min(implicitWidth, Math.max(0, parent.width - 2 * Math.max(areaDoInicio.width + 12, areaDoFim.width + (botaoFechar.visible ? 41 : 6) + 6)))
        elide: Text.ElideRight
        text: cabecalho.titulo
        textFormat: Text.PlainText
        color: Tema.texto
        font { family: Tema.fonte; pixelSize: Tema.corpo; weight: Tema.pesoForte }
        Behavior on opacity { enabled: Tema.animacoes; NumberAnimation { duration: Tema.duracaoCurta } }
        Accessible.role: Accessible.Heading
        Accessible.name: text
    }

    Row {
        id: areaDoFim
        anchors { right: botaoFechar.visible ? botaoFechar.left : parent.right; rightMargin: botaoFechar.visible ? 0 : 6; verticalCenter: parent.verticalCenter; verticalCenterOffset: -0.5 }
        spacing: 6
    }

    Control {
        id: botaoFechar
        objectName: "fecharDoCabecalho"
        visible: cabecalho.comFechar
        anchors { right: parent.right; rightMargin: 6; verticalCenter: parent.verticalCenter; verticalCenterOffset: -0.5 }
        width: 34
        height: 34
        focusPolicy: Qt.StrongFocus
        Accessible.role: Accessible.Button
        Accessible.name: "Fechar"
        Accessible.onPressAction: cabecalho.fechar()
        Keys.onReturnPressed: cabecalho.fechar()
        Keys.onEnterPressed: cabecalho.fechar()
        Keys.onSpacePressed: cabecalho.fechar()
        Rectangle {
            anchors.centerIn: parent
            width: 24
            height: 24
            radius: 12
            color: area.pressed ? Tema.pressionado : area.containsMouse ? Tema.botaoSobre : Tema.botao
            Behavior on color { ColorAnimation { duration: Tema.duracaoCurta } }
            Icone { anchors.centerIn: parent; nome: "window-close" }
            AnelDeFoco { ativo: botaoFechar.visualFocus; raio: 12 }
        }
        MouseArea {
            id: area
            anchors.fill: parent
            hoverEnabled: true
            onClicked: cabecalho.fechar()
        }
    }

    Rectangle {
        anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
        height: 1
        visible: cabecalho.sombra
        color: Tema.sombraDaBarra
    }
}
