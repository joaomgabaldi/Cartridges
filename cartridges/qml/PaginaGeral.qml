import QtQuick

// A página Geral das Preferências. Só desenha: as chaves e as travas são do `preferencias` (cartridges/modelos/preferencias.py).
Column {
    id: pagina
    objectName: "paginaGeral"

    // Sem 3D o Big Picture não abre: as duas linhas dele dizem por quê no lugar do subtítulo (D47).
    readonly property string sem3d: preferencias.estado.subtituloSem3d || ""

    width: parent ? parent.width : implicitWidth
    spacing: 24

    component Interruptor: LinhaDeAlternancia {
        property string chave
        objectName: "interruptor-" + chave
        checked: preferencias.valores[chave] === true
        onAlternado: preferencias.definir(chave, checked)
    }

    // shortcut: faltam "Backup da sua biblioteca", "Atualizações", "Zona de perigo" e o subtítulo de "Contar horas de jogo" que promete o backup dos saves, todos do plano 8 (D64); entram aqui, depois de "Comportamento".
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
            subtitulo: "Registra o tempo de cada sessão; quando o jogo não pode ser acompanhado automaticamente, abre uma janela compacta para encerrar a sessão"
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
}
