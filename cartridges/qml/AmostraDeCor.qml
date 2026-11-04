import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Window

// A amostra em círculo e o balão com o `SeletorDeCor`. No automático (`roda`), a amostra é uma roda de cores com o furo
// transparente, do matiz 0 no topo.
Botao {
    id: amostra

    property color cor
    property bool roda: false
    property string nomeDoBalao: objectName + "Balao"
    property string nomeDoSeletor: objectName + "Seletor"
    property string nomeDaAmostra: objectName + "Cor"
    property string nomeDaRoda: objectName + "Roda"
    readonly property alias balao: balao
    property bool editando: false
    onEditandoChanged: if (editando) Qt.callLater(() => seletor.forceActiveFocus(Qt.TabFocusReason))
    property Item primeiraDaPaleta: null
    readonly property var paleta: [
        ["#99c1f1", "#62a0ea", "#3584e4", "#1c71d8", "#1a5fb4"],
        ["#8ff0a4", "#57e389", "#33d17a", "#2ec27e", "#26a269"],
        ["#f9f06b", "#f8e45c", "#f6d32d", "#f5c211", "#e5a50a"],
        ["#ffbe6f", "#ffa348", "#ff7800", "#e66100", "#c64600"],
        ["#f66151", "#ed333b", "#e01b24", "#c01c28", "#a51d2d"],
        ["#dc8add", "#c061cb", "#9141ac", "#813d9c", "#613583"],
        ["#cdab8f", "#b5835a", "#986a44", "#865e3c", "#63452c"],
        ["#ffffff", "#f6f5f4", "#deddda", "#c0bfbc", "#9a9996"],
        ["#77767b", "#5e5c64", "#3d3846", "#241f31", "#000000"]
    ]

    readonly property var nomesDosTons: {
        const cores = ["Azul", "Verde", "Amarelo", "Laranja", "Vermelho", "Roxo", "Marrom"]
        const tons = [" muito claro", " claro", "", " escuro", " muito escuro"]
        const linhas = cores.map(c => tons.map(t => c + t))
        linhas.push(["Branco", "Cinza claro 1", "Cinza claro 2", "Cinza claro 3", "Cinza claro 4"])
        linhas.push(["Cinza escuro 1", "Cinza escuro 2", "Cinza escuro 3", "Cinza escuro 4", "Preto"])
        return linhas
    }

    // O aperto fora do botão fecha o balão e a soltura não pode reabri-lo: decide pela ordem dos eventos, sem relógio.
    property bool _fechouAgora: false
    property bool _estavaAberto: false
    function apertou() { _estavaAberto = balao.opened || _fechouAgora }
    function alternar() {
        const estava = _estavaAberto
        _estavaAberto = false
        if (!estava) click()
    }

    signal escolhida(color cor)
    signal aberta()
    signal fechada()

    dicaSomeAoClicar: false
    implicitWidth: 34
    implicitHeight: 34
    leftPadding: 0
    rightPadding: 0
    dicaAtiva: hovered && !balao.opened
    onClicked: balao.opened ? balao.close() : balao.open()

    contentItem: Item {
        Rectangle {
            objectName: amostra.nomeDaAmostra
            anchors.centerIn: parent
            width: 22
            height: 22
            radius: 11
            visible: !amostra.roda
            color: amostra.cor
        }
        Canvas {
            objectName: amostra.nomeDaRoda
            anchors.centerIn: parent
            width: 22
            height: 22
            visible: amostra.roda
            onVisibleChanged: if (visible) requestPaint()
            onPaint: {
                // 36 fatias a partir do topo (-90 graus), com sobra de 0,02 rad contra a fresta entre elas; o furo é 35%
                // do raio.
                var c = getContext("2d")
                c.reset()
                var r = width / 2
                for (var i = 0; i < 36; ++i) {
                    var inicio = 2 * Math.PI * i / 36 - Math.PI / 2
                    c.fillStyle = Qt.hsva(i / 36, 1, 1, 1)
                    c.beginPath()
                    c.moveTo(r, r)
                    c.arc(r, r, r, inicio, inicio + 2 * Math.PI / 36 + 0.02, false)
                    c.closePath()
                    c.fill()
                }
                c.globalCompositeOperation = "destination-out"
                c.beginPath()
                c.arc(r, r, r * 0.35, 0, 2 * Math.PI, false)
                c.fill()
            }
        }
    }

    Popup {
        id: balao
        objectName: amostra.nomeDoBalao
        // Sem espaço embaixo do botão, o balão sobe para o outro lado e não cobre a amostra.
        property bool porCima: false
        function recalcularLado() {
            const janela = amostra.Window.height > 0 ? amostra.Window.height : Number.MAX_VALUE
            porCima = amostra.mapToItem(null, 0, amostra.height).y + 6 + implicitHeight + margins > janela
        }
        x: (amostra.width - width) / 2
        y: porCima ? -height - 6 : amostra.height + 6
        padding: 12
        margins: 8  // o balão não sai da janela, mesmo com a linha no pé da rolagem
        closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutsideParent
        enter: null
        exit: null
        // A altura muda com o seletor (45 tons ou o seletor livre): o lado se refaz com o balão aberto.
        Connections { target: amostra; function onEditandoChanged() { if (balao.visible) balao.recalcularLado() } }
        onAboutToShow: {
            amostra.editando = false
            recalcularLado()
            seletor.matiz = Math.max(0, amostra.cor.hsvHue) * 360
            seletor.saturacao = Math.round(amostra.cor.hsvSaturation * 1000)
        }
        onOpened: {
            (primeiraDaPaleta ? primeiraDaPaleta : amostra).forceActiveFocus(Qt.TabFocusReason)
            amostra.aberta()
        }
        onClosed: {
            amostra._fechouAgora = true
            Qt.callLater(() => amostra._fechouAgora = false)
            amostra.forceActiveFocus(Qt.TabFocusReason)
            amostra.fechada()
        }
        background: Rectangle {
            color: Tema.popover
            radius: 15
            Sombra { camadas: Tema.sombraPopover; raio: 15 }
            Rectangle {
                x: parent.width / 2 - width / 2
                y: balao.porCima ? parent.height - width / 2 - 1 : -width / 2 + 1
                width: 14
                height: 14
                rotation: 45
                color: Tema.popover
            }
        }
        contentItem: Item {
            implicitWidth: amostra.editando ? seletor.implicitWidth : paleta.implicitWidth
            implicitHeight: amostra.editando ? seletor.implicitHeight : paleta.implicitHeight

            component Tom: Control {
                id: tom
                property color cor
                property int coluna: -1
                property int linha: -1
                readonly property bool escolhido: Qt.colorEqual(amostra.cor, cor)
                width: 28
                height: 28
                focusPolicy: Qt.StrongFocus
                hoverEnabled: true
                Accessible.role: Accessible.Button
                Accessible.name: coluna >= 0 ? amostra.nomesDosTons[coluna][linha] : ""
                function acionar() { amostra.escolhida(cor) }
                Keys.onReturnPressed: acionar()
                Keys.onEnterPressed: acionar()
                Keys.onSpacePressed: acionar()
                Rectangle {
                    anchors.fill: parent
                    radius: 6
                    color: tom.cor
                    border { width: 1; color: Qt.rgba(0, 0, 6 / 255, 0.15) }
                    Rectangle {
                        anchors.fill: parent
                        radius: parent.radius
                        color: Qt.rgba(1, 1, 1, 0.15)
                        visible: tom.hovered
                    }
                    Icone {
                        anchors.centerIn: parent
                        visible: tom.escolhido
                        nome: "object-select"
                        cor: tom.cor.hslLightness > 0.6 ? "#000000" : "#ffffff"
                    }
                    AnelDeFoco { ativo: tom.visualFocus; raio: 6; afastamento: 1 }
                }
                MouseArea { anchors.fill: parent; onClicked: tom.acionar() }
            }

            Column {
                id: paleta
                visible: !amostra.editando
                spacing: 12
                Grid {
                    id: grade
                    columns: 9
                    spacing: 6
                    Repeater {
                        id: repetidorDaGrade
                        model: 45
                        Tom {
                            required property int index
                            id: tomDaGrade
                            coluna: index % 9
                            linha: Math.floor(index / 9)
                            cor: amostra.paleta[coluna][linha]
                            Component.onCompleted: if (index === 0) primeiraDaPaleta = tomDaGrade
                            Keys.onLeftPressed: repetidorDaGrade.itemAt(Math.max(0, index - 1)).forceActiveFocus(Qt.TabFocusReason)
                            Keys.onRightPressed: repetidorDaGrade.itemAt(Math.min(44, index + 1)).forceActiveFocus(Qt.TabFocusReason)
                            Keys.onUpPressed: repetidorDaGrade.itemAt(Math.max(0, index - 9)).forceActiveFocus(Qt.TabFocusReason)
                            Keys.onDownPressed: repetidorDaGrade.itemAt(Math.min(44, index + 9)).forceActiveFocus(Qt.TabFocusReason)
                        }
                    }
                }
                Column {
                    spacing: 6
                    Text {
                        text: "Personalizada"
                        textFormat: Text.PlainText
                        color: Tema.textoSecundario
                        font { family: Tema.fonte; pixelSize: Tema.corpo }
                    }
                    Control {
                        id: maisCor
                        objectName: amostra.objectName + "Mais"
                        width: 28
                        height: 28
                        focusPolicy: Qt.StrongFocus
                        hoverEnabled: true
                        Accessible.role: Accessible.Button
                        Accessible.name: "Cor personalizada"
                        Keys.onReturnPressed: amostra.editando = true
                        Keys.onEnterPressed: amostra.editando = true
                        Keys.onSpacePressed: amostra.editando = true
                        Rectangle {
                            anchors.fill: parent
                            radius: 6
                            color: Tema.mistura(maisCor.hovered ? 0.15 : 0.10)
                            Icone { anchors.centerIn: parent; nome: "list-add" }
                            AnelDeFoco { ativo: maisCor.visualFocus; raio: 6; afastamento: 1 }
                        }
                        MouseArea { anchors.fill: parent; onClicked: amostra.editando = true }
                    }
                }
            }

            SeletorDeCor {
                id: seletor
                objectName: amostra.nomeDoSeletor
                visible: amostra.editando
                onEscolhida: cor => amostra.escolhida(cor)
            }
        }
    }
}
