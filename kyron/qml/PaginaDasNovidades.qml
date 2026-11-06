import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Window

// Os posts do feed, num único cartão de linhas que expandem; o texto do feed é de terceiros e sempre PlainText.
Item {
    id: raiz

    signal voltar()

    readonly property bool menuDoJogoAberto: false
    readonly property bool comLista: novidades.estado === "lista"

    function focarInicial() {
        if (comLista) irPara(Math.max(0, lista.currentIndex))
        else if (novidades.estado === "vazio") vazio.forceActiveFocus(Qt.TabFocusReason)
    }
    function focarGrade() { focarInicial() }
    function focoNaLista() {
        var item = Window.window ? Window.window.activeFocusItem : null
        while (item) {
            if (item === lista) return true
            item = item.parent
        }
        return false
    }
    function mostrarSelecao() {}
    function abrirMenuDoAtual() {}
    function xDoAtual() { return raiz.mapToItem(null, raiz.width / 2, 0).x }
    // Só ↑ e ↓ andam, pelas paradas da lista (cabeçalho de cada linha e, na aberta, o "Abrir no navegador"); devolve se o foco mudou.
    function moverSelecao(dx, dy) {
        if (!comLista) return false
        if (dy === 0) return false
        var foco = Window.window ? Window.window.activeFocusItem : null
        var atual = lista.itemAtIndex(lista.currentIndex)
        if (foco && foco.objectName === "abrirNoNavegador" && dy < 0) { irPara(lista.currentIndex); return true }
        if (dy > 0 && atual && atual.aberta && atual.botaoDoLink.visible && foco === atual.botaoDoCabecalho) {
            atual.botaoDoLink.forceActiveFocus(Qt.TabFocusReason)
            return true
        }
        var i = lista.currentIndex + dy
        if (i < 0 || i >= lista.count) return false
        irPara(i)
        return true
    }
    function irPara(i) {
        lista.currentIndex = i
        lista.positionViewAtIndex(i, ListView.Contain)
        var linha = lista.itemAtIndex(i)
        if (linha) linha.botaoDoCabecalho.forceActiveFocus(Qt.TabFocusReason)
    }
    function abrirDetalhesDoAtual() {
        var foco = Window.window ? Window.window.activeFocusItem : null
        if (foco && foco.click) { foco.click(); return }
        for (var p = foco; p; p = p.parent) {
            if (p.alternar) { p.alternar(); return }
        }
    }

    focus: true
    Keys.onEscapePressed: voltar()

    StackView.onStatusChanged: novidades.paginaVisivel(StackView.status === StackView.Active || StackView.status === StackView.Activating)
    // Depois do foco que a própria StackView dá à página ao ativá-la.
    StackView.onActivated: Qt.callLater(() => focarInicial())

    Rectangle { anchors.fill: parent; color: Tema.fundo; z: -1 }
    // A lista não ocupa a largura toda: sem isto, o clique, a roda e o hover nas margens atravessam até a biblioteca de baixo.
    MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons; hoverEnabled: true; onWheel: wheel => wheel.accepted = true }

    Connections {
        target: novidades
        // A lista refeita volta ao topo e só: o foco não é puxado (o Tab já entra nela).
        function onListaRefeita() { lista.positionViewAtBeginning() }
    }

    BusyIndicator {
        objectName: "carregandoNovidades"
        anchors.centerIn: parent
        visible: novidades.estado === "carregando"
        running: visible
        implicitWidth: 32
        implicitHeight: 32
        Accessible.name: "Carregando"
    }

    EstadoVazio {
        id: vazio
        objectName: "novidadesVazias"
        anchors.fill: parent
        visible: novidades.estado === "vazio"
        icone: "novidades"
        titulo: "Sem novidades"
        descricao: "Não foi possível carregar as novidades."
        rotuloDoBotao: "Tentar novamente"
        onBotaoClicado: novidades.atualizar()
    }

    ListView {
        id: lista
        objectName: "listaDasNovidades"
        width: Math.min(800, parent.width - 24)
        height: parent.height
        anchors.horizontalCenter: parent.horizontalCenter
        visible: raiz.comLista
        model: novidades.posts
        topMargin: 18
        bottomMargin: 18
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        ScrollBar.vertical: BarraDeRolagem {}
        RolagemPorMola { alvo: lista }

        // Filho direto da ListView não entra no contentItem: ficaria parado e acima das linhas (topMargin).
        Rectangle {
            objectName: "cartaoDasNovidades"
            parent: lista.contentItem
            y: lista.originY
            z: -1
            width: lista.width
            height: lista.contentHeight
            radius: 12
            color: Tema.cartao
            Sombra { camadas: Tema.sombraCartao; raio: 12 }
        }

        delegate: LinhaDoGrupo {
            id: linha

            required property int index
            required property var modelData
            readonly property bool expansivel: modelData.resumo !== "" || modelData.url !== ""
            property bool aberta: false
            // A linha expandida mora no `novidades`: a página é destruída ao voltar.
            readonly property string chave: modelData.url + "|" + modelData.titulo
            property bool _pronta: false  // a linha restaurada como aberta nasce aberta, sem animar de fechada
            Component.onCompleted: { aberta = novidades.estaAberta(chave); _pronta = true }
            onAbertaChanged: novidades.definirAberta(chave, aberta)
            readonly property bool _comResumo: modelData.resumo !== ""
            readonly property bool _comLink: modelData.url !== ""
            readonly property real _cabecalho: Math.max(alturaMinima, textosDaLinha.implicitHeight + 12) + 4
            readonly property real _corpo: (_comResumo ? resumoDaLinha.implicitHeight + 24 + 1 : 0) + (_comLink ? 50 + 4 + 1 : 0)

            readonly property alias botaoDoCabecalho: cabecalhoBotao
            readonly property alias botaoDoLink: abrir

            function alternar() { if (expansivel) aberta = !aberta }

            comTextos: false
            implicitHeight: _separador + _cabecalho + (aberta ? _corpo : 0)
            Behavior on implicitHeight { enabled: Tema.animacoes && linha._pronta; NumberAnimation { duration: Tema.duracaoCurta; easing { type: Easing.Bezier; bezierCurve: Tema.curva } } }
            onActiveFocusChanged: if (activeFocus) lista.currentIndex = index
            Keys.onUpPressed: raiz.moverSelecao(0, -1)
            Keys.onDownPressed: raiz.moverSelecao(0, 1)
            Keys.onRightPressed: if (expansivel) aberta = true
            Keys.onLeftPressed: aberta = false

            Rectangle {
                anchors { left: parent.left; right: parent.right; top: parent.top; topMargin: linha._separador }
                height: linha._cabecalho
                topLeftRadius: linha.primeira ? 12 : 0
                topRightRadius: topLeftRadius
                bottomLeftRadius: linha.ultima && !linha.aberta ? 12 : 0
                bottomRightRadius: bottomLeftRadius
                color: cabecalhoBotao.down ? Tema.linhaPressionada : cabecalhoBotao.hovered && linha.expansivel ? Tema.linhaSobre : "transparent"
            }
            Button {
                id: cabecalhoBotao
                objectName: "cabecalhoDaNovidade"
                anchors { left: parent.left; right: parent.right; top: parent.top; topMargin: linha._separador }
                height: linha._cabecalho
                focusPolicy: Qt.StrongFocus
                hoverEnabled: true
                Accessible.role: Accessible.Button
                Accessible.name: linha.modelData.titulo
                Keys.onReturnPressed: linha.alternar()
                Keys.onEnterPressed: linha.alternar()
                onClicked: linha.alternar()
                contentItem: Item {}
                background: Item {}
                HoverHandler { cursorShape: linha.expansivel ? Qt.PointingHandCursor : Qt.ArrowCursor }
                AnelDeFoco { ativo: cabecalhoBotao.visualFocus; raio: 12; afastamento: -2 }
            }
            Column {
                id: textosDaLinha
                anchors {
                    left: parent.left; leftMargin: 14
                    right: parent.right; rightMargin: 14 + (linha.expansivel ? 16 + 12 : 0)
                    top: parent.top; topMargin: linha._separador + (linha._cabecalho - 4 - implicitHeight) / 2 + 2
                }
                spacing: 3
                Text {
                    width: parent.width
                    text: linha.modelData.titulo
                    textFormat: Text.PlainText
                    wrapMode: Text.Wrap
                    lineHeightMode: Text.FixedHeight
                    lineHeight: Tema.alturaDoCorpo
                    color: Tema.texto
                    font { family: Tema.fonte; pixelSize: Tema.corpo }
                }
                Text {
                    width: parent.width
                    visible: text !== ""
                    text: linha.modelData.subtitulo
                    textFormat: Text.PlainText
                    wrapMode: Text.Wrap
                    lineHeightMode: Text.FixedHeight
                    lineHeight: Tema.alturaDaLegenda
                    color: Tema.textoSecundario
                    font { family: Tema.fonte; pixelSize: Tema.legenda }
                }
            }
            Icone {
                visible: linha.expansivel
                anchors { right: parent.right; rightMargin: 14; top: parent.top; topMargin: linha._separador + (linha._cabecalho - height) / 2 }
                nome: "pan-down"
                opacity: Tema.opacidadeApagado
                rotation: linha.aberta ? 180 : 0
                Behavior on rotation { enabled: Tema.animacoes; NumberAnimation { duration: Tema.duracaoCurta; easing { type: Easing.Bezier; bezierCurve: Tema.curva } } }
            }

            Item {
                id: corpoDaLinha
                anchors { left: parent.left; right: parent.right; top: parent.top; topMargin: linha._separador + linha._cabecalho }
                height: Math.max(0, linha.implicitHeight - linha._separador - linha._cabecalho)
                clip: true
                visible: linha.aberta || height > 0

                Rectangle { width: parent.width; height: 1; color: Tema.sombraDoCartao; visible: linha._comResumo || linha._comLink }
                Text {
                    id: resumoDaLinha
                    x: 12
                    y: 1 + 12
                    width: parent.width - 24
                    visible: linha._comResumo
                    text: linha.modelData.resumo
                    textFormat: Text.PlainText
                    wrapMode: Text.Wrap
                    lineHeightMode: Text.FixedHeight
                    lineHeight: Tema.alturaDoCorpo
                    color: Tema.texto
                    font { family: Tema.fonte; pixelSize: Tema.corpo }
                }
                Item {
                    id: linhaDoLink
                    y: 1 + (linha._comResumo ? resumoDaLinha.implicitHeight + 24 : 0)
                    width: parent.width
                    height: 50 + 4
                    visible: linha._comLink
                    Rectangle {
                        anchors { fill: parent; topMargin: linha._comResumo ? 1 : 0 }
                        bottomLeftRadius: linha.ultima ? 12 : 0
                        bottomRightRadius: bottomLeftRadius
                        color: abrir.down ? Tema.linhaPressionada : abrir.hovered ? Tema.linhaSobre : "transparent"
                    }
                    Rectangle { width: parent.width; height: 1; color: Tema.sombraDoCartao; visible: linha._comResumo }
                    Button {
                        id: abrir
                        objectName: "abrirNoNavegador"
                        anchors.fill: parent
                        focusPolicy: Qt.StrongFocus
                        hoverEnabled: true
                        text: "Abrir no navegador"
                        Accessible.name: text
                        Keys.onReturnPressed: click()
                        Keys.onEnterPressed: click()
                        onClicked: novidades.abrirNoNavegador(linha.modelData.url)
                        contentItem: Item {}
                        background: Item {}
                        HoverHandler { cursorShape: Qt.PointingHandCursor }
                        AnelDeFoco { ativo: abrir.visualFocus; raio: 12; afastamento: -2 }
                    }
                    Text {
                        anchors { left: parent.left; leftMargin: 14; verticalCenter: parent.verticalCenter; verticalCenterOffset: 0.5 }
                        text: "Abrir no navegador"
                        textFormat: Text.PlainText
                        color: Tema.texto
                        font { family: Tema.fonte; pixelSize: Tema.corpo }
                    }
                    Icone {
                        anchors { right: parent.right; rightMargin: 14; verticalCenter: parent.verticalCenter }
                        nome: "adw-external-link"
                        cor: Tema.textoSecundario
                    }
                }
            }
        }
    }
}
