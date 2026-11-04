import QtQuick
import QtQuick.Window

Botao {
    dicaSomeAoClicar: false
    id: botao

    property bool menuAberto: false
    // Habilitado, apenas apagado: um botão desabilitado não recebe hover e a dica (o porquê) não abriria.
    property bool indisponivel: false
    property bool selo: false
    readonly property QtObject agente: Window.window && Window.window.agentePronto ? Window.window.agente : null

    estilo: "plano"
    implicitWidth: 34
    implicitHeight: 34
    semRealce: indisponivel
    focusPolicy: indisponivel ? Qt.NoFocus : Qt.TabFocus
    opacity: indisponivel || !enabled ? Tema.opacidadeDesabilitado : 1
    dicaAtiva: hovered && !menuAberto
    Accessible.name: dica

    // Sem isto o QWindowKit trata o clique como arrasto da janela.
    function registrar() { if (agente) agente.setHitTestVisible(botao, true) }
    Component.onCompleted: registrar()
    onAgenteChanged: registrar()

    Rectangle {
        objectName: "seloDoBotao"
        visible: botao.selo
        z: 1
        width: 7
        height: 7
        radius: 3.5
        color: Tema.destaque
        x: (botao.width + botao.tamanhoDoIcone) / 2 - width
        y: (botao.height - botao.tamanhoDoIcone) / 2
        Rectangle {
            anchors { fill: parent; margins: -1.5 }
            z: -1
            radius: width / 2
            color: Tema.barra
        }
    }
}
