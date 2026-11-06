import QtQuick
import QtQuick.Effects

// A capa desfocada do jogo central, cruzada com a anterior; só vale o `image://desfoque/`. Por baixo fica o fundo de sempre.
Item {
    id: fundo
    property string fonte
    property bool animar: true
    readonly property real intensidade: 0.4
    readonly property real saturacao: -0.25
    readonly property real opacidadeVisivel: Math.max(a.opacity, b.opacity)
    property bool frenteEhA: false

    Component.onCompleted: atualizar()
    onFonteChanged: atualizar()
    function atualizar() {
        if (!a || !b) return
        // Lê a `fonte` aqui: um binding `valida` ainda não teria reavaliado quando este handler roda.
        const valida = fonte.startsWith("image://desfoque/")
        const alvo = valida ? (frenteEhA ? b : a) : null
        if (alvo) {
            alvo.source = fonte
            frenteEhA = alvo === a
        }
        a.alvo = valida && frenteEhA ? intensidade : 0
        b.alvo = valida && !frenteEhA ? intensidade : 0
    }

    component Camada: Image {
        property real alvo: 0
        objectName: "imagemDoFundo"
        anchors.fill: parent
        fillMode: Image.PreserveAspectCrop
        asynchronous: false  // provedor Python na thread de imagens trava (D45)
        cache: false
        opacity: alvo
        visible: opacity > 0
        layer.enabled: true
        layer.effect: MultiEffect { saturation: fundo.saturacao }
        Behavior on opacity { enabled: fundo.animar; NumberAnimation { duration: 900 } }
    }
    Camada { id: a }
    Camada { id: b }
}
