import QtQuick

// A tela da sessão do Big Picture, sobre o logo (que fica no alto): relógio, conquistas e o "Já terminei de jogar".
// Os textos entram e saem só com fade; a capa é que se move.
Item {
    id: tela
    objectName: "sessaoDoBigPicture"

    property bool mostrar: false
    property bool animar: true
    // Sob o logo na posição "relogio" (`LogoDoBigPicture`).
    readonly property real baseDoLogo: height * 0.18 + 110

    // O que o fade de saída ainda mostra: os rastreadores da sessão já foram limpos, mas o texto some só com fade.
    property string relogioExibido: ""
    property var conquistas: ({})
    function guardarRelogio() { if (sessao.emAndamento) relogioExibido = sessao.relogio }
    function guardarConquistas() { if (sessao.emAndamento) conquistas = conquistasDoJogo.sessao }
    Connections { target: sessao; function onRelogioMudou() { tela.guardarRelogio() } }
    Connections { target: conquistasDoJogo; function onAlterado() { tela.guardarConquistas() } }

    opacity: 0
    visible: opacity > 0

    onMostrarChanged: {
        if (mostrar) {
            relogioExibido = sessao.relogio
            conquistas = conquistasDoJogo.sessao
        }
        aparecer.stop()
        sumir.stop()
        if (!animar) opacity = mostrar ? 1 : 0
        else if (mostrar) aparecer.start()
        else sumir.start()
    }
    SequentialAnimation {
        id: aparecer
        PauseAnimation { duration: 600 }
        NumberAnimation { target: tela; property: "opacity"; to: 1; duration: 500 }
    }
    NumberAnimation { id: sumir; target: tela; property: "opacity"; to: 0; duration: 300 }

    Text {
        id: relogio
        objectName: "relogioDoBigPicture"
        anchors.horizontalCenter: parent.horizontalCenter
        y: tela.baseDoLogo + 24
        text: tela.relogioExibido
        textFormat: Text.PlainText
        color: "white"
        font { family: Tema.fonte; pixelSize: Math.round(Tema.titulo1 * 2); weight: Tema.pesoTitulo1; features: { "tnum": 1 } }
    }

    // Só com o Big Picture à vista: escondido, os ícones das conquistas não são decodificados.
    Loader {
        active: bigPicture.visivel
        anchors.horizontalCenter: parent.horizontalCenter
        y: relogio.y + relogio.height + 40
        visible: tela.conquistas.visivel === true
        sourceComponent: ConquistasDaSessao {
            dados: tela.conquistas
            larguraMaxima: tela.width * 0.6
            animarNovos: tela.mostrar && tela.animar
        }
    }

    BotaoDoBigPicture {
        objectName: "botaoJaTerminei"
        // Acima do aviso "iniciado" (de h-70 a h-24), que é centrado e a cobriria.
        anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 96 }
        texto: "Já terminei de jogar"
        unidade: Math.max(0.85, Math.min(tela.width, tela.height) / 1080)  // em pé, segue a largura, como o Iniciar
        ativo: tela.mostrar && sessao.emAndamento
        onAcionado: sessao.terminar()
    }
}
