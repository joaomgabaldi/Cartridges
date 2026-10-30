import QtQuick
import QtQuick.Dialogs

// A página Importação das Preferências. Só desenha: as chaves são do `preferencias` (cartridges/modelos/preferencias.py).
Column {
    id: pagina
    objectName: "paginaDeImportacao"

    readonly property bool comAtalhos: preferencias.valores["shortcuts"] === true

    width: parent ? parent.width : implicitWidth
    spacing: 24

    component Interruptor: LinhaDeAlternancia {
        property string chave
        objectName: "interruptor-" + chave
        checked: preferencias.valores[chave] === true
        onAlternado: preferencias.definir(chave, checked)
    }

    // Criado só ao clicar: o seletor nativo não precisa existir antes.
    function escolherPasta() {
        if (carga.item) carga.item.open(); else carga.active = true
    }
    Loader {
        id: carga
        active: false
        sourceComponent: FolderDialog {
            title: "Selecionar pasta"
            onAccepted: preferencias.escolherPastaDosAtalhos(selectedFolder)
        }
        onLoaded: item.open()
    }

    GrupoDePreferencias {
        objectName: "grupoComportamentoDaImportacao"
        titulo: "Comportamento"

        Interruptor { chave: "auto-import"; titulo: "Importar jogos automaticamente" }
        Interruptor { chave: "remove-missing"; titulo: "Remover jogos desinstalados" }
        Interruptor {
            chave: "steam-metadata"
            titulo: "Buscar metadados da Steam"
            subtitulo: "Busca na Steam título, desenvolvedora, publicadora, lançamento, gênero, descrição, avaliações e compatibilidade com controle"
        }
        Interruptor {
            chave: "hltb-metadata"
            titulo: "Buscar tempos do HowLongToBeat"
            subtitulo: "Busca as estimativas de história principal, extras e completista"
        }
    }

    GrupoDePreferencias {
        objectName: "grupoAtualizarMetadados"

        LinhaDeAtualizacao {
            objectName: "linhaDosMetadados"
            titulo: "Atualizar metadados"
            subtitulo: "Busca dados para jogos já na biblioteca"
            // Sem nenhuma das duas fontes ligadas a busca não faria nada.
            enabled: preferencias.biblioteca.metadadosAtivos
            emAndamento: preferencias.biblioteca.rodando
            podeParar: true
            paradaPedida: preferencias.biblioteca.cancelado
            progressoVisivel: preferencias.biblioteca.rodando
            fracao: preferencias.biblioteca.fracao
            textoDoProgresso: preferencias.biblioteca.progresso
            onAcionada: preferencias.biblioteca.atualizarMetadados()
            onParada: preferencias.biblioteca.cancelarMetadados()
        }
    }

    GrupoDePreferencias {
        objectName: "grupoAtalhos"
        titulo: "Atalhos"
        descricao: "Importa atalhos de jogos (.lnk e .url) de uma pasta. Funciona com Steam, Epic, Ubisoft Connect, Xbox/Microsoft Store e outros."

        Interruptor { chave: "shortcuts"; titulo: "Atalhos" }
        LinhaDeAcao {
            objectName: "linhaDaPasta"
            visible: pagina.comAtalhos
            titulo: "Pasta"
            subtitulo: preferencias.estado.pastaDosAtalhos || ""
            glifo: ""  // pasta
            dica: "Selecionar pasta"
            onAcionada: pagina.escolherPasta()
        }
        Interruptor { chave: "shortcuts-recursive"; titulo: "Buscar em subpastas"; visible: pagina.comAtalhos }
    }
}
