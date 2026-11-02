import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Window

// Uma linha de Preferências com título, subtítulo e, à direita, o botão "Atualizar" (a `Adw.ActionRow` com a `Stack` da
// `main`). Enquanto o trabalho roda, o botão dá lugar ao botão plano de parar (`podeParar`) ou ao `Adw.Spinner`. A barra de
// progresso fica fora da linha (um grupo abaixo do cartão): quem usa a desenha. A linha apagada (`enabled: false`) apaga tudo.
LinhaDoGrupo {
    id: linha

    property bool emAndamento: false
    property bool podeParar: false
    property bool paradaPedida: false

    signal acionada()
    signal parada()

    // O foco acompanha a troca do botão: o "Atualizar" some ao começar (o foco ficaria num item invisível e o Esc
    // deixaria de chegar ao diálogo). Vai ao "parar" ou, sem ele, à própria linha (que continua sob o diálogo); ao
    // terminar, volta ao "Atualizar".
    property bool _focoVeioDoBotao: false
    property bool _focoNaLinha: false  // o foco já foi entregue ao "parar" (ou à linha)
    function _dentro(item) {
        for (var p = item; p; p = p.parent) // `parent`: o `parentItem` do C++ não existe no QML
            if (p === linha) return true
        return false
    }
    onEmAndamentoChanged: {
        if (emAndamento && botao.activeFocus) {
            _focoVeioDoBotao = true
            Qt.callLater(() => {
                var alvo = linha.podeParar ? parar : linha
                if (linha.emAndamento && linha._focoVeioDoBotao && alvo.visible) {
                    alvo.forceActiveFocus(Qt.TabFocusReason)
                    linha._focoNaLinha = true
                }
            })
        } else if (!emAndamento && _focoVeioDoBotao) {
            _focoVeioDoBotao = false
            _focoNaLinha = false
            Qt.callLater(() => botao.forceActiveFocus(Qt.TabFocusReason))
        }
    }
    // Se a pessoa levou o foco para outro lugar durante a atualização, ele fica onde ela o deixou.
    Connections {
        target: linha.Window.window
        function onActiveFocusItemChanged() {
            var foco = linha.Window.window.activeFocusItem
            if (linha._focoNaLinha && foco && !linha._dentro(foco)) { linha._focoVeioDoBotao = false; linha._focoNaLinha = false }
        }
    }

    reservaADireita: lado.width

    Item {
        id: lado
        anchors { right: parent.right; rightMargin: 14; verticalCenter: parent.verticalCenter }
        width: Math.max(botao.visible ? botao.width : 0, parar.visible ? parar.width : 0, ocupado.visible ? ocupado.width : 0)
        height: 34

        Botao {
            id: botao
            objectName: linha.objectName + "Botao"
            anchors.verticalCenter: parent.verticalCenter
            visible: !linha.emAndamento
            text: "Atualizar"
            onClicked: linha.acionada()
        }

        Botao {
            id: parar
            objectName: linha.objectName + "Parar"
            anchors.verticalCenter: parent.verticalCenter
            visible: linha.emAndamento && linha.podeParar
            enabled: !linha.paradaPedida
            estilo: "plano"
            icone: "process-stop"
            dica: "Cancelar"
            onClicked: linha.parada()
        }

        Girador {
            id: ocupado
            objectName: linha.objectName + "Ocupado"
            anchors.verticalCenter: parent.verticalCenter
            visible: linha.emAndamento && !linha.podeParar
            running: visible
            width: 32
            height: 32
            Accessible.name: "Em andamento"
        }
    }
}
