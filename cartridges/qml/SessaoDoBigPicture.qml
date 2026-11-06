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

    opacity: 0
    visible: opacity > 0

    onMostrarChanged: {
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
        text: sessao.relogio
        textFormat: Text.PlainText
        color: "white"
        font { family: Tema.fonte; pixelSize: Math.round(Tema.titulo1 * 2); weight: Tema.pesoTitulo1; features: { "tnum": 1 } }
    }

    ConquistasDaSessao {
        anchors.horizontalCenter: parent.horizontalCenter
        y: relogio.y + relogio.height + 40
        larguraMaxima: tela.width * 0.6
        visible: conquistasDoJogo.sessao.visivel === true
        animarNovos: tela.mostrar && tela.animar
    }

    Rectangle {
        id: pilula
        objectName: "botaoJaTerminei"
        anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 48 }
        width: rotulo.x + rotulo.width + 28
        height: 44
        radius: height / 2
        color: "white"
        Accessible.role: Accessible.Button
        Accessible.name: "Já terminei de jogar"

        GlifoDoBotao {
            id: glifo
            letra: "A"
            x: 14
            anchors.verticalCenter: parent.verticalCenter
        }
        Text {
            id: rotulo
            x: glifo.x + glifo.width + 10
            anchors.verticalCenter: parent.verticalCenter
            text: "Já terminei de jogar"
            textFormat: Text.PlainText
            color: "black"
            font { family: Tema.fonte; pixelSize: Tema.corpo; weight: Tema.pesoForte }
        }
        TapHandler {
            enabled: tela.mostrar && sessao.emAndamento
            onTapped: sessao.terminar()
        }
    }
}
