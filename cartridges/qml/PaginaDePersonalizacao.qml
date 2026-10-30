import QtQuick

// A página Personalização das Preferências. Só desenha: as chaves e o estado são do `preferencias` (cartridges/modelos/preferencias.py).
Column {
    id: pagina
    objectName: "paginaDePersonalizacao"

    readonly property bool semSegundo: preferencias.estado.semSegundoMonitor === true

    width: parent ? parent.width : implicitWidth
    spacing: 24

    component Interruptor: LinhaDeAlternancia {
        property string chave
        objectName: "interruptor-" + chave
        checked: preferencias.valores[chave] === true
        onAlternado: preferencias.definir(chave, checked)
    }

    // shortcut: falta o grupo "Barra superior" (D64: o botão Novidades não aparece, sem `show-news-button`); na `main` é o primeiro grupo da página, antes de "Biblioteca".
    GrupoDePreferencias {
        objectName: "grupoBiblioteca"
        titulo: "Biblioteca"

        Interruptor {
            chave: "cover-autoplay"
            titulo: "Reproduzir capas animadas automaticamente"
            subtitulo: "As capas animadas são reproduzidas na biblioteca automaticamente e em loop."
        }
    }

    GrupoDePreferencias {
        objectName: "grupoAoIniciarUmJogo"
        titulo: "Ao iniciar um jogo"
        descricao: "Move o Cartridges para outro monitor (se disponível) em vez de minimizá-lo para a barra de tarefas."

        Interruptor {
            chave: "session-move-window"
            titulo: "Mover para outro monitor"
            subtitulo: pagina.semSegundo ? "Requer um segundo monitor" : ""
            enabled: preferencias.estado.moverAtivo === true
        }
        LinhaDeEscolha {
            objectName: "linhaDoMonitor"
            titulo: "Monitor"
            model: preferencias.estado.monitores || []
            currentIndex: preferencias.estado.monitorEscolhido || 0
            enabled: preferencias.estado.monitorAtivo === true
            onEscolhido: indice => preferencias.escolherMonitor(indice)
        }
        // Sempre clicável: é olhando para as telas que se decide qual escolher.
        LinhaDeBotao {
            objectName: "linhaIdentificarMonitores"
            titulo: "Identificar monitores"
            onAcionada: preferencias.identificarMonitores()
        }
    }

    GrupoDePreferencias {
        objectName: "grupoPapelDeParede"
        titulo: "Papel de parede"
        // Sem contar horas não há sessão para trocar o papel de parede: o grupo inteiro apaga, como na `main`.
        enabled: preferencias.estado.papelDeParedeAtivo === true
        descricao: "Durante a sessão, substitui temporariamente o papel de parede dos outros monitores por uma imagem relacionada ao jogo."

        Interruptor {
            chave: "session-wallpaper"
            titulo: "Trocar o papel de parede dos outros monitores"
            subtitulo: pagina.semSegundo ? "Requer um segundo monitor" : ""
            enabled: preferencias.estado.papelDeParedeLigavel === true
        }
        LinhaDeTexto {
            objectName: "campoDaChaveDoWallhaven"
            titulo: "Chave da API do wallhaven (opcional)"
            text: preferencias.valores["wallhaven-key"] || ""
            enabled: preferencias.estado.chaveWallhavenAtiva === true
            onEditado: preferencias.definirTexto("wallhaven-key", text)
        }
    }

    // shortcut: faltam os grupos das fitas de LED e da iluminação das conquistas (Task 5); entram aqui, depois do "Papel de parede".
}
