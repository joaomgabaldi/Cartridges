import QtQuick
import QtQuick.Controls.Basic

// Uma linha de Preferências com título, subtítulo e, à direita, o botão "Atualizar". Enquanto o trabalho roda, o botão dá
// lugar ao botão de parar (`podeParar`) ou a um indicador de ocupado; `progressoVisivel` põe a barra e o texto abaixo
// da linha. A linha apagada (`enabled: false`) apaga tudo. Os textos vão em PlainText.
Item {
    id: linha

    // `aparece` é a regra de cada linha (ex.: só com um interruptor ligado); a busca esconde mais, nunca mostra o que a regra esconde.
    // O grupo conta por estas duas propriedades, não pelo `visible` efetivo (que depende do próprio grupo: laço, D58).
    property bool aparece: true
    // Só as linhas das Preferências são buscáveis (`buscavel: true`); as dos assistentes e do editor ignoram a busca.
    // Nas Preferências use `aparece` para a regra da linha, nunca `visible` (um `visible:` de instância desliga o filtro).
    property bool buscavel: false
    readonly property bool passaNoFiltro: !buscavel || BuscaDasPreferencias.passa(linha.titulo, linha.subtitulo)
    visible: aparece && passaNoFiltro

    property string titulo
    property string subtitulo
    property bool emAndamento: false
    property bool podeParar: false
    property bool paradaPedida: false
    property bool progressoVisivel: false
    property real fracao: 0
    property string textoDoProgresso

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

    width: parent ? parent.width : implicitWidth
    implicitHeight: Math.max(textos.implicitHeight, 34) + 24 + (progressoVisivel ? barra.height + legenda.implicitHeight + 20 : 0)
    opacity: enabled ? 1 : 0.5

    Rectangle {
        width: parent.width
        height: 1
        color: Tema.borda
        visible: linha.y > 0
    }

    Column {
        id: textos
        anchors { left: parent.left; leftMargin: 16; right: lado.left; rightMargin: 12; verticalCenter: lado.verticalCenter }
        spacing: 2
        Text {
            width: parent.width
            text: linha.titulo
            textFormat: Text.PlainText
            wrapMode: Text.Wrap
            color: Tema.texto
            font { family: Tema.fonte; pixelSize: 15 }
        }
        Text {
            width: parent.width
            visible: text !== ""
            text: linha.subtitulo
            textFormat: Text.PlainText
            wrapMode: Text.Wrap
            color: Tema.textoSecundario
            font { family: Tema.fonte; pixelSize: 12 }
        }
    }

    Item {
        id: lado
        anchors { right: parent.right; rightMargin: 16; top: parent.top; topMargin: 12 }
        width: Math.max(botao.visible ? botao.width : 0, parar.visible ? parar.width : 0, ocupado.visible ? ocupado.width : 0)
        height: Math.max(textos.implicitHeight, 34)

        Button {
            id: botao
            objectName: linha.objectName + "Botao"
            anchors.verticalCenter: parent.verticalCenter
            visible: !linha.emAndamento
            text: "Atualizar"
            focusPolicy: Qt.StrongFocus
            implicitHeight: 34
            leftPadding: 16
            rightPadding: 16
            Accessible.name: text
            Keys.onReturnPressed: click()
            Keys.onEnterPressed: click()
            onClicked: linha.acionada()
            contentItem: Text {
                text: botao.text
                textFormat: Text.PlainText
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
                color: Tema.texto
                font { family: Tema.fonte; pixelSize: 14 }
            }
            background: Rectangle {
                radius: 6
                color: botao.down ? Tema.pressionado : botao.hovered ? Tema.botaoSobre : Tema.superficie
                border { width: botao.visualFocus ? 2 : 1; color: botao.visualFocus ? Tema.destaque : Tema.borda }
            }
        }

        Button {
            id: parar
            objectName: linha.objectName + "Parar"
            anchors.verticalCenter: parent.verticalCenter
            visible: linha.emAndamento && linha.podeParar
            enabled: !linha.paradaPedida
            focusPolicy: Qt.StrongFocus
            implicitWidth: 34
            implicitHeight: 34
            Accessible.name: "Cancelar"
            ToolTip.visible: hovered
            ToolTip.text: "Cancelar"
            ToolTip.delay: 600
            Keys.onReturnPressed: click()
            Keys.onEnterPressed: click()
            onClicked: linha.parada()
            contentItem: Text {
                text: ""  // parar
                textFormat: Text.PlainText
                horizontalAlignment: Text.AlignHCenter
                verticalAlignment: Text.AlignVCenter
                color: Tema.texto
                opacity: parar.enabled ? 1 : 0.5
                font { family: Tema.fonteDeIcones; pixelSize: 14 }
            }
            background: Rectangle {
                radius: 6
                color: parar.down ? Tema.pressionado : parar.hovered ? Tema.botaoSobre : "transparent"
                border { width: parar.visualFocus ? 2 : 0; color: Tema.destaque }
            }
        }

        BusyIndicator {
            id: ocupado
            objectName: linha.objectName + "Ocupado"
            anchors.verticalCenter: parent.verticalCenter
            visible: linha.emAndamento && !linha.podeParar
            running: visible
            implicitWidth: 24
            implicitHeight: 24
            Accessible.name: "Em andamento"
        }
    }

    // Abaixo da linha, na largura toda: o contador precisa de espaço e a atualização pode durar minutos.
    BarraDeProgresso {
        id: barra
        objectName: linha.objectName + "Progresso"
        anchors { left: parent.left; right: parent.right; margins: 16; top: lado.bottom; topMargin: 12 }
        visible: linha.progressoVisivel
        value: linha.fracao
    }
    Text {
        id: legenda
        objectName: linha.objectName + "ProgressoTexto"
        anchors { horizontalCenter: parent.horizontalCenter; top: barra.bottom; topMargin: 6 }
        visible: linha.progressoVisivel
        text: linha.textoDoProgresso
        textFormat: Text.PlainText
        color: Tema.textoSecundario
        font { family: Tema.fonte; pixelSize: 12 }
    }
}
