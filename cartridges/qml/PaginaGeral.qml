import QtQuick
import QtCore
import QtQuick.Dialogs

// A página Geral das Preferências. Só desenha: as chaves e as travas são do `preferencias` (cartridges/modelos/preferencias.py).
Column {
    id: pagina
    objectName: "paginaGeral"

    // Sem 3D o Big Picture não abre: as duas linhas dele dizem por quê no lugar do subtítulo (D47).
    readonly property string sem3d: preferencias.estado.subtituloSem3d || ""
    // Sem o Ludusavi no pacote não há saves a configurar: as linhas deles somem e os textos não os prometem.
    readonly property bool saves: preferencias.estado.savesDisponiveis === true

    width: parent ? parent.width : implicitWidth
    spacing: 24

    component Interruptor: LinhaDeAlternancia {
        property string chave
        buscavel: true
        objectName: "interruptor-" + chave
        checked: preferencias.valores[chave] === true
        onAlternado: preferencias.definir(chave, checked)
    }

    // Criados só ao clicar: os seletores nativos não precisam existir antes.
    function abrir(carga) {
        if (carga.item) carga.item.open(); else carga.active = true
    }
    // O nome do dia na pasta Documentos (um nome solto abriria o seletor na pasta do aplicativo); relido a cada abertura:
    // depois de uma exportação o diálogo guardaria o arquivo anterior.
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
            title: "Exportar para arquivo"
            fileMode: FileDialog.SaveFile
            nameFilters: ["Backup do Cartridges (*.zip)"]
            // O nome sugerido vai na pasta Documentos: um nome solto abriria o seletor na pasta do aplicativo.
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
            title: "Importar de arquivo"
            fileMode: FileDialog.OpenFile
            nameFilters: ["Backup do Cartridges (*.zip)"]
            onAccepted: preferencias.backup.importar(selectedFile)
        }
        onLoaded: item.open()
    }
    Loader {
        id: cargaDaPasta
        active: false
        visible: false  // sem isto o `Column` soma um espaço vazio por Loader
        sourceComponent: FolderDialog {
            title: "Selecionar pasta"
            onAccepted: preferencias.backup.escolherPastaDosSaves(selectedFolder)
        }
        onLoaded: item.open()
    }

    GrupoDePreferencias {
        objectName: "grupoComportamentoGeral"
        titulo: "Comportamento"

        Interruptor {
            chave: "minimize-after-launch"
            titulo: "Minimizar ao iniciar um jogo"
            subtitulo: "Minimiza a janela ao iniciar um jogo quando a contagem de horas está desligada"
            // Com a contagem de horas ligada a janela sempre minimiza (a da sessão assume): a chave fica ligada e travada.
            enabled: preferencias.estado.minimizarTravado !== true
        }
        Interruptor {
            chave: "playtime-tracking"
            titulo: "Contar horas de jogo"
            subtitulo: pagina.saves
                ? "Registra o tempo de cada sessão e faz o backup dos saves ao fim dela; quando o jogo não pode ser acompanhado automaticamente, abre uma janela compacta para encerrar a sessão"
                : "Registra o tempo de cada sessão; quando o jogo não pode ser acompanhado automaticamente, abre uma janela compacta para encerrar a sessão"
        }
        Interruptor {
            chave: "gamepad"
            titulo: "Usar controle Xbox"
            subtitulo: "Permite navegar no aplicativo com um controle"
        }
        Interruptor {
            chave: "gamepad-rumble"
            titulo: "Vibração"
            subtitulo: "Vibra ao mover a seleção, ao chegar ao fim da lista e ao iniciar um jogo"
            enabled: preferencias.estado.rumbleAtivo === true
        }
        Interruptor {
            chave: "big-picture-ao-conectar"
            titulo: "Abrir o Big Picture ao usar um controle"
            subtitulo: pagina.sem3d !== "" ? pagina.sem3d : "Abre o Big Picture ao iniciar o aplicativo com um controle conectado ou ao conectar um controle na biblioteca"
            enabled: preferencias.estado.bigPictureAtivo === true
        }
        Interruptor {
            chave: "big-picture-som"
            titulo: "Som ao trocar de capa"
            subtitulo: pagina.sem3d !== "" ? pagina.sem3d : "Toca um clique curto a cada capa no Big Picture"
            enabled: preferencias.estado.somDoBigPictureAtivo === true
        }
        LinhaDeNumero {
            buscavel: true
            objectName: "linhaDaEspera"
            titulo: "Tempo de espera ao fechar o jogo"
            subtitulo: "Segundos de espera após o jogo fechar antes de encerrar a sessão, para que um reinício do jogo não divida a sessão"
            de: 0
            ate: 120
            passo: 1
            pagina: 5
            value: preferencias.valores["process-tracking-grace"] || 0
            onAlterado: valor => preferencias.definir("process-tracking-grace", valor)
        }
    }

    GrupoDePreferencias {
        objectName: "grupoBackupDaBiblioteca"
        titulo: "Backup da sua biblioteca"
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
        LinhaDeAcao {
            buscavel: true
            aparece: pagina.saves
            objectName: "linhaPastaDosSaves"
            titulo: "Pasta dos saves"
            subtitulo: preferencias.backup.pastaDosSaves
            rotulo: "Escolher"
            rotuloSecundario: "Usar a padrão"
            secundarioAtivo: !preferencias.backup.pastaPadrao
            // A troca espera a trava dos saves e copia arquivos: a linha fica apagada até acabar.
            enabled: !preferencias.backup.trocandoPasta
            onAcionada: pagina.abrir(cargaDaPasta)
            onSecundaria: preferencias.backup.usarPastaPadrao()
        }
        LinhaDeBotao {
            buscavel: true
            aparece: pagina.saves
            objectName: "linhaRestaurarSaves"
            titulo: "Restaurar saves de todos os jogos"
            onAcionada: preferencias.backup.restaurarTodos()
        }
    }

    // O AppUpdater (D82); sem ele no contexto (os testes das outras páginas), o botão avisa que não foi possível.
    readonly property QtObject servicoDeAtualizacao: typeof atualizador === "undefined" ? null : atualizador

    GrupoDePreferencias {
        objectName: "grupoAtualizacoes"
        titulo: "Atualizações"

        LinhaDeAcao {
            buscavel: true
            objectName: "linhaBuscarAtualizacoes"
            titulo: "Buscar atualizações"
            subtitulo: "Versão atual: " + (pagina.servicoDeAtualizacao ? pagina.servicoDeAtualizacao.versao : "")
            rotulo: "Buscar"
            // Só o botão apaga durante a busca, como na `main`.
            botaoDaLinha.enabled: !pagina.servicoDeAtualizacao || !pagina.servicoDeAtualizacao.buscando
            onAcionada: {
                if (pagina.servicoDeAtualizacao) pagina.servicoDeAtualizacao.buscarAgora()
                else aplicativo.avisar("Não foi possível buscar atualizações")
            }
        }
    }

    GrupoDePreferencias {
        objectName: "grupoZonaDePerigo"
        titulo: "Zona de perigo"

        LinhaDeBotao {
            buscavel: true
            objectName: "linhaRedefinir"
            titulo: "Redefinir Cartridges"
            destrutivo: true
            onAcionada: preferencias.backup.redefinir()
        }
    }
}
