import QtQuick
import QtQuick.Controls.Basic

// O menu principal (filtros e ordenação); os submenus deslizam dentro do mesmo popover, cada item com a sua `pagina`.
MenuDoTema {
    id: menu

    property QtObject servicoDoSobre: null

    property string pagina: "raiz"
    // A página pedida por um item de navegação: o `Menu` fecha a cada item acionado, e o `onClosed` o reabre nela.
    property string destino: ""
    property int sentido: 1

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

    onAboutToShow: {
        filtros.recalcularOpcoes()
        medirItens()
    }
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
        enabled: naPagina
        height: naPagina ? implicitHeight : 0
    }
    component SeparadorDaPagina: SeparadorDoMenu {
        property string pagina: "raiz"
        property bool exibido: true
        visible: pagina === menu.pagina && exibido
        height: visible ? implicitHeight : 0
    }
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

    Entrada { alvo: "filtrar"; text: "Filtrar por" }
    Entrada { alvo: "ordenar"; text: "Ordenar por" }
    SeparadorDaPagina {}
    ItemDaPagina {
        objectName: "itemPreferencias"
        text: "Preferências"
        enabled: naPagina && !aplicativo.importando
        onTriggered: preferencias.abrir()
    }
    ItemDaPagina {
        objectName: "itemSobre"
        exibido: menu.servicoDoSobre !== null
        text: "Sobre o Kyron"
        onTriggered: menu.servicoDoSobre.abrir()
    }

    Cabecalho { pagina: "filtrar"; text: "Filtrar por"; volta: "raiz" }
    SeparadorDaPagina { pagina: "filtrar" }
    Entrada { pagina: "filtrar"; alvo: "genero"; text: "Gêneros" }
    Entrada { pagina: "filtrar"; alvo: "ano"; text: "Ano de lançamento" }
    Entrada { pagina: "filtrar"; alvo: "status"; text: "Status" }
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
        exibido: temFiltro
        text: "Limpar"
        onTriggered: filtros.limpar()
    }

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
