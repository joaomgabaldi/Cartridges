import QtQuick

Column {
    id: pagina
    objectName: "paginaGeral"

    readonly property bool saves: preferencias.estado.savesDisponiveis === true

    width: parent ? parent.width : implicitWidth
    spacing: 24

    GrupoDePreferencias {
        objectName: "grupoAoIniciarUmJogoGeral"
        titulo: "Ao iniciar um jogo"

        InterruptorDaPreferencia {
            chave: "minimize-after-launch"
            titulo: "Minimizar ao iniciar um jogo"
            subtitulo: "Minimiza a janela ao iniciar um jogo quando a contagem de horas está desligada"
            // Com a contagem de horas ligada a janela sempre minimiza (a da sessão assume): a chave fica ligada e travada.
            enabled: preferencias.estado.minimizarTravado !== true
        }
    }

    GrupoDePreferencias {
        objectName: "grupoSessoes"
        titulo: "Sessões"

        InterruptorDaPreferencia {
            chave: "playtime-tracking"
            titulo: "Contar horas de jogo"
            subtitulo: pagina.saves
                ? "Registra o tempo de cada sessão e faz o backup dos saves ao fim dela; quando o jogo não pode ser acompanhado automaticamente, abre uma janela compacta para encerrar a sessão"
                : "Registra o tempo de cada sessão; quando o jogo não pode ser acompanhado automaticamente, abre uma janela compacta para encerrar a sessão"
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
        objectName: "grupoJogador"
        titulo: "Jogador"
        descricao: "Aplicados automaticamente aos jogos que guardam essas informações em arquivos de configuração."

        LinhaDeTexto {
            buscavel: true
            objectName: "campoDoNomeDoJogador"
            titulo: "Nome do jogador"
            subtitulo: erro ? "Use até 32 caracteres, sem acentos nem símbolos especiais." : "Até 32 caracteres, sem acentos."
            erro: !preferencias.nomeDoJogadorValido(text)
            onTerminado: preferencias.definirTexto("nome-do-jogador", text)
            // Lido a cada abertura, sem ligação: com ela, o espaço digitado sumiria antes da letra seguinte.
            // A página nasce com o app, antes de `valores` existir; ler só no `onCompleted` deixava o campo vazio.
            // Propriedade QML, e não o `alterado` do modelo: ela só avisa na troca, não a cada preferência gravada.
            readonly property bool dialogoAberto: preferencias.aberto
            onDialogoAbertoChanged: if (dialogoAberto) text = preferencias.valores["nome-do-jogador"] || ""
        }
        LinhaDeEscolha {
            buscavel: true
            objectName: "linhaDoIdiomaDosJogos"
            titulo: "Idioma dos jogos"
            model: ["Não alterar"].concat(preferencias.opcoesDeIdioma.map(i => i.nome))
            currentIndex: 1 + preferencias.opcoesDeIdioma.findIndex(i => i.codigo === preferencias.valores["idioma-do-jogador"])
            onEscolhido: indice => preferencias.definirTexto("idioma-do-jogador", indice === 0 ? "" : preferencias.opcoesDeIdioma[indice - 1].codigo)
        }
    }

    GrupoDePreferencias {
        objectName: "grupoInterface"
        titulo: "Interface"

        InterruptorDaPreferencia {
            chave: "show-news-button"
            titulo: "Mostrar o botão Novidades"
        }
        InterruptorDaPreferencia {
            chave: "cover-autoplay"
            titulo: "Reproduzir capas animadas automaticamente"
            subtitulo: "As capas animadas são reproduzidas na biblioteca automaticamente e em loop."
        }
    }
}
