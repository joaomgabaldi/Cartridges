import QtQuick

Column {
    id: pagina
    objectName: "paginaDoControle"

    // Sem 3D o Big Picture não abre: as duas linhas dele dizem por quê no lugar do subtítulo.
    readonly property string sem3d: preferencias.estado.subtituloSem3d || ""

    width: parent ? parent.width : implicitWidth
    spacing: 24

    GrupoDePreferencias {
        objectName: "grupoControle"
        titulo: "Controle"

        InterruptorDaPreferencia {
            chave: "gamepad"
            titulo: "Usar controle Xbox"
            subtitulo: "Permite navegar no aplicativo com um controle"
        }
        InterruptorDaPreferencia {
            chave: "gamepad-rumble"
            titulo: "Vibração"
            subtitulo: "Vibra ao mover a seleção, ao chegar ao fim da lista e ao iniciar um jogo"
            enabled: preferencias.estado.rumbleAtivo === true
        }
    }

    GrupoDePreferencias {
        objectName: "grupoBigPicture"
        titulo: "Big Picture"

        InterruptorDaPreferencia {
            chave: "big-picture-ao-conectar"
            titulo: "Abrir o Big Picture ao usar um controle"
            subtitulo: pagina.sem3d !== "" ? pagina.sem3d : "Abre o Big Picture ao iniciar o aplicativo com um controle conectado ou ao conectar um controle na biblioteca"
            enabled: preferencias.estado.bigPictureAtivo === true
        }
        InterruptorDaPreferencia {
            chave: "big-picture-som"
            titulo: "Som ao trocar de capa"
            subtitulo: pagina.sem3d !== "" ? pagina.sem3d : "Toca um clique curto a cada capa no Big Picture"
            enabled: preferencias.estado.somDoBigPictureAtivo === true
        }
    }
}
