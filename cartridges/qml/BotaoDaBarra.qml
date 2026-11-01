import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Shapes
import QtQuick.Window

// Botão de ícone da barra de título (Controls Basic, redesenhado pelo Tema).
ToolButton {
    id: botao

    // Glifo da Segoe Fluent Icons (MDL2 de reserva): E710 adicionar, E700 menu, E721 buscar, E72B voltar.
    property string glifo
    // A Segoe não tem troféu: este botão o desenha (o mesmo desenho do `trofeu-symbolic`).
    property bool trofeu: false
    property string dica
    // O menu deste botão está aberto: a dica sairia por cima dele.
    property bool menuAberto: false
    // Apagado e fora do foco, mas habilitado: um botão desabilitado não recebe hover e a dica (o porquê) não abriria.
    property bool indisponivel: false
    // O ponto de "há novidade" no canto do ícone; nunca recebe o clique (o botão inteiro é o alvo).
    property bool selo: false
    // O WindowAgent da Principal, depois do setup (nulo nos testes).
    readonly property QtObject agente: Window.window && Window.window.agentePronto ? Window.window.agente : null

    implicitWidth: 38
    implicitHeight: 34
    focusPolicy: indisponivel ? Qt.NoFocus : Qt.TabFocus
    opacity: indisponivel ? 0.4 : 1
    Accessible.name: dica
    ToolTip.visible: hovered && dica !== "" && !menuAberto
    ToolTip.text: dica
    ToolTip.delay: 500

    // Sem isto o QWindowKit trata o clique como arrasto da janela.
    function registrar() { if (agente) agente.setHitTestVisible(botao, true) }
    Component.onCompleted: registrar()
    onAgenteChanged: registrar()

    contentItem: Item {
        Rectangle {
            objectName: "seloDoBotao"
            visible: botao.selo
            z: 1
            width: 8
            height: 8
            radius: 4
            color: Tema.destaque
            x: parent.width / 2 + 3
            y: parent.height / 2 - 11
        }
        Text {
            visible: !botao.trofeu
            anchors.centerIn: parent
            text: botao.glifo
            font.family: Tema.fonteDeIcones
            font.pixelSize: 16
            color: Tema.texto
        }
        Shape {
            visible: botao.trofeu
            anchors.centerIn: parent
            width: 16
            height: 16
            scale: 1.1
            ShapePath {
                fillColor: Tema.texto
                strokeColor: "transparent"
                fillRule: ShapePath.WindingFill
                PathSvg { path: "M4 1h8v4.5a4 4 0 0 1-8 0Z" }
                PathSvg { path: "M4 2H2.5A1.5 1.5 0 0 0 1 3.5V4.5A3 3 0 0 0 4 7.5H5V6H4A1.5 1.5 0 0 1 2.5 4.5V3.5H4Z" }
                PathSvg { path: "M12 2H13.5A1.5 1.5 0 0 1 15 3.5V4.5A3 3 0 0 1 12 7.5H11V6H12A1.5 1.5 0 0 0 13.5 4.5V3.5H12Z" }
                PathSvg { path: "M7 9h2v4h-2Z M4 13h8v2h-8Z" }
            }
        }
    }

    background: Rectangle {
        radius: 5
        color: botao.down || botao.checked ? Tema.pressionado : botao.hovered ? Tema.botaoSobre : "transparent"
        border.width: botao.visualFocus ? 2 : 0
        border.color: Tema.destaque
    }
}
