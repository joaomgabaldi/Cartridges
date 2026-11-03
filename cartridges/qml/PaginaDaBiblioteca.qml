import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Shapes

// Uma página de jogos: "Todos os jogos" (com busca) ou "Jogos Zerados". Os botões ficam na barra de título
// (Aplicativo.qml); aqui estão a barra de busca, a grade e o aviso de página vazia.
// `aplicativo` vem do contexto (cartridges/app.py).
Item {
    id: raiz

    // FiltroDaPagina
    property QtObject pagina
    property bool comBusca: false
    property bool buscaAberta: false
    // A página que está por cima na pilha; a coberta não anima capas.
    property bool ativa: true
    // Um jogo foi escolhido (clique, Enter, A do controle ou Enter da busca) e a página dele deve abrir.
    signal abrirDetalhes(string jogoId)
    signal editar(string jogoId)
    // Esc em Jogos Zerados volta (`pop-on-escape` da `AdwNavigationPage`); "Todos os jogos" não tem para onde.
    signal voltar()

    function focarGrade() { grade.forceActiveFocus() }
    function focarJogo(jogoId) { grade.focarJogo(jogoId) }

    // O controle do Xbox (Aplicativo.qml): o menu do jogo está aberto, e os comandos sobre o cartão atual.
    readonly property bool menuDoJogoAberto: grade.menuAberto
    // A grade rolada: a barra de título mostra a linha de baixo.
    // Com a busca aberta, a linha fica sob ela (`undershoot` abaixo da `SearchBar`), e a da barra de título apaga:
    // só uma linha, nunca duas.
    readonly property bool buscaVisivel: comBusca && buscaAberta
    readonly property bool rolado: grade.rolado && !buscaVisivel
    // Devolve se o passo tem onde acontecer aqui; falso em ↑ na primeira linha (o controle vai à barra) e onde não há nada a fazer.
    function moverSelecao(dx, dy) {
        // Na busca, ↓ só entra na grade, sem andar uma linha; ↑ vai à barra e ←/→ não fazem nada.
        if (campo.activeFocus) {
            if (dy <= 0) return false
            grade.porTeclado = true
            grade.forceActiveFocus()
            return true
        }
        // Página vazia: o foco alcança o botão "Importar" (`window.blp:20-29`).
        if (grade.count === 0) {
            if (dy <= 0 || !aviso.visible || aviso.rotuloDoBotao === "" || aviso.botaoFocado) return false
            aviso.focarBotao()
            return true
        }
        // O `GtkFlowBox` responde que andou mesmo contra a parede (o toque é o de passar): só ↑ na primeira linha sai.
        return grade.moverSelecao(dx, dy) || dy >= 0
    }
    // O x (na janela) do centro do cartão atual, para achar o botão da barra mais próximo.
    function xDoAtual() {
        return grade.currentItem ? grade.currentItem.mapToItem(null, grade.currentItem.width / 2, 0).x : 0
    }
    // Um controle apareceu: acende a seleção, sem tirar o foco de quem digita na busca. Com o foco fora da grade, vai ao
    // primeiro jogo (`_focus_first`); devolve se foi.
    function mostrarSelecao() {
        if (buscaAberta) return false
        const foraDaGrade = !grade.activeFocus && grade.count > 0
        grade.porTeclado = true
        if (foraDaGrade) { grade.currentIndex = 0; grade.rolarAte(0) }
        grade.forceActiveFocus()
        return foraDaGrade
    }
    // O Y só age com o foco num cartão: na barra, na busca ou no botão da página vazia não faz nada.
    function abrirMenuDoAtual() {
        if (!grade.activeFocus) return
        grade.porTeclado = true
        if (grade.currentItem) grade.currentItem.abrirMenu()
    }
    // O A: o botão da página vazia, o primeiro resultado da busca (o Enter do campo), ou o cartão atual.
    function abrirDetalhesDoAtual() {
        if (aviso.botaoFocado) { aviso.acionarBotao(); return }
        if (campo.activeFocus) { campo.accepted(); return }
        grade.porTeclado = true
        grade.forceActiveFocus()
        grade.abrirDoAtual()
    }
    function alternarBusca() { buscaAberta = !buscaAberta }

    // O `key-capture-widget` da `main` é a página inteira (`window.blp:180`): digitar com o foco na grade ou num botão da
    // barra abre a busca e leva a letra. Só a página "Todos os jogos" (a busca dos Zerados não existe, e Detalhes e
    // Zerados à vista não a abrem, G13). Espaço não conta: ele aciona o botão ou o cartão em foco.
    // Devolve se a tecla foi tomada.
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
            // Fechar por qualquer caminho limpa o texto, e a página volta na hora (sem a espera de 150 ms).
            campo.text = ""
            esperaDaBusca.stop()
            if (pagina) pagina.busca = ""
            grade.forceActiveFocus()
        }
    }

    // A `SearchBar` dentro do `.top-bar` da `ToolbarView`: transparente, sem linha própria (CSS 2853 vence a 2839),
    // padding 6 em volta do campo de 34 (46 no total); abre em 250 ms.
    Item {
        id: barraDeBusca
        objectName: "barraDeBusca"
        anchors { top: parent.top; left: parent.left; right: parent.right }
        height: raiz.buscaVisivel ? 46 : 0
        visible: height > 0
        clip: true
        Behavior on height { enabled: Tema.animacoes; NumberAnimation { duration: 250 } }

        // O `GtkSearchEntry` espera 150 ms depois da última tecla para filtrar; Enter e Esc aplicam na hora.
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
            // `Adw.Clamp` de 500, com os 6 de padding dos lados.
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
                // O foco volta ao cartão aberto, o primeiro da lista filtrada.
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
            // `edit-clear-symbolic` à direita: limpa e mantém o foco no campo.
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
        // Só com "Animar capas" e os efeitos de animação do Windows ligados (como na `main`).
        tocarSempre: aplicativo.tocarSempre && aplicativo.animacoesDoSistema
        ativa: raiz.ativa
        visible: !aviso.visible
        onAbrirDetalhes: id => raiz.abrirDetalhes(id)
        onEditar: id => raiz.editar(id)
    }

    // `toolbarview.undershoot-top` (CSS 2914): sob a busca aberta, a linha de 1 px mais o degradê de 4 px em `shade_color`
    // a 75%, enquanto a grade está rolada. Sem a busca, a mesma linha é a `sombraDaBarra` da barra de título.
    Item {
        id: linhaBusca
        objectName: "linhaDaBusca"
        anchors { top: barraDeBusca.bottom; left: parent.left; right: parent.right }
        height: 4
        visible: raiz.buscaVisivel && grade.rolado
        enabled: false
        z: 1
        readonly property color sombra: Qt.rgba(0, 0, 6 / 255, (Tema.escuro ? 0.25 : 0.07) * 0.75)
        Rectangle {
            anchors.fill: parent
            gradient: Gradient {
                GradientStop { position: 0; color: linhaBusca.sombra }
                GradientStop { position: 1; color: "transparent" }
            }
        }
        Rectangle { anchors { left: parent.left; right: parent.right; top: parent.top } height: 1; color: linhaBusca.sombra }
    }

    // `overshoot` do scrolledwindow (CSS 2343): dois degradês radiais em `currentColor`, 12% numa faixa de 3% da altura e
    // 5% numa de 50%, com o centro na borda; somem ao soltar. Dispara com `verticalOvershoot` (`DragOverBounds`).
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
            // Uma elipse por camada: o `farthest-side` do CSS é a elipse inscrita na faixa.
            component Camada: Item {
                id: camada
                required property real fracao
                required property real alfa
                anchors { left: parent.left; right: parent.right; top: brilho.modelData.topo ? parent.top : undefined; bottom: brilho.modelData.topo ? undefined : parent.bottom }
                height: brilho.height * fracao
                Shape {
                    // Um círculo de raio `height`, esticado na largura: a elipse.
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
        // `window.blp`: busca sem resultado, `system-search`; Zerados vazio, `object-select`; "Nenhum jogo" não tem ícone.
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
