import QtQuick
import QtCore
import QtQuick.Dialogs

Column {
    id: pagina
    objectName: "paginaDoBackup"

    readonly property bool saves: preferencias.estado.savesDisponiveis === true

    width: parent ? parent.width : implicitWidth
    spacing: 24

    // Criados só ao clicar: os seletores nativos não precisam existir antes. Sem título próprio: o Windows mostra o padrão dele.
    function abrir(carga) {
        if (carga.item) carga.item.open(); else carga.active = true
    }
    // O nome do dia na pasta Documentos (um nome solto abriria o seletor na pasta do aplicativo), relido a cada abertura.
    function sugestaoDoBackup() {
        return StandardPaths.writableLocation(StandardPaths.DocumentsLocation) + "/" + preferencias.backup.nomeDoArquivo
    }
    function abrirSalvar() {
        if (cargaDoSalvar.item) cargaDoSalvar.item.selectedFile = sugestaoDoBackup()
        abrir(cargaDoSalvar)
    }
    Loader {
        id: cargaDoSalvar
        active: false
        visible: false  // sem isto o `Column` soma um espaço vazio por Loader
        sourceComponent: FileDialog {
            fileMode: FileDialog.SaveFile
            nameFilters: ["Backup do Kyron (*.zip)"]
            selectedFile: pagina.sugestaoDoBackup()
            onAccepted: preferencias.backup.exportar(selectedFile)
        }
        onLoaded: item.open()
    }
    Loader {
        id: cargaDoAbrir
        active: false
        visible: false  // sem isto o `Column` soma um espaço vazio por Loader
        sourceComponent: FileDialog {
            fileMode: FileDialog.OpenFile
            nameFilters: ["Backup do Kyron (*.zip)"]
            onAccepted: preferencias.backup.importar(selectedFile)
        }
        onLoaded: item.open()
    }
    Loader {
        id: cargaDaPasta
        active: false
        visible: false  // sem isto o `Column` soma um espaço vazio por Loader
        sourceComponent: FolderDialog {
            onAccepted: preferencias.backup.escolherPastaDosSaves(selectedFolder)
        }
        onLoaded: item.open()
    }

    GrupoDePreferencias {
        objectName: "grupoDaBibliotecaNoBackup"
        titulo: "Biblioteca"
        separada: true
        descricao: pagina.saves
            ? "Salve em um arquivo .zip a biblioteca completa, as cópias dos saves dos jogos e todas as configurações. A restauração substitui a biblioteca, as configurações e as cópias dos saves pelas do backup. Para devolver os saves aos jogos, use “Restaurar saves de todos os jogos”."
            : "Salve em um arquivo .zip a biblioteca completa e todas as configurações. A restauração substitui a biblioteca e as configurações atuais pelas do backup."

        LinhaDeBotao {
            buscavel: true
            objectName: "linhaExportarBackup"
            titulo: "Exportar para arquivo"
            onAcionada: pagina.abrirSalvar()
        }
        LinhaDeBotao {
            buscavel: true
            objectName: "linhaImportarBackup"
            titulo: "Importar de arquivo"
            onAcionada: pagina.abrir(cargaDoAbrir)
        }
    }

    GrupoDePreferencias {
        objectName: "grupoSaves"
        titulo: "Saves"

        LinhaDeBotoes {
            buscavel: true
            aparece: pagina.saves
            objectName: "linhaPastaDosSaves"
            titulo: "Pasta dos saves"
            subtitulo: preferencias.backup.pastaDosSaves
            quebraDoSubtitulo: Text.WrapAnywhere
            enabled: !preferencias.backup.trocandoPasta

            Botao {
                objectName: "linhaPastaDosSavesBotaoSecundario"
                text: "Usar a padrão"
                enabled: !preferencias.backup.pastaPadrao
                onClicked: preferencias.backup.usarPastaPadrao()
            }
            Botao {
                objectName: "linhaPastaDosSavesBotao"
                text: "Escolher"
                onClicked: pagina.abrir(cargaDaPasta)
            }
        }
        LinhaDeBotao {
            buscavel: true
            aparece: pagina.saves
            objectName: "linhaRestaurarSaves"
            titulo: "Restaurar saves de todos os jogos"
            onAcionada: preferencias.backup.restaurarTodos()
        }
    }
}
