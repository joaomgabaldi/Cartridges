import QtQuick
import QtQuick.Window

// Botão de ícone da barra de título: plano, 34x34, raio 9. `icone` é o nome em `data/icones`; `dica` é o tooltip.
Botao {
    dicaSomeAoClicar: false
    id: botao

    // O menu deste botão está aberto: a dica sairia por cima dele.
    property bool menuAberto: false
    // Apagado e fora do foco, mas habilitado: um botão desabilitado não recebe hover e a dica (o porquê) não abriria.
    property bool indisponivel: false
    // O ponto de "há novidade" no canto do ícone; nunca recebe o clique (o botão inteiro é o alvo).
    property bool selo: false
    // O WindowAgent da Principal, depois do setup (nulo nos testes).
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

    // .news-badge: 7x7, destaque, anel de 1,5 px na cor da headerbar, no canto superior direito do ícone.
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
