import QtQuick
import QtQuick.Controls.Basic

// O menu principal, o mesmo nas duas páginas: filtros e ordenação. `filtros` vem do contexto (app.py).
// Como o `GtkPopoverMenu` da `main` (`window.blp:1213`): os submenus deslizam dentro do mesmo popover, com o cabeçalho
// "‹ Título" para voltar, em vez de abrir em cascata ao lado. Todos os itens são filhos deste menu, cada um com a sua
// `pagina`; só os da página atual aparecem. Escolher uma opção fecha o popover (como na `main`).
MenuDoTema {
    id: menu

    // O `Sobre` (D84); nulo onde ele não está no contexto (os arneses dos outros diálogos): o item some.
    property QtObject servicoDoSobre: null

    // "raiz", "filtrar", "genero", "ano", "status" ou "ordenar".
    property string pagina: "raiz"
    // A página pedida por um item de navegação: o `Menu` fecha a cada item acionado, e o `onClosed` o reabre nela.
    property string destino: ""
    property int sentido: 1

    // O `objectName` do item em foco do teclado (para os testes).
    readonly property string atual: currentIndex >= 0 && itemAt(currentIndex) ? itemAt(currentIndex).objectName : ""
    readonly property var rotulosDeFiltrar: rotulosDaPagina("filtrar", "entrada-")
    readonly property var rotulosDeOrdenar: rotulosDaPagina("ordenar", "ordenar-")

    function rotulosDaPagina(qual, prefixo) {
        var lista = []
        for (var i = 0; i < count; ++i) {
            var item = itemAt(i)
            if (item && item.pagina === qual && item.objectName.startsWith(prefixo))
                lista.push(item.text)
        }
        return lista
    }

    // Troca a página sem fechar o popover (como o `GtkPopoverMenu`): o mouse e o Enter dos itens de navegação chegam aqui.
    // `irPara` + o `Menu` fechando e reabrindo é só o caminho de quem aciona o item por `click()`/`triggered`.
    function navegar(qual, avanca) {
        sentido = avanca ? 1 : -1
        pagina = qual
        currentIndex = -1
        deslizar()
    }
    function irPara(qual, avanca) {
        sentido = avanca ? 1 : -1
        destino = qual
    }

    // As opções (gêneros, anos) são refeitas a cada abertura, não a cada jogo importado.
    onAboutToShow: {
        filtros.recalcularOpcoes()
        medirItens()
    }
    // Fechou por um item de navegação: abre de novo, já na outra página, no mesmo quadro. Senão, a próxima abertura
    // começa na raiz.
    // Adiado um passo: o `Menu` fecha ao acionar o item, e o item só diz a página depois (a ordem não é fixa).
    onClosed: Qt.callLater(continuar)
    function continuar() {
        if (opened) return
        if (destino !== "") {
            pagina = destino
            destino = ""
            open()
            deslizar()
        } else {
            pagina = "raiz"
        }
    }

    // A página nova entra deslizando um pouco e surgindo, dentro do mesmo popover.
    function deslizar() {
        if (!Tema.animacoes) return
        entrada.base = leftPadding
        entrada.restart()
    }
    ParallelAnimation {
        id: entrada
        property real base: 6
        NumberAnimation { target: menu.contentItem; property: "x"; from: entrada.base + 24 * menu.sentido; to: entrada.base; duration: Tema.duracaoCurta; easing { type: Easing.Bezier; bezierCurve: Tema.curva } }
        NumberAnimation { target: menu.contentItem; property: "opacity"; from: 0; to: 1; duration: Tema.duracaoCurta }
    }

    // Os itens que não são da página atual não ocupam lugar (o menu mede pela `height`).
    component ItemDaPagina: ItemDoMenu {
        property string pagina: "raiz"
        property bool exibido: true
        readonly property bool naPagina: pagina === menu.pagina && exibido
        visible: naPagina
        // Fora da página, o item não ocupa lugar nem recebe as setas (nem as do controle).
        enabled: naPagina
        height: naPagina ? implicitHeight : 0
    }
    component SeparadorDaPagina: SeparadorDoMenu {
        property string pagina: "raiz"
        property bool exibido: true
        visible: pagina === menu.pagina && exibido
        height: visible ? implicitHeight : 0
    }
    // ← volta e → entra, como no `GtkPopoverMenu`; o foco é do menu, não dos itens, então o atalho é do menu.
    Shortcut {
        sequence: "Left"
        enabled: menu.opened && menu.pagina !== "raiz"
        onActivated: menu.voltarDaPagina()
    }
    Shortcut {
        sequence: "Right"
        enabled: menu.opened && menu.atual.startsWith("entrada-")
        onActivated: menu.navegar(menu.itemAt(menu.currentIndex).alvo, true)
    }
    function voltarDaPagina() {
        const pai = { filtrar: "raiz", ordenar: "raiz", genero: "filtrar", ano: "filtrar", status: "filtrar" }[pagina]
        if (!pai) return false
        navegar(pai, false)
        return true
    }

    // A linha de entrada de um submenu: "Título ›".
    component Entrada: ItemDaPagina {
        property string alvo
        rightPadding: 34
        objectName: "entrada-" + alvo
        arrow: Icone {
            x: parent.width - width - 12
            anchors.verticalCenter: parent.verticalCenter
            nome: "go-next"
            opacity: 0.3
        }
        onTriggered: menu.irPara(alvo, true)
        // O clique e o Enter do item não passam pelo `triggered` do `Menu`, que fecharia o popover.
        MouseArea { anchors.fill: parent; onClicked: menu.navegar(parent.alvo, true) }
        Keys.onReturnPressed: menu.navegar(alvo, true)
        Keys.onEnterPressed: menu.navegar(alvo, true)
    }

    // O cabeçalho "‹ Título" de um submenu: volta à página de cima.
    component Cabecalho: ItemDaPagina {
        id: cabecalho
        objectName: "cabecalho-" + pagina
        property string volta: "raiz"
        leftPadding: 12 + 16 + 6
        indicator: Icone {
            x: 12
            anchors.verticalCenter: parent.verticalCenter
            nome: "go-previous"
        }
        contentItem: Text {
            text: cabecalho.text
            textFormat: Text.PlainText
            color: Tema.texto
            verticalAlignment: Text.AlignVCenter
            font { family: Tema.fonte; pixelSize: Tema.corpo; weight: Tema.pesoForte }
        }
        onTriggered: menu.irPara(volta, false)
        MouseArea { anchors.fill: parent; onClicked: menu.navegar(parent.volta, false) }
        Keys.onReturnPressed: menu.navegar(volta, false)
        Keys.onEnterPressed: menu.navegar(volta, false)
    }

    // Um item de escolha única: marcado quando `atual`, e sem trocar a marca por conta própria.
    component Escolha: ItemDaPagina {
        property string grupo
        property string rotulo
        property bool atual
        signal escolhido()
        objectName: grupo + "-" + rotulo
        text: rotulo
        checkable: true
        checked: atual
        onTriggered: {
            escolhido()
            checked = Qt.binding(() => atual)
        }
    }

    // --- raiz -----------------------------------------------------------------------------------------------
    Entrada { alvo: "filtrar"; text: "Filtrar por" }
    Entrada { alvo: "ordenar"; text: "Ordenar por" }
    SeparadorDaPagina {}
    ItemDaPagina {
        objectName: "itemPreferencias"
        text: "Preferências"
        // Como a `main`: a ação some durante a importação.
        enabled: naPagina && !aplicativo.importando
        onTriggered: preferencias.abrir()
    }
    ItemDaPagina {
        objectName: "itemSobre"
        exibido: menu.servicoDoSobre !== null
        text: "Sobre o Cartridges"
        onTriggered: menu.servicoDoSobre.abrir()
    }

    // --- Filtrar por ------------------------------------------------------------------------------------------
    Cabecalho { pagina: "filtrar"; text: "Filtrar por"; volta: "raiz" }
    SeparadorDaPagina { pagina: "filtrar" }
    Entrada { pagina: "filtrar"; alvo: "genero"; text: "Gêneros" }
    Entrada { pagina: "filtrar"; alvo: "ano"; text: "Ano de lançamento" }
    Entrada { pagina: "filtrar"; alvo: "status"; text: "Status" }
    // "Limpar" só existe enquanto há o que limpar, numa seção própria (com o separador acima).
    SeparadorDaPagina {
        objectName: "limparSeparador"
        pagina: "filtrar"
        readonly property bool temFiltro: filtros.genero !== "" || filtros.ano !== "" || filtros.status !== ""
        exibido: temFiltro
    }
    ItemDaPagina {
        objectName: "limpar"
        pagina: "filtrar"
        readonly property bool temFiltro: filtros.genero !== "" || filtros.ano !== "" || filtros.status !== ""
        // `exibido` diz se há o que limpar; a página de filtros à vista é `naPagina`.
        exibido: temFiltro
        text: "Limpar"
        onTriggered: filtros.limpar()
    }

    // --- Gêneros, Ano de lançamento, Status -------------------------------------------------------------------
    Cabecalho { pagina: "genero"; text: "Gêneros"; volta: "filtrar" }
    SeparadorDaPagina { pagina: "genero" }
    Escolha { pagina: "genero"; grupo: "genero"; rotulo: "Todos"; atual: filtros.genero === ""; onEscolhido: filtros.genero = "" }
    Repeater {
        model: filtros.generos
        Escolha {
            required property string modelData
            pagina: "genero"
            grupo: "genero"
            rotulo: modelData
            atual: filtros.genero === modelData
            onEscolhido: filtros.genero = modelData
        }
    }

    Cabecalho { pagina: "ano"; text: "Ano de lançamento"; volta: "filtrar" }
    SeparadorDaPagina { pagina: "ano" }
    Escolha { pagina: "ano"; grupo: "ano"; rotulo: "Todos"; atual: filtros.ano === ""; onEscolhido: filtros.ano = "" }
    Repeater {
        model: filtros.anos
        Escolha {
            required property string modelData
            pagina: "ano"
            grupo: "ano"
            rotulo: modelData
            atual: filtros.ano === modelData
            onEscolhido: filtros.ano = modelData
        }
    }

    Cabecalho { pagina: "status"; text: "Status"; volta: "filtrar" }
    SeparadorDaPagina { pagina: "status" }
    Escolha { pagina: "status"; grupo: "status"; rotulo: "Todos"; atual: filtros.status === ""; onEscolhido: filtros.status = "" }
    Repeater {
        model: filtros.opcoesDeStatus
        Escolha {
            required property var modelData
            pagina: "status"
            grupo: "status"
            rotulo: modelData.rotulo
            atual: filtros.status === modelData.valor
            onEscolhido: filtros.status = modelData.valor
        }
    }

    // --- Ordenar por ------------------------------------------------------------------------------------------
    Cabecalho { pagina: "ordenar"; text: "Ordenar por"; volta: "raiz" }
    SeparadorDaPagina { pagina: "ordenar" }
    Repeater {
        model: [
            { rotulo: "Jogados recentemente", valor: "last_played" },
            { rotulo: "Título (A–Z)", valor: "a-z" },
            { rotulo: "Título (Z–A)", valor: "z-a" },
            { rotulo: "Lançamento (mais recente)", valor: "released_newest" },
            { rotulo: "Lançamento (mais antigo)", valor: "released_oldest" },
            { rotulo: "Adicionados recentemente", valor: "newest" },
            { rotulo: "Adicionados há mais tempo", valor: "oldest" },
            { rotulo: "Mais jogados", valor: "playtime" },
            { rotulo: "Minha nota", valor: "rating" },
            { rotulo: "Tamanho", valor: "install_size" }
        ]
        Escolha {
            required property var modelData
            pagina: "ordenar"
            grupo: "ordenar"
            rotulo: modelData.rotulo
            atual: filtros.modo === modelData.valor
            onEscolhido: filtros.modo = modelData.valor
        }
    }
}
