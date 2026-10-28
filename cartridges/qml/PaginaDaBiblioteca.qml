import QtQuick
import QtQuick.Controls.Basic

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
    // O jogo que o Enter da busca escolheu; a tela de detalhes (plano 3) o abre.
    // shortcut: só guardado, a tela de detalhes ainda não existe; sai com o plano 3.
    property string jogoEscolhido: ""

    function focarGrade() { grade.forceActiveFocus() }

    // O controle do Xbox (Aplicativo.qml): o menu do jogo está aberto, e os comandos sobre o cartão atual.
    readonly property bool menuDoJogoAberto: grade.menuAberto
    function moverSelecao(dx, dy) { return grade.moverSelecao(dx, dy) }
    // O x (na janela) do centro do cartão atual, para achar o botão da barra mais próximo.
    function xDoAtual() {
        return grade.currentItem ? grade.currentItem.mapToItem(null, grade.currentItem.width / 2, 0).x : 0
    }
    // Um controle apareceu: acende a seleção no cartão atual, sem tirar o foco de quem digita na busca.
    function mostrarSelecao() {
        if (buscaAberta) return
        grade.porTeclado = true
        grade.forceActiveFocus()
    }
    function abrirMenuDoAtual() {
        grade.porTeclado = true
        grade.forceActiveFocus()
        if (grade.currentItem) grade.currentItem.abrirMenu()
    }
    function abrirDetalhesDoAtual() {
        grade.porTeclado = true
        grade.forceActiveFocus()
        grade.abrirDoAtual()
    }
    function alternarBusca() { buscaAberta = !buscaAberta }

    onBuscaAbertaChanged: {
        if (buscaAberta) {
            campo.forceActiveFocus()
        } else {
            // Fechar por qualquer caminho limpa o texto.
            campo.text = ""
            grade.forceActiveFocus()
        }
    }

    Rectangle {
        id: barraDeBusca
        anchors { top: parent.top; left: parent.left; right: parent.right }
        height: raiz.comBusca && raiz.buscaAberta ? 56 : 0
        visible: height > 0
        clip: true
        color: Tema.barra
        Behavior on height { NumberAnimation { duration: Tema.duracaoCurta } }

        TextField {
            id: campo
            objectName: "campoDeBusca"
            anchors.centerIn: parent
            width: Math.min(500, parent.width - 24)
            height: 36
            placeholderText: "Buscar"
            placeholderTextColor: Tema.textoSecundario
            color: Tema.texto
            selectionColor: Tema.destaque
            font { family: Tema.fonte; pixelSize: 14 }
            leftPadding: 34
            onTextChanged: if (raiz.pagina) raiz.pagina.busca = text
            onAccepted: raiz.jogoEscolhido = raiz.pagina.primeiro()
            Keys.onEscapePressed: raiz.buscaAberta = false

            Text {
                anchors { left: parent.left; leftMargin: 11; verticalCenter: parent.verticalCenter }
                text: ""  // lupa
                font { family: Tema.fonteDeIcones; pixelSize: 14 }
                color: Tema.textoSecundario
            }
            background: Rectangle {
                radius: 6
                color: Tema.superficie
                border.width: campo.activeFocus ? 2 : 1
                border.color: campo.activeFocus ? Tema.destaque : Tema.borda
            }
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

        // Digitar com a grade em foco abre a busca, como o `key-capture-widget` da versão anterior.
        Keys.onPressed: event => {
            if (event.key === Qt.Key_Escape && raiz.buscaAberta) {
                raiz.buscaAberta = false
                event.accepted = true
            } else if (raiz.comBusca && event.text.length > 0 && event.text >= " " && event.text !== "\u007f"
                       && !(event.modifiers & (Qt.ControlModifier | Qt.AltModifier))) {
                raiz.buscaAberta = true
                campo.forceActiveFocus()
                campo.text += event.text
                event.accepted = true
            }
        }
    }

    EstadoVazio {
        id: aviso
        objectName: raiz.comBusca ? "estadoVazio" : "estadoVazioDeZerados"
        anchors { top: barraDeBusca.bottom; left: parent.left; right: parent.right; bottom: parent.bottom }
        visible: raiz.pagina && (raiz.pagina.vazia || raiz.pagina.semResultados)
        glifo: raiz.pagina.vazia ? (raiz.comBusca ? "" : "") : ""
        iconeDoApp: raiz.pagina.vazia && raiz.comBusca
        titulo: raiz.pagina.vazia ? (raiz.comBusca ? "Nenhum jogo" : "Nenhum jogo zerado") : "Nenhum jogo encontrado"
        descricao: raiz.pagina.vazia
            ? (raiz.comBusca ? "Use o botão + para adicionar jogos." : "Os jogos desinstalados marcados como Zerado são exibidos aqui.")
            : (raiz.comBusca ? "Tente outra busca ou outro filtro." : "Tente outro filtro.")
        rotuloDoBotao: raiz.pagina.vazia && raiz.comBusca ? "Importar" : ""
        botaoHabilitado: !aplicativo.importando
        onBotaoClicado: aplicativo.importar()
    }
}
