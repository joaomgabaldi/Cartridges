import QtQuick
import QtQuick.Layouts
import QtQuick.Window

// O Adw.Dialog: escurece a janela inteira (barra de título incluída), mostra o cartão com raio 15, sombra e contorno, e
// anima a abertura e o fechamento com a mola da libadwaita (medida na DLL 1.10: massa 1, rigidez 500, amortecimento 0,62;
// escala 0,8 + 0,2p; opacidade p até 1). Medidas, API e exemplos: `docs/auditoria-gtk-qt/COMPONENTES.md`.
//
// `aberto` manda; `visible` continua verdadeiro até o fim da animação de saída. O conteúdo é um ColumnLayout: os filhos
// usam `Layout.fillWidth`/`Layout.fillHeight`. O foco vai ao `focoInicial` ao abrir e volta a quem o tinha ao fechar.
FocusScope {
    id: moldura

    property bool aberto: false
    // content-width e content-height; `altura` 0 acompanha o conteúdo. Ambas encolhem para caber na janela.
    property real largura: 360
    property real altura: 0
    // Janela abaixo de 450x360 (medido na `main`): vira a folha de baixo (bottom sheet). O AlertDialog nunca vira.
    property bool podeSerFolha: true
    property real raio: 15
    property color cor: Tema.fundo
    // Sem `fechavel`, nem o Esc nem o toque fora pedem o fechamento (`can-close` falso).
    property bool fechavel: true
    property Item focoInicial: null
    property string nomeAcessivel: ""
    default property alias conteudo: coluna.data
    readonly property alias cartao: cartao

    // Esc, o X do cabeçalho (ligado por quem usa) ou o toque fora na folha de baixo: quem usa decide e põe `aberto: false`.
    signal fecharPedido()
    // Quem tinha o foco ao abrir sumiu: a janela decide para onde ele vai.
    signal retornoPerdido()

    property Item retorno: null
    property bool _tecladoEmUso: false
    property bool _cobertaAoFechar: false

    // Margens do adw-floating-sheet: crescem com a janela. A 795 de altura dão 30 (medido no gabarito).
    readonly property int margemH: Math.floor(30 + 90 * Math.max(0, (width - 720) / 720))
    readonly property int margemV: Math.floor(20 + 100 * Math.max(0, (height - 720) / 720))
    readonly property real _alturaPedida: altura > 0 ? altura : coluna.implicitHeight
    readonly property bool emFolha: podeSerFolha && (width < 450 || height < 360)

    // A mola. `_t` é o tempo em segundos; ao fechar, para na primeira passagem por 0 (`clamp`); ao abrir, passa de 1 e volta.
    property real _de: 0
    property real _para: 0
    property real _t: 0
    readonly property real progresso: _de + (_para - _de) * _mola(_t)
    function _mola(t) {
        const w0 = Math.sqrt(500), z = 0.62, wd = w0 * Math.sqrt(1 - z * z)
        return 1 - Math.exp(-z * w0 * t) * (Math.cos(wd * t) + z * w0 / wd * Math.sin(wd * t))
    }
    NumberAnimation {
        id: relogio
        target: moldura
        property: "_t"
        from: 0
        easing.type: Easing.Linear
        onFinished: moldura._assentar()
    }
    function _animar() {
        relogio.stop()
        _de = progresso
        _para = aberto ? 1 : 0
        _t = 0
        if (!Tema.animacoes || !Window.window) { _assentar(); return }
        // Abrindo: até assentar a 1% (epsilon da DLL). Fechando: a primeira passagem pelo alvo.
        relogio.to = aberto ? 0.33 : 0.1277
        relogio.duration = relogio.to * 1000
        relogio.start()
    }
    function _assentar() {
        _de = _para
        _t = 0
        if (!aberto) visible = false
    }

    function dentro(item) {
        for (var p = item; p; p = p.parent)
            if (p === moldura) return true
        return false
    }
    function focarInicial() {
        if (!aberto) return
        // O anel só aparece se o teclado já estava em uso (`focus-visible` do GTK); aberto com o mouse, sem anel.
        const motivo = _tecladoEmUso ? Qt.TabFocusReason : Qt.OtherFocusReason
        if (focoInicial && focoInicial.visible && focoInicial.enabled) focoInicial.forceActiveFocus(motivo)
        else moldura.forceActiveFocus()
    }
    function _devolverFoco() {
        if (aberto) return
        const alvo = retorno
        retorno = null
        // Fechou um diálogo coberto (a pilha): o foco é do de cima e fica com ele.
        if (_cobertaAoFechar) return
        if (alvo && alvo !== Window.contentItem && alvo.visible && alvo.enabled) alvo.forceActiveFocus(Qt.TabFocusReason)
        else retornoPerdido()
    }
    // Cobre a janela inteira, de onde quer que tenha sido declarada (uma página fica abaixo da barra).
    function _cobrir() {
        if (!parent) return
        const origem = parent.mapToItem(null, 0, 0)
        x = -origem.x
        y = -origem.y
    }

    Accessible.role: Accessible.Dialog
    Accessible.name: nomeAcessivel
    x: 0
    y: 0
    width: Window.width > 0 ? Window.width : (parent ? parent.width : 0)
    height: Window.height > 0 ? Window.height : (parent ? parent.height : 0)
    z: 10
    visible: false
    focus: visible

    // Declarada dentro de um cartão que se move com a janela (as Preferências), a origem muda a cada redimensionamento.
    onWidthChanged: if (visible) Qt.callLater(_cobrir)
    onHeightChanged: if (visible) Qt.callLater(_cobrir)

    onAbertoChanged: {
        if (aberto) {
            // Reaberto no meio da saída, ou com o foco em lugar nenhum: o retorno de antes continua valendo.
            const foco = Window.window ? Window.window.activeFocusItem : null
            if (foco && foco !== Window.contentItem && !dentro(foco)) retorno = foco
            _tecladoEmUso = !!foco && foco.visualFocus === true
            _cobrir()
            visible = true
            // Adiado: o item acabou de ficar visível e só então aceita o foco.
            Qt.callLater(focarInicial)
        } else {
            const foco = Window.window ? Window.window.activeFocusItem : null
            _cobertaAoFechar = !!foco && foco !== Window.contentItem && !dentro(foco)
            Qt.callLater(_devolverFoco)
        }
        _animar()
    }
    Component.onCompleted: if (aberto) { visible = true; _animar() }

    Keys.onEscapePressed: if (fechavel) fecharPedido()
    // Modal para o teclado e o controle: nenhuma tecla chega à página de trás. O Tab passa, para circular.
    Keys.onPressed: event => event.accepted = event.key !== Qt.Key_Tab && event.key !== Qt.Key_Backtab

    // floating-sheet > dimming. Ao fechar, deixa passar o clique (`can-target` falso, como na DLL). A `main` segura o toque
    // fora do diálogo flutuante (`dialog_backdrop.py`): nem fecha nem arrasta. Na folha de baixo, fecha.
    Rectangle {
        anchors.fill: parent
        color: Tema.esmaecido
        opacity: Math.max(0, Math.min(1, moldura.progresso))
        MouseArea {
            anchors.fill: parent
            enabled: moldura.aberto
            acceptedButtons: Qt.AllButtons
            onClicked: if (moldura.emFolha && moldura.fechavel) moldura.fecharPedido()
            onWheel: wheel => wheel.accepted = true
        }
    }

    Rectangle {
        id: cartao
        objectName: "cartaoDoDialogo"
        readonly property real _larguraBase: Math.min(moldura.largura, moldura.emFolha ? moldura.width : moldura.width - 2 * moldura.margemH)
        readonly property real _alturaBase: Math.min(moldura._alturaPedida, moldura.emFolha ? moldura.height - 30 : moldura.height - 2 * moldura.margemV)
        x: Math.round((moldura.width - width) / 2)
        y: moldura.emFolha ? moldura.height - height + (1 - moldura.progresso) * height : Math.round((moldura.height - height) / 2)
        width: _larguraBase
        height: _alturaBase
        radius: moldura.raio
        color: moldura.cor
        enabled: moldura.aberto
        opacity: Math.max(0, Math.min(1, moldura.progresso))
        scale: moldura.emFolha ? 1 : 0.8 + 0.2 * moldura.progresso

        Sombra { camadas: Tema.sombraDialogo; raio: moldura.raio }
        // Os cliques no cartão não vão para o fundo (que, na folha de baixo, fecharia).
        MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons; onWheel: wheel => wheel.accepted = true }

        ColumnLayout {
            id: coluna
            anchors.fill: parent
            spacing: 0
        }
        // outline: 1px solid rgba(255,255,255,.07); outline-offset: -1px.
        Rectangle {
            anchors.fill: parent
            z: 20
            enabled: false
            radius: moldura.raio
            color: "transparent"
            border { width: 1; color: Tema.contorno }
        }
    }
}
