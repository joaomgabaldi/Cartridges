import QtQuick

// A página Conquistas das Preferências. Só desenha: as chaves e o estado são do `preferencias` (cartridges/modelos/preferencias.py).
Column {
    id: pagina
    objectName: "paginaDasConquistas"

    width: parent ? parent.width : implicitWidth
    spacing: 24

    component Interruptor: LinhaDeAlternancia {
        property string chave
        buscavel: true
        objectName: "interruptor-" + chave
        checked: preferencias.valores[chave] === true
        onAlternado: preferencias.definir(chave, checked)
    }

    TextMetrics {
        id: medidaDoCanto
        font { family: Tema.fonte; pixelSize: 14 }
        text: "Canto superior esquerdo"
    }

    // As contas existem só com as Preferências abertas; o `Loader` evita ler um `contas` nulo ao fechar.
    Loader {
        objectName: "carregadorDasContas"
        width: parent.width
        active: preferencias.contas !== null
        readonly property int linhasAMostrar: item ? item.linhasAMostrar : 0
        // Sem conta que case, o Loader sai (senão guardaria a altura do grupo).
        visible: active && linhasAMostrar > 0
        sourceComponent: GrupoDasContas { contas: preferencias.contas }
    }

    GrupoDePreferencias {
        objectName: "grupoDaChaveDaSteam"
        titulo: "Steam Web API"
        // Texto nosso, com o único link (só http/https chega ao navegador, em `abrirEndereco`).
        descricao: 'Informe a chave da Steam Web API. <a href="https://steamcommunity.com/dev/apikey">Obtenha aqui</a>.'
        descricaoRica: true
        onLinkAcionado: endereco => preferencias.abrirEndereco(endereco)

        LinhaDeTexto {
            buscavel: true
            objectName: "campoDaChaveDaSteam"
            titulo: "Chave da API"
            text: preferencias.valores["conquistas-chave-steam"] || ""
            onEditado: preferencias.definirTexto("conquistas-chave-steam", text)
        }
    }

    GrupoDePreferencias {
        objectName: "grupoExibicao"
        titulo: "Exibição"

        Interruptor {
            chave: "conquistas-mostrar-ocultas"
            titulo: "Mostrar descrição das conquistas ocultas"
            subtitulo: "Exibe o nome e a descrição das conquistas ocultas ainda não desbloqueadas"
        }
    }

    GrupoDePreferencias {
        objectName: "grupoDuranteOJogo"
        titulo: "Durante o jogo"

        Interruptor {
            chave: "conquistas-aviso"
            titulo: "Mostrar aviso durante o jogo"
            subtitulo: "Exibe um aviso por cima do jogo ao desbloquear uma conquista. Nos jogos da Steam, aparece o aviso da própria Steam."
        }
        Interruptor {
            chave: "conquistas-aviso-som"
            titulo: "Tocar som com o aviso"
            subtitulo: "Reproduz um som quando o aviso aparece"
            enabled: preferencias.estado.avisoAtivo === true
        }
        LinhaDeNumero {
            buscavel: true
            objectName: "linhaDoVolumeDoAviso"
            titulo: "Volume do som (%)"
            de: 10
            ate: 100
            passo: 5
            pagina: 10
            value: preferencias.valores["conquistas-aviso-som-volume"] || 100
            enabled: preferencias.estado.volumeDoAvisoAtivo === true
            onAlterado: valor => preferencias.definir("conquistas-aviso-som-volume", valor)
        }
        LinhaDeEscolha {
            buscavel: true
            objectName: "linhaDaPosicaoDoAviso"
            titulo: "Posição do aviso"
            // O texto mais longo inteiro, com o recuo e a seta da caixa (LinhaDeEscolha).
            larguraDaCaixa: Math.ceil(medidaDoCanto.width) + 70
            model: ["Canto superior esquerdo", "Canto superior direito", "Canto inferior esquerdo", "Canto inferior direito"]
            currentIndex: preferencias.estado.posicaoDoAviso
            enabled: preferencias.estado.avisoAtivo === true
            onEscolhido: indice => preferencias.escolherPosicaoDoAviso(indice)
        }
        Interruptor {
            chave: "conquistas-iluminacao"
            titulo: "Piscar a iluminação inteligente"
            subtitulo: "Os dispositivos piscam ao desbloquear uma conquista"
        }
        // Com o balão aberto, as fitas mostram a cor escolhida; ao fechar, voltam à cor do app.
        LinhaDeCor {
            buscavel: true
            objectName: "linhaDaCorDoAlerta"
            titulo: "Cor do alerta"
            subtitulo: "A cor da iluminação inteligente ao desbloquear uma conquista"
            cor: preferencias.fitas.corDoPulso
            padrao: preferencias.fitas.corDoPulsoPadrao
            dicaDaAmostra: "Escolher a cor do alerta"
            enabled: preferencias.estado.alertaAtivo === true
            onAberta: preferencias.fitas.abrirCorDoPulso()
            onFechada: preferencias.fitas.fecharCorDoPulso()
            onEscolhida: cor => preferencias.fitas.escolherCorDoPulso(cor)
            onVoltar: preferencias.fitas.voltarCorDoPulso()
        }
        LinhaDeEscolha {
            buscavel: true
            objectName: "linhaDoEstiloDoAlerta"
            titulo: "Estilo do alerta"
            model: ["Piscar", "Respirar", "Piscar rápido", "Brilho longo"]
            currentIndex: preferencias.fitas.estiloDoPulso
            enabled: preferencias.estado.alertaAtivo === true
            onEscolhido: indice => preferencias.fitas.escolherEstiloDoPulso(indice)
        }
        LinhaDeBotao {
            buscavel: true
            objectName: "linhaDoTesteDoAlerta"
            titulo: "Testar o alerta"
            enabled: preferencias.estado.alertaAtivo === true
            onAcionada: preferencias.fitas.testarAlerta()
        }
        LinhaDeBotao {
            buscavel: true
            objectName: "linhaDoExemplo"
            titulo: "Mostrar um aviso de exemplo"
            onAcionada: preferencias.mostrarAvisoDeExemplo()
        }
    }
}
