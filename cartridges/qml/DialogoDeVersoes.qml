import QtQuick
import QtQuick.Controls.Basic

// "Restaurar save": uma linha por versão guardada dos saves do jogo; só desenha, o estado é do `saves`
// (cartridges/modelos/saves.py).
ModalDaRestauracao {
    id: dialogo
    objectName: "dialogoDeVersoes"

    aberto: saves.aberto
    titulo: "Restaurar save"
    largura: 420
    inicial: botaoFechar
    onSaiu: saves.fechar()
    onAbertoChanged: if (aberto) lista.vista.contentY = 0

    ModalDaRestauracao.Cartela {
        id: lista
        width: parent.width
        objetoDaLista: "listaDeVersoes"
        model: saves.versoes

        delegate: LinhaDeAcao {
            id: linha
            required property int index
            required property var modelData
            objectName: "versao-" + modelData.id
            titulo: modelData.titulo
            subtitulo: modelData.subtitulo
            icone: "go-next"
            quebraDoSubtitulo: Text.Wrap
            function click() { botaoDaLinha.click() }
            onAcionada: saves.escolher(modelData.id)

            function irPara(passo) {
                var v = lista.vista
                var alvo = Math.max(0, Math.min(v.count - 1, index + passo))
                v.positionViewAtIndex(alvo, ListView.Contain)
                var item = v.itemAtIndex(alvo)
                if (item) item.botaoDaLinha.forceActiveFocus(Qt.TabFocusReason)
            }
            Keys.onUpPressed: irPara(-1)
            Keys.onDownPressed: irPara(1)
            Keys.onPressed: event => {
                if (event.key === Qt.Key_PageUp) { irPara(-5); event.accepted = true }
                else if (event.key === Qt.Key_PageDown) { irPara(5); event.accepted = true }
            }
        }
    }
}
