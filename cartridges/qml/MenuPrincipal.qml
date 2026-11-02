import QtQuick
import QtQuick.Controls.Basic

// O menu principal, o mesmo nas duas páginas: filtros e ordenação. `filtros` vem do contexto (app.py).
MenuDoTema {
    id: menu

    // O `Sobre` (D84); nulo onde ele não está no contexto (os arneses dos outros diálogos): o item some.
    property QtObject servicoDoSobre: null

    readonly property var rotulosDeFiltrar: rotulos(filtrar)
    readonly property var rotulosDeOrdenar: rotulos(ordenar)
    // Para os testes olharem o visual dos menus aninhados.
    property Item primeiroDeOrdenar
    property Item fundoDeOrdenar
    Component.onCompleted: {
        primeiroDeOrdenar = ordenar.itemAt(0)
        fundoDeOrdenar = ordenar.background
    }

    function rotulos(submenu) {
        var lista = []
        for (var i = 0; i < submenu.count; ++i)
            if (submenu.itemAt(i).objectName !== "limpar" && submenu.itemAt(i).objectName !== "limparSeparador")
                lista.push(submenu.itemAt(i).text)
        return lista
    }

    // As opções (gêneros, anos) são refeitas a cada abertura, não a cada jogo importado.
    onAboutToShow: filtros.recalcularOpcoes()

    // Um item de escolha única: marcado quando `atual`, e sem trocar a marca por conta própria.
    component Escolha: ItemDoMenu {
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

    MenuDoTema {
        id: filtrar
        title: "Filtrar por"
        MenuDoTema {
            title: "Gêneros"
            Escolha { grupo: "genero"; rotulo: "Todos"; atual: filtros.genero === ""; onEscolhido: filtros.genero = "" }
            Repeater {
                model: filtros.generos
                Escolha {
                    required property string modelData
                    grupo: "genero"
                    rotulo: modelData
                    atual: filtros.genero === modelData
                    onEscolhido: filtros.genero = modelData
                }
            }
        }
        MenuDoTema {
            title: "Ano de lançamento"
            Escolha { grupo: "ano"; rotulo: "Todos"; atual: filtros.ano === ""; onEscolhido: filtros.ano = "" }
            Repeater {
                model: filtros.anos
                Escolha {
                    required property string modelData
                    grupo: "ano"
                    rotulo: modelData
                    atual: filtros.ano === modelData
                    onEscolhido: filtros.ano = modelData
                }
            }
        }
        MenuDoTema {
            title: "Status"
            Escolha { grupo: "status"; rotulo: "Todos"; atual: filtros.status === ""; onEscolhido: filtros.status = "" }
            Repeater {
                model: filtros.opcoesDeStatus
                Escolha {
                    required property var modelData
                    grupo: "status"
                    rotulo: modelData.rotulo
                    atual: filtros.status === modelData.valor
                    onEscolhido: filtros.status = modelData.valor
                }
            }
        }
        // "Limpar" só existe enquanto há o que limpar, numa seção própria (com o separador acima).
        SeparadorDoMenu {
            objectName: "limparSeparador"
            readonly property bool exibido: filtros.genero !== "" || filtros.ano !== "" || filtros.status !== ""
            visible: exibido
            height: exibido ? implicitHeight : 0
        }
        ItemDoMenu {
            objectName: "limpar"
            readonly property bool exibido: filtros.genero !== "" || filtros.ano !== "" || filtros.status !== ""
            visible: exibido
            height: exibido ? implicitHeight : 0
            text: "Limpar"
            onTriggered: filtros.limpar()
        }
    }

    MenuDoTema {
        id: ordenar
        title: "Ordenar por"
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
                grupo: "ordenar"
                rotulo: modelData.rotulo
                atual: filtros.modo === modelData.valor
                onEscolhido: filtros.modo = modelData.valor
            }
        }
    }

    SeparadorDoMenu {}
    ItemDoMenu {
        objectName: "itemPreferencias"
        text: "Preferências"
        // Como a `main`: a ação some durante a importação.
        enabled: !aplicativo.importando
        onTriggered: preferencias.abrir()
    }
    ItemDoMenu {
        objectName: "itemSobre"
        visible: menu.servicoDoSobre !== null
        height: visible ? implicitHeight : 0
        text: "Sobre o Cartridges"
        onTriggered: menu.servicoDoSobre.abrir()
    }
}
