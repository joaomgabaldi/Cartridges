import QtQuick
import QtQuick.Controls.Basic

// A janela do app: as páginas da biblioteca, os botões da barra e as camadas de aviso e confirmação.
// `paginaTodos`, `paginaZerados`, `filtros`, `aplicativo` e `ponte` vêm do contexto (cartridges/app.py).
Principal {
    id: janela

    // Lido aqui, fora dos Avisos, porque lá o nome da propriedade é o mesmo.
    readonly property QtObject ligacao: ponte
    readonly property string paginaAtual: pilha.depth === 0 ? "todos" : "zerados"

    // O `y` de um menu aberto por um botão da barra: abaixo dos 46 px dela, fora da área de arrasto do QWindowKit.
    function baseDaBarra(botao) { return botao.height + (alturaDaBarra - botao.height) / 2 }

    tituloDaBarra: paginaAtual === "todos" ? "Todos os jogos" : "Jogos Zerados"

    // Depois do setup do QWindowKit (Principal.qml), que roda no onCompleted da base.
    Component.onCompleted: visible = true

    inicio: [
        BotaoDaBarra {
            objectName: "botaoAdicionar"
            visible: janela.paginaAtual === "todos"
            glifo: ""
            dica: "Adicionar jogo"
            onClicked: menuDeAdicionar.open()
            menuAberto: menuDeAdicionar.opened
            MenuDoTema {
                id: menuDeAdicionar
                y: janela.baseDaBarra(parent)
                ItemDoMenu { text: "Importar"; enabled: !aplicativo.importando; onTriggered: aplicativo.importar() }
            }
        },
        BotaoDaBarra {
            objectName: "botaoVoltar"
            visible: janela.paginaAtual === "zerados"
            glifo: ""
            dica: "Voltar"
            onClicked: pilha.clear(StackView.PopTransition)
        }
    ]

    // Da direita para a esquerda: menu principal, Jogos Zerados e busca.
    fim: [
        BotaoDaBarra {
            objectName: "botaoMenu"
            glifo: ""
            dica: "Menu principal"
            onClicked: menuPrincipal.open()
            menuAberto: menuPrincipal.opened
            MenuPrincipal {
                id: menuPrincipal
                objectName: "menuPrincipal"
                y: janela.baseDaBarra(parent)
                x: parent.width - width
            }
        },
        BotaoDaBarra {
            objectName: "botaoZerados"
            visible: janela.paginaAtual === "todos"
            trofeu: true
            dica: "Jogos Zerados"
            onClicked: pilha.push(zerados)
        },
        BotaoDaBarra {
            objectName: "botaoBusca"
            visible: janela.paginaAtual === "todos"
            glifo: ""
            dica: "Buscar"
            checkable: true
            checked: todos.buscaAberta
            onClicked: todos.alternarBusca()
        }
    ]

    // O foco do teclado acompanha a página que está na tela.
    onPaginaAtualChanged: if (paginaAtual === "todos") todos.focarGrade()

    PaginaDaBiblioteca {
        id: todos
        objectName: "pagina"
        anchors.fill: parent
        pagina: paginaTodos
        comBusca: true
        ativa: pilha.depth === 0
    }

    // Vazia, a pilha mostra "Todos os jogos"; "Jogos Zerados" entra por cima.
    StackView {
        id: pilha
        anchors.fill: parent
        visible: depth > 0
    }

    Component {
        id: zerados
        PaginaDaBiblioteca {
            objectName: "paginaDeZerados"
            pagina: paginaZerados
            StackView.onActivated: focarGrade()
            // O fundo cobre "Todos os jogos" durante a transição.
            Rectangle { anchors.fill: parent; color: Tema.fundo; z: -1 }
        }
    }

    Avisos {
        id: camadaDeAvisos
        objectName: "camadaDeAvisos"
        anchors.fill: parent
        ponte: janela.ligacao
        fila: aplicativo.avisos
        app: aplicativo
    }

    // Atalhos arrastados do Explorer: só com a janela livre de diálogos.
    DropArea {
        id: alvoDeSoltar
        objectName: "alvoDeSoltar"
        anchors.fill: parent
        enabled: !camadaDeAvisos.dialogoAberto
        onEntered: (arrasto) => arrasto.accepted = arrasto.hasUrls
        onDropped: (soltou) => {
            if (soltou.hasUrls) aplicativo.soltar(soltou.urls)
        }
    }

    Rectangle {
        id: avisoDeSoltar
        objectName: "avisoDeSoltar"
        anchors.fill: parent
        color: "#99000000"
        opacity: alvoDeSoltar.containsDrag ? 1 : 0
        visible: opacity > 0
        Behavior on opacity { NumberAnimation { duration: 150 } }

        Rectangle {
            anchors.centerIn: parent
            width: Math.min(420, avisoDeSoltar.width - 48)
            height: 140
            radius: 12
            color: Tema.fundo
            border { color: Tema.destaque; width: 2 }
            Text {
                anchors.centerIn: parent
                text: "Solte aqui para importar"
                textFormat: Text.PlainText
                color: Tema.texto
                font { family: Tema.fonte; pixelSize: 20; weight: Font.DemiBold }
            }
        }
    }

    Connections {
        target: janela.ligacao
        function onSairDaFrente() { janela.showMinimized() }
    }
}
