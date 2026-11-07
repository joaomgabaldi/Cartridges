import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Shapes

// Uma página de jogos: "Todos os jogos" (com busca) ou "Jogos Zerados".
Item {
    id: raiz

    property QtObject pagina
    property bool comBusca: false
    property bool buscaAberta: false
    property bool ativa: true
    signal abrirDetalhes(string jogoId)
    signal editar(string jogoId)
    signal voltar()

    readonly property bool vazioComBotao: grade.count === 0 && aviso.visible && aviso.rotuloDoBotao !== ""
    function focarGrade() { if (vazioComBotao) aviso.focarBotao(); else grade.forceActiveFocus() }
    function fecharMenuDoJogo() { grade.fecharMenu() }
    function focarJogo(jogoId) { grade.focarJogo(jogoId) }
    function marcarTeclado() { grade.marcarTeclado() }

    readonly property bool menuDoJogoAberto: grade.menuAberto
    // Com a grade rolada, a barra de título mostra a linha de baixo; com a busca aberta, a linha fica sob ela (só uma, nunca duas).
    readonly property bool buscaVisivel: comBusca && buscaAberta
    readonly property bool rolado: grade.rolado && !buscaVisivel
    // Devolve se o passo tem onde acontecer aqui.
    function moverSelecao(dx, dy) {
        if (campo.activeFocus) {
            if (dy <= 0) return false
            grade.porTeclado = true
            grade.forceActiveFocus()
            return true
        }
        if (grade.count === 0) {
            if (dy <= 0 || !aviso.visible || aviso.rotuloDoBotao === "" || aviso.botaoFocado) return false
            aviso.focarBotao()
            return true
        }
        // A grade responde que andou mesmo contra a parede (o toque é o de passar): só ↑ na primeira linha sai.
        return grade.moverSelecao(dx, dy) || dy >= 0
    }
    function xDoAtual() {
        return grade.currentItem ? grade.currentItem.mapToItem(null, grade.currentItem.width / 2, 0).x : 0
    }
    // Um controle apareceu: acende a seleção sem tirar o foco de quem digita; fora da grade, vai ao primeiro jogo.
    function mostrarSelecao() {
        if (buscaAberta) return false
        if (vazioComBotao) { aviso.focarBotao(); return false }
        const foraDaGrade = !grade.activeFocus && grade.count > 0
        grade.porTeclado = true
        if (foraDaGrade) { grade.currentIndex = 0; grade.rolarAte(0) }
        grade.forceActiveFocus()
        return foraDaGrade
    }
    function abrirMenuDoAtual() {
        if (!grade.activeFocus) return
        grade.porTeclado = true
        if (grade.currentItem) grade.currentItem.abrirMenu()
    }
    function abrirDetalhesDoAtual() {
        if (aviso.botaoFocado) { aviso.acionarBotao(); return }
        if (campo.activeFocus) { campo.accepted(); return }
        grade.porTeclado = true
        grade.forceActiveFocus()
        grade.abrirDoAtual()
    }
    function alternarBusca() { buscaAberta = !buscaAberta }

    // Digitar com o foco na grade ou num botão da barra abre a busca (só em "Todos os jogos"). Espaço não conta: aciona o botão ou o cartão.
    function capturar(event) {
        if (event.key === Qt.Key_Escape) {
            if (buscaAberta) { buscaAberta = false; return true }
            if (!comBusca) { voltar(); return true }
            return false
        }
        if (!comBusca || !ativa || event.key === Qt.Key_Space || event.text.length === 0 || event.text < " "
            || event.text === "\u007f" || (event.modifiers & (Qt.ControlModifier | Qt.AltModifier)))
            return false
        buscaAberta = true
        campo.forceActiveFocus()
        campo.text += event.text
        return true
    }
    Keys.onPressed: event => { if (capturar(event)) event.accepted = true }

    onBuscaAbertaChanged: {
        if (buscaAberta) {
            campo.forceActiveFocus()
        } else {
            campo.text = ""
            esperaDaBusca.stop()
            if (pagina) pagina.busca = ""
            grade.forceActiveFocus()
        }
    }

    // Barra de busca: padding 6 em volta do campo de 34 (46 no total); abre em 250 ms.
    Item {
        id: barraDeBusca
        objectName: "barraDeBusca"
        anchors { top: parent.top; left: parent.left; right: parent.right }
        height: raiz.buscaVisivel ? 46 : 0
        visible: height > 0
        clip: true
        Behavior on height { enabled: Tema.animacoes; NumberAnimation { duration: 250 } }

        // O campo espera 150 ms depois da última tecla para filtrar; Enter e Esc aplicam na hora.
        Timer {
            id: esperaDaBusca
            interval: 150
            onTriggered: if (raiz.pagina) raiz.pagina.busca = campo.text
        }

        TextField {
            id: campo
            objectName: "campoDeBusca"
            x: Math.round((parent.width - width) / 2)
            y: 6
            width: Math.min(500, parent.width - 12)
            height: 34
            placeholderText: "Buscar"
            placeholderTextColor: Tema.textoSecundario
            color: Tema.texto
            selectionColor: Tema.destaque
            font { family: Tema.fonte; pixelSize: Tema.corpo }
            verticalAlignment: TextInput.AlignVCenter
            // padding 9, o ícone de 16 e 6 de espaço; à direita, o botão de limpar quando há texto.
            leftPadding: 9 + 16 + 6
            rightPadding: text !== "" ? 9 + 16 + 6 : 9
            topPadding: 0
            bottomPadding: 0
            onTextChanged: esperaDaBusca.restart()
            onAccepted: {
                esperaDaBusca.stop()
                if (raiz.pagina) raiz.pagina.busca = text
                var id = raiz.pagina.primeiro()
                if (id === "") return
                grade.currentIndex = 0
                raiz.abrirDetalhes(id)
            }
            Keys.onEscapePressed: raiz.buscaAberta = false

            Icone {
                x: 9
                anchors.verticalCenter: parent.verticalCenter
                nome: "edit-find"
                opacity: 0.7
            }
            Icone {
                id: limpar
                objectName: "limparBusca"
                visible: campo.text !== ""
                x: parent.width - width - 9
                anchors.verticalCenter: parent.verticalCenter
                nome: "edit-clear"
                opacity: toqueDoLimpar.pressed ? 0.8 : toqueDoLimpar.containsMouse ? 1 : 0.7
                Accessible.role: Accessible.Button
                Accessible.name: "Limpar"
                MouseArea {
                    id: toqueDoLimpar
                    anchors.fill: parent
                    hoverEnabled: true
                    onClicked: { campo.text = ""; campo.forceActiveFocus() }
                }
            }
            background: Rectangle {
                radius: 9
                color: Tema.mistura(0.10)
            }
            AnelDeFoco { ativo: campo.activeFocus; raio: 9; afastamento: -2 }
        }
    }

    Grade {
        id: grade
        objectName: raiz.comBusca ? "grade" : "gradeDeZerados"
        anchors { top: barraDeBusca.bottom; left: parent.left; right: parent.right; bottom: parent.bottom }
        biblioteca: raiz.pagina
        colunasMaximas: aplicativo.colunasMaximas
        tocarSempre: aplicativo.tocarSempre && aplicativo.animacoesDoSistema
        ativa: raiz.ativa
        visible: !aviso.visible
        onAbrirDetalhes: id => raiz.abrirDetalhes(id)
        onEditar: id => raiz.editar(id)
    }

    // Sob a busca aberta, com a grade rolada: a mesma sombra da barra de título.
    SombraDeRolagem {
        objectName: "linhaDaBusca"
        anchors.top: barraDeBusca.bottom
        ativa: raiz.buscaVisivel && grade.rolado
        z: 1
    }

    // Efeito de fim de rolagem: dois degradês radiais em `currentColor`, 12% numa faixa de 3% da altura e 5% numa de 50%; somem ao soltar.
    Repeater {
        model: [{ topo: true }, { topo: false }]
        Item {
            id: brilho
            required property var modelData
            readonly property real excesso: modelData.topo ? Math.max(0, -grade.verticalOvershoot) : Math.max(0, grade.verticalOvershoot)
            readonly property real forca: Math.min(1, excesso / (grade.height * 0.1))
            anchors { left: grade.left; right: grade.right }
            y: modelData.topo ? grade.y : grade.y + grade.height - height
            height: grade.height * 0.5
            visible: grade.visible && forca > 0
            opacity: forca
            enabled: false
            clip: true
            component Camada: Item {
                id: camada
                required property real fracao
                required property real alfa
                anchors { left: parent.left; right: parent.right; top: brilho.modelData.topo ? parent.top : undefined; bottom: brilho.modelData.topo ? undefined : parent.bottom }
                height: brilho.height * fracao
                Shape {
                    width: camada.height * 2
                    height: camada.height
                    transform: Scale { xScale: camada.width / (camada.height * 2) }
                    ShapePath {
                        strokeColor: "transparent"
                        fillGradient: RadialGradient {
                            centerX: camada.height
                            centerY: brilho.modelData.topo ? 0 : camada.height
                            focalX: centerX
                            focalY: centerY
                            centerRadius: camada.height
                            GradientStop { position: 0; color: Tema.mistura(camada.alfa) }
                            GradientStop { position: 1; color: Tema.mistura(0) }
                        }
                        PathRectangle { x: 0; y: 0; width: camada.height * 2; height: camada.height }
                    }
                }
            }
            Camada { fracao: 1; alfa: 0.05 }
            Camada { fracao: 0.06; alfa: 0.12 }
        }
    }

    EstadoVazio {
        id: aviso
        objectName: raiz.comBusca ? "estadoVazio" : "estadoVazioDeZerados"
        anchors { top: barraDeBusca.bottom; left: parent.left; right: parent.right; bottom: parent.bottom }
        visible: raiz.pagina && (raiz.pagina.vazia || raiz.pagina.semResultados)
        // Busca sem resultado, `system-search`; Zerados vazio, `object-select`; "Nenhum jogo" não tem ícone.
        iconeDoApp: raiz.pagina.vazia && raiz.comBusca
        icone: raiz.pagina.vazia ? (raiz.comBusca ? "" : "object-select") : "system-search"
        titulo: raiz.pagina.vazia ? (raiz.comBusca ? "Nenhum jogo" : "Nenhum jogo zerado") : "Nenhum jogo encontrado"
        descricao: raiz.pagina.vazia
            ? (raiz.comBusca ? "Use o botão + para adicionar jogos." : "Os jogos desinstalados marcados como Zerado são exibidos aqui.")
            : (raiz.comBusca ? "Tente outra busca ou outro filtro." : "Tente outro filtro.")
        rotuloDoBotao: raiz.pagina.vazia && raiz.comBusca ? "Importar" : ""
        botaoHabilitado: !aplicativo.importando
        onBotaoClicado: aplicativo.importar()
    }
}
