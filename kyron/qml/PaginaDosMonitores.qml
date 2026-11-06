import QtQuick

Column {
    id: pagina
    objectName: "paginaDosMonitores"

    readonly property bool semSegundo: preferencias.estado.semSegundoMonitor === true

    width: parent ? parent.width : implicitWidth
    spacing: 24

    GrupoDePreferencias {
        objectName: "grupoAoIniciarUmJogo"
        titulo: "Ao iniciar um jogo"
        // Sem contar horas, ou sem segundo monitor, o grupo inteiro apaga, título e descrição incluídos.
        enabled: preferencias.estado.moverAtivo === true
        descricao: "Move o Kyron para outro monitor (se disponível) em vez de minimizá-lo para a barra de tarefas."

        InterruptorDaPreferencia {
            chave: "session-move-window"
            titulo: "Mover para outro monitor"
            subtitulo: pagina.semSegundo ? "Requer um segundo monitor" : ""
        }
        LinhaDeEscolha {
            buscavel: true
            objectName: "linhaDoMonitor"
            titulo: "Monitor"
            model: preferencias.estado.monitores || []
            currentIndex: preferencias.estado.monitorEscolhido || 0
            enabled: preferencias.estado.monitorAtivo === true
            onEscolhido: indice => preferencias.escolherMonitor(indice)
        }
        LinhaDeBotao {
            buscavel: true
            objectName: "linhaIdentificarMonitores"
            titulo: "Identificar monitores"
            onAcionada: preferencias.identificarMonitores()
        }
    }

    GrupoDePreferencias {
        objectName: "grupoPapelDeParede"
        titulo: "Papel de parede"
        // Sem contar horas não há sessão para trocar o papel de parede: o grupo inteiro apaga.
        enabled: preferencias.estado.papelDeParedeAtivo === true
        descricao: "Durante a sessão, substitui temporariamente o papel de parede dos outros monitores por uma imagem relacionada ao jogo."

        InterruptorDaPreferencia {
            chave: "session-wallpaper"
            titulo: "Trocar o papel de parede dos outros monitores"
            subtitulo: pagina.semSegundo ? "Requer um segundo monitor" : ""
            enabled: preferencias.estado.papelDeParedeLigavel === true
        }
        LinhaDeTexto {
            buscavel: true
            objectName: "campoDaChaveDoWallhaven"
            titulo: "Chave da API do wallhaven (opcional)"
            text: preferencias.valores["wallhaven-key"] || ""
            enabled: preferencias.estado.chaveWallhavenAtiva === true
            onEditado: preferencias.definirTexto("wallhaven-key", text)
        }
    }
}
