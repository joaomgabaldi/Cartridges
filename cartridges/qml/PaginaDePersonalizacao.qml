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
        buscavel: true
        objectName: "interruptor-" + chave
        checked: preferencias.valores[chave] === true
        onAlternado: preferencias.definir(chave, checked)
    }

    GrupoDePreferencias {
        objectName: "grupoBarraSuperior"
        titulo: "Barra superior"

        Interruptor {
            chave: "show-news-button"
            titulo: "Mostrar o botão Novidades"
        }
    }

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
            buscavel: true
            objectName: "linhaDoMonitor"
            titulo: "Monitor"
            model: preferencias.estado.monitores || []
            currentIndex: preferencias.estado.monitorEscolhido || 0
            enabled: preferencias.estado.monitorAtivo === true
            onEscolhido: indice => preferencias.escolherMonitor(indice)
        }
        // Sempre clicável: é olhando para as telas que se decide qual escolher.
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
            buscavel: true
            objectName: "campoDaChaveDoWallhaven"
            titulo: "Chave da API do wallhaven (opcional)"
            text: preferencias.valores["wallhaven-key"] || ""
            enabled: preferencias.estado.chaveWallhavenAtiva === true
            onEditado: preferencias.definirTexto("wallhaven-key", text)
        }
    }

    // A iluminação inteligente vale também fora da sessão (a cor do app): não segue a contagem de horas. O interruptor
    // só liga com fita configurada; "Configurar" fica sempre clicável. O resto acompanha o interruptor.
    GrupoDePreferencias {
        id: grupoIluminacao
        objectName: "grupoIluminacao"
        titulo: "Iluminação inteligente"
        descricao: "Muda a cor da iluminação inteligente enquanto o Cartridges está aberto: a cor do aplicativo fora do jogo e a cor do jogo durante a sessão. Ao fechar o aplicativo, a iluminação inteligente volta ao estado anterior."

        readonly property bool ligada: preferencias.valores["session-fita"] === true

        Interruptor {
            chave: "session-fita"
            titulo: "Mudar a cor da iluminação inteligente"
            subtitulo: preferencias.fitas.subtitulo
            enabled: preferencias.fitas.configuradas > 0
        }
        LinhaDeNumero {
            buscavel: true
            objectName: "linhaDoBrilhoDasFitas"
            titulo: "Brilho (%)"
            subtitulo: "Aplicado aos jogos sem brilho próprio definido"
            de: 1
            ate: 100
            passo: 1
            pagina: 10
            value: preferencias.fitas.brilho
            enabled: grupoIluminacao.ligada
            onAlterado: valor => preferencias.fitas.definirBrilho(valor)
        }
        LinhaDeAcao {
            buscavel: true
            objectName: "linhaDoBrilhoPorDispositivo"
            titulo: "Brilho máximo por dispositivo"
            subtitulo: "Define o brilho máximo de cada dispositivo"
            glifo: ""  // seguir
            dica: "Ajustar o brilho de cada dispositivo"
            enabled: grupoIluminacao.ligada
            onAcionada: preferencias.abrirBrilhoPorDispositivo()
        }
        Interruptor {
            chave: "fita-acompanha-tela"
            titulo: "Cor acompanha a tela do jogo"
            subtitulo: "A cor da iluminação acompanha, devagar, a cor predominante do jogo. Jogos com cor escolhida manualmente mantêm a cor fixa."
            enabled: grupoIluminacao.ligada
        }
        LinhaDeAcao {
            buscavel: true
            objectName: "linhaCalibrarFitas"
            titulo: "Calibrar as cores"
            subtitulo: "Ajusta cada dispositivo para reproduzir as cores como a tela"
            glifo: ""  // seguir
            dica: "Abrir o assistente de calibração"
            enabled: grupoIluminacao.ligada
            onAcionada: preferencias.abrirCalibracao()
        }
        LinhaDeCor {
            buscavel: true
            objectName: "linhaDaCorDoApp"
            titulo: "Cor do app"
            subtitulo: "A cor da iluminação inteligente com o aplicativo aberto e nenhum jogo em execução"
            cor: preferencias.fitas.corDoApp
            padrao: preferencias.fitas.corDoAppPadrao
            dicaDaAmostra: "Escolher a cor da iluminação inteligente"
            enabled: grupoIluminacao.ligada
            onEscolhida: cor => preferencias.fitas.escolherCorDoApp(cor)
            onVoltar: preferencias.fitas.voltarCorDoApp()
        }
        LinhaDeAcao {
            buscavel: true
            objectName: "linhaConfigurarFitas"
            titulo: "Configurar a iluminação inteligente"
            subtitulo: "Busca os dispositivos na sua conta da Tuya"
            glifo: ""  // engrenagem
            dica: "Abrir assistente"
            onAcionada: preferencias.abrirConfiguracaoDasFitas()
        }
        LinhaDeAcao {
            buscavel: true
            objectName: "linhaTestarFitas"
            titulo: "Testar"
            subtitulo: preferencias.fitas.resultadoDoTeste || "Acende cada dispositivo na cor do aplicativo"
            glifo: preferencias.fitas.testando ? "" : ""  // parar : reproduzir
            dica: "Ligar a iluminação inteligente"
            enabled: grupoIluminacao.ligada
            onAcionada: preferencias.fitas.testar()
        }
    }
}
