import QtQuick

// A iluminação inteligente vale também fora da sessão (a cor do app): não segue a contagem de horas. O interruptor
// só liga com fita configurada; "Configurar" fica sempre clicável. O resto acompanha o interruptor.
Column {
    id: pagina
    objectName: "paginaDaIluminacao"

    readonly property bool ligada: preferencias.valores["session-fita"] === true

    width: parent ? parent.width : implicitWidth
    spacing: 24

    GrupoDePreferencias {
        objectName: "grupoDispositivos"
        titulo: "Dispositivos"
        descricao: "Muda a cor da iluminação inteligente enquanto o Kyron está aberto: a cor do aplicativo fora do jogo e a cor do jogo durante a sessão. Ao fechar o aplicativo, a iluminação inteligente volta ao estado anterior."

        LinhaDeBotoes {
            buscavel: true
            objectName: "linhaDoBrilhoPorDispositivo"
            titulo: "Brilho máximo por dispositivo"
            subtitulo: "Define o brilho máximo de cada dispositivo"
            ativavel: botaoDoBrilho
            enabled: pagina.ligada
            Botao {
                id: botaoDoBrilho
                objectName: "linhaDoBrilhoPorDispositivoBotao"
                estilo: "plano"
                icone: "go-next"
                dica: "Ajustar o brilho de cada dispositivo"
                onClicked: preferencias.abrirBrilhoPorDispositivo()
            }
        }
        LinhaDeBotoes {
            buscavel: true
            objectName: "linhaCalibrarFitas"
            titulo: "Calibrar as cores"
            subtitulo: "Ajusta cada dispositivo para reproduzir as cores como a tela"
            ativavel: botaoDaCalibracao
            enabled: pagina.ligada
            Botao {
                id: botaoDaCalibracao
                objectName: "linhaCalibrarFitasBotao"
                estilo: "plano"
                icone: "go-next"
                dica: "Abrir o assistente de calibração"
                onClicked: preferencias.abrirCalibracao()
            }
        }
        LinhaDeBotoes {
            buscavel: true
            objectName: "linhaConfigurarFitas"
            titulo: "Configurar a iluminação inteligente"
            subtitulo: "Busca os dispositivos na sua conta da Tuya"
            ativavel: botaoDaConfiguracao
            Botao {
                id: botaoDaConfiguracao
                objectName: "linhaConfigurarFitasBotao"
                estilo: "plano"
                icone: "applications-engineering"
                dica: "Abrir assistente"
                onClicked: preferencias.abrirConfiguracaoDasFitas()
            }
        }
        LinhaDeBotoes {
            buscavel: true
            objectName: "linhaTestarFitas"
            titulo: "Testar"
            subtitulo: preferencias.fitas.resultadoDoTeste || "Acende cada dispositivo na cor do aplicativo"
            ativavel: botaoDoTeste
            enabled: pagina.ligada
            Botao {
                id: botaoDoTeste
                objectName: "linhaTestarFitasBotao"
                estilo: "plano"
                icone: preferencias.fitas.testando ? "media-playback-stop" : "media-playback-start"
                dica: "Ligar a iluminação inteligente"
                onClicked: preferencias.fitas.testar()
            }
        }
    }

    GrupoDePreferencias {
        objectName: "grupoCores"
        titulo: "Cores"

        InterruptorDaPreferencia {
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
            enabled: pagina.ligada
            onAlterado: valor => preferencias.fitas.definirBrilho(valor)
        }
        InterruptorDaPreferencia {
            chave: "fita-acompanha-tela"
            titulo: "Cor acompanha a tela do jogo"
            subtitulo: "A cor da iluminação acompanha, devagar, a cor predominante do jogo. Jogos com cor escolhida manualmente mantêm a cor fixa."
            enabled: pagina.ligada
        }
        LinhaDeCor {
            buscavel: true
            objectName: "linhaDaCorDoApp"
            titulo: "Cor do app"
            subtitulo: "A cor da iluminação inteligente com o aplicativo aberto e nenhum jogo em execução"
            cor: preferencias.fitas.corDoApp
            padrao: preferencias.fitas.corDoAppPadrao
            dicaDaAmostra: "Escolher a cor da iluminação inteligente"
            enabled: pagina.ligada
            onEscolhida: cor => preferencias.fitas.escolherCorDoApp(cor)
            onVoltar: preferencias.fitas.voltarCorDoApp()
        }
    }
}
