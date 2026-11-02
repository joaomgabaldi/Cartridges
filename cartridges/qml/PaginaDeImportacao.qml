import QtQuick
import QtQuick.Dialogs

// A página Importação das Preferências. Só desenha: as chaves são do `preferencias` (cartridges/modelos/preferencias.py).
Column {
    id: pagina
    objectName: "paginaDeImportacao"

    width: parent ? parent.width : implicitWidth
    spacing: 24

    component Interruptor: LinhaDeAlternancia {
        property string chave
        buscavel: true
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

    // O progresso fica abaixo do cartão, num grupo só dele, com 12 de margem (`metadata_update_group`); o texto "N de M"
    // vai sobre a barra (`show-text`).
    Column {
        width: parent.width
        spacing: 12

        GrupoDePreferencias {
            objectName: "grupoAtualizarMetadados"

            LinhaDeAtualizacao {
                buscavel: true
                objectName: "linhaDosMetadados"
                titulo: "Atualizar metadados"
                subtitulo: "Busca dados para jogos já na biblioteca"
                // Sem nenhuma das duas fontes ligadas a busca não faria nada.
                enabled: preferencias.biblioteca.metadadosAtivos
                emAndamento: preferencias.biblioteca.rodando
                podeParar: true
                paradaPedida: preferencias.biblioteca.cancelado
                onAcionada: preferencias.biblioteca.atualizarMetadados()
                onParada: preferencias.biblioteca.cancelarMetadados()
            }
        }
        BarraDeProgresso {
            objectName: "linhaDosMetadadosProgresso"
            width: parent.width
            implicitHeight: 16
            visible: preferencias.biblioteca.rodando
            value: preferencias.biblioteca.fracao
            Text {
                objectName: "linhaDosMetadadosProgressoTexto"
                anchors.centerIn: parent
                text: preferencias.biblioteca.progresso
                textFormat: Text.PlainText
                color: Tema.texto
                font { family: Tema.fonte; pixelSize: Tema.legenda }
            }
        }
    }

    GrupoDePreferencias {
        objectName: "grupoAtalhos"
        titulo: "Atalhos"
        descricao: "Importa atalhos de jogos (.lnk e .url) de uma pasta. Funciona com Steam, Epic, Ubisoft Connect, Xbox/Microsoft Store e outros."
        separada: true

        // As filhas ficam fora da busca (`buscavel` falso): a `main` só indexa as linhas de nível de grupo.
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
