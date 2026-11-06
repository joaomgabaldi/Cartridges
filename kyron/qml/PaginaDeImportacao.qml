import QtQuick
import QtQuick.Dialogs

Column {
    id: pagina
    objectName: "paginaDeImportacao"

    width: parent ? parent.width : implicitWidth
    spacing: 24

    function escolherPasta() {
        if (carga.item) carga.item.open(); else carga.active = true
    }
    Loader {
        id: carga
        active: false
        sourceComponent: FolderDialog {
            onAccepted: preferencias.escolherPastaDosAtalhos(selectedFolder)
        }
        onLoaded: item.open()
    }

    GrupoDePreferencias {
        objectName: "grupoComportamentoDaImportacao"
        titulo: "Comportamento"

        InterruptorDaPreferencia { chave: "auto-import"; titulo: "Importar jogos automaticamente" }
        InterruptorDaPreferencia { chave: "remove-missing"; titulo: "Remover jogos desinstalados" }
    }

    GrupoDePreferencias {
        objectName: "grupoAtalhos"
        titulo: "Atalhos"
        descricao: "Importa atalhos de jogos (.lnk e .url) de uma pasta. Funciona com Steam, Epic, Ubisoft Connect, Xbox/Microsoft Store e outros."
        separada: true

        // As filhas ficam fora da busca (`buscavel` falso): só as linhas de nível de grupo entram.
        LinhaExpansora {
            buscavel: true
            objectName: "interruptor-shortcuts"
            icone: "shortcuts-source"
            titulo: "Atalhos"
            checked: preferencias.valores["shortcuts"] === true
            onAlternado: preferencias.definir("shortcuts", checked)

            LinhaDeBotoes {
                objectName: "linhaDaPasta"
                titulo: "Pasta"
                subtitulo: preferencias.estado.pastaDosAtalhos || ""
                propriedade: true
                ativavel: botaoDaPasta
                Botao {
                    id: botaoDaPasta
                    objectName: "linhaDaPastaBotao"
                    estilo: "plano"
                    icone: "folder"
                    dica: "Selecionar pasta"
                    onClicked: pagina.escolherPasta()
                }
            }
            LinhaDeAlternancia {
                objectName: "interruptor-shortcuts-recursive"
                titulo: "Buscar em subpastas"
                checked: preferencias.valores["shortcuts-recursive"] === true
                onAlternado: preferencias.definir("shortcuts-recursive", checked)
            }
        }
    }
}
