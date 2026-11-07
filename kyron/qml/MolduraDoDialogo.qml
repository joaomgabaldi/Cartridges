import QtQuick
import QtQuick.Layouts
import QtQuick.Window

// O diálogo: escurece a janela, mostra o cartão e anima abertura e fechamento com uma mola (massa 1, rigidez 500, amortecimento 0,62).
// `aberto` manda; `visible` continua verdadeiro até o fim da animação de saída. Os filhos usam `Layout.fillWidth`/`Layout.fillHeight`.
FocusScope {
    id: moldura

    property bool aberto: false
    property real largura: 360
    property real altura: 0
    // Janela abaixo de 450x360: vira a folha de baixo (o AlertDialog nunca vira).
    property bool podeSerFolha: true
    property real raio: 15
    property color cor: Tema.fundo
    property bool fechavel: true
    // O controle do Xbox manda ↑/↓: sem isto, o que nenhum controle trata leva o foco ao vizinho do Tab, sem sair do diálogo.
    property bool setasMovemOFoco: false
    // Página rolável: ↑/↓ rolam quando o vizinho do Tab fica fora dela, e PgUp/PgDn rolam sempre.
    property Flickable rolagemDasSetas: null
    property bool altSegurado: false
    property Item focoInicial: null
    property string nomeAcessivel: ""
    default property alias conteudo: coluna.data
    readonly property alias cartao: cartao

    signal fecharPedido()
    signal retornoPerdido()

    property Item retorno: null
    property bool _tecladoEmUso: false
    property bool naPilha: false
    property bool _cobertaAoFechar: false

    // Margens do diálogo flutuante: crescem com a janela. A 795 de altura dão 30.
    readonly property int margemH: Math.floor(30 + 90 * Math.max(0, (width - 720) / 720))
    readonly property int margemV: Math.floor(20 + 100 * Math.max(0, (height - 720) / 720))
    readonly property real _alturaPedida: altura > 0 ? altura : coluna.implicitHeight
    readonly property bool emFolha: podeSerFolha && (width < 450 || height < 360)

    // A mola; ao fechar, para na primeira passagem por 0; ao abrir, passa de 1 e volta.
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
        // O anel só aparece se o teclado já estava em uso; aberto com o mouse, sem anel.
        const motivo = _tecladoEmUso ? Qt.TabFocusReason : Qt.OtherFocusReason
        if (focoInicial && focoInicial.visible && focoInicial.enabled) focoInicial.forceActiveFocus(motivo)
        else moldura.forceActiveFocus()
    }
    function _devolverFoco() {
        if (aberto) return
        const alvo = retorno
        retorno = null
        if (_cobertaAoFechar) return
        // Da pilha, com a outra ainda aberta: o foco é dela.
        const outra = naPilha && parent ? Array.from(parent.children).find(f => f !== moldura && f.naPilha === true && f.aberto && f.visible) : null
        if (outra) { outra.focarInicial(); return }
        if (alvo && alvo !== Window.contentItem && alvo.visible && alvo.enabled) alvo.forceActiveFocus(Qt.TabFocusReason)
        else retornoPerdido()
    }
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
        altSegurado = false
        if (aberto) {
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

    // Alt+Tab tira o foco da janela sem soltar o Alt na moldura: o sublinhado dos mnemônicos não pode ficar preso.
    Connections {
        target: moldura.Window.window
        function onActiveChanged() { if (!moldura.Window.window.active) moldura.altSegurado = false }
    }

    Connections {
        target: moldura.Window.window
        function onActiveFocusItemChanged() {
            const r = moldura.rolagemDasSetas
            const foco = moldura.Window.window.activeFocusItem
            if (!r || !foco || !moldura.visible) return
            let dentro = false
            for (var q = foco; q; q = q.parent) if (q === r.contentItem) { dentro = true; break }
            if (!dentro) return
            const topo = foco.mapToItem(r.contentItem, 0, 0).y
            const base = topo + foco.height
            if (topo < r.contentY) r.contentY = Math.max(0, topo - 8)
            else if (base > r.contentY + r.height) r.contentY = Math.max(0, Math.min(r.contentHeight - r.height, base - r.height + 8))
        }
    }

    property bool pedidoPorTeclado: false
    Keys.onEscapePressed: if (fechavel) { pedidoPorTeclado = true; fecharPedido(); pedidoPorTeclado = false }
    Keys.onReleased: event => { if (event.key === Qt.Key_Alt) altSegurado = false }
    Keys.onPressed: event => {
        if (event.key === Qt.Key_Alt) altSegurado = true
        const r = rolagemDasSetas
        if (r && (event.key === Qt.Key_PageUp || event.key === Qt.Key_PageDown))
            r.contentY = Math.max(0, Math.min(r.contentHeight - r.height, r.contentY + (event.key === Qt.Key_PageUp ? -r.height : r.height)))
        if (setasMovemOFoco && (event.key === Qt.Key_Down || event.key === Qt.Key_Up)) {
            const adiante = event.key === Qt.Key_Down
            const foco = Window.window ? Window.window.activeFocusItem : null
            if (!r) {
                const vizinho = foco ? foco.nextItemInFocusChain(adiante) : null
                if (vizinho && dentro(vizinho)) vizinho.forceActiveFocus(adiante ? Qt.TabFocusReason : Qt.BacktabFocusReason)
            } else {
                // Com página rolável: anda até o primeiro controle de fato abaixo (↓) ou acima (↑) do foco, sem dar a volta; senão, rola a página.
                const yDe = item => item.mapToItem(null, 0, 0).y
                const y0 = foco ? yDe(foco) : 0
                let alvo = foco
                let achou = null
                for (let i = 0; foco && i < 100; ++i) {
                    alvo = alvo.nextItemInFocusChain(adiante)
                    if (!alvo || alvo === foco) break
                    if (dentro(alvo) && (adiante ? yDe(alvo) > y0 + 1 : yDe(alvo) < y0 - 1)) { achou = alvo; break }
                }
                if (achou) achou.forceActiveFocus(adiante ? Qt.TabFocusReason : Qt.BacktabFocusReason)
                else r.contentY = Math.max(0, Math.min(r.contentHeight - r.height, r.contentY + (adiante ? 40 : -40)))
            }
        }
        event.accepted = event.key !== Qt.Key_Tab && event.key !== Qt.Key_Backtab
    }

    // O escurecimento atrás do diálogo; ao fechar, deixa passar o clique. O toque fora do diálogo flutuante não faz nada; na folha de baixo, fecha.
    Rectangle {
        objectName: "esmaecimentoDaMoldura"
        anchors.fill: parent
        color: Tema.esmaecido
        opacity: Math.max(0, Math.min(1, moldura.progresso))
        BloqueioDoFundo {
            enabled: moldura.aberto
            onClicked: if (moldura.emFolha && moldura.fechavel) moldura.fecharPedido()
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
        BloqueioDoFundo {}

        ColumnLayout {
            id: coluna
            anchors.fill: parent
            spacing: 0
        }
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
