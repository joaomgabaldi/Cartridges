import QtQuick

Column {
    id: pagina
    objectName: "paginaDosMetadados"

    width: parent ? parent.width : implicitWidth
    spacing: 24

    GrupoDePreferencias {
        objectName: "grupoMetadados"
        titulo: "Metadados"

        InterruptorDaPreferencia {
            chave: "steam-metadata"
            titulo: "Buscar metadados da Steam"
            subtitulo: "Busca na Steam título, desenvolvedora, publicadora, lançamento, gênero, descrição, avaliações e compatibilidade com controle"
        }
        InterruptorDaPreferencia {
            chave: "hltb-metadata"
            titulo: "Buscar tempos do HowLongToBeat"
            subtitulo: "Busca as estimativas de história principal, extras e completista"
        }
    }

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
        Column {
            width: parent.width
            spacing: 0
            visible: preferencias.biblioteca.rodando
            Text {
                objectName: "linhaDosMetadadosProgressoTexto"
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                text: preferencias.biblioteca.progresso
                textFormat: Text.PlainText
                color: Tema.textoSecundario
                font { family: Tema.fonte; pixelSize: Tema.legenda; features: { "tnum": 1 } }
            }
            BarraDeProgresso {
                objectName: "linhaDosMetadadosProgresso"
                width: parent.width
                value: preferencias.biblioteca.fracao
            }
        }
    }

    GrupoDePreferencias {
        objectName: "grupoSteamGridDB"
        titulo: "SteamGridDB"
        // Texto nosso, com o único link (só http/https chega ao navegador, em `abrirEndereco`).
        descricao: 'É necessária uma chave da API para usar o SteamGridDB. <a href="https://www.steamgriddb.com/profile/preferences/api">Obtenha aqui</a>.'
        descricaoRica: true
        onLinkAcionado: endereco => preferencias.abrirEndereco(endereco)

        LinhaDeTexto {
            buscavel: true
            objectName: "campoDaChaveDoSgdb"
            titulo: "Chave da API"
            text: preferencias.valores["sgdb-key"] || ""
            onEditado: preferencias.definirTexto("sgdb-key", text)
        }
        InterruptorDaPreferencia {
            chave: "sgdb"
            titulo: "Usar o SteamGridDB"
            subtitulo: "Baixa imagens ao adicionar ou importar jogos"
            enabled: preferencias.estado.sgdbAtivo === true
        }
        InterruptorDaPreferencia { chave: "sgdb-prefer"; titulo: "Priorizar o SteamGridDB às imagens oficiais" }
        InterruptorDaPreferencia { chave: "sgdb-animated"; titulo: "Preferir imagens animadas" }
    }

    GrupoDePreferencias {
        objectName: "grupoAtualizarCapas"

        LinhaDeAtualizacao {
            buscavel: true
            objectName: "linhaDasCapas"
            titulo: "Atualizar capas"
            subtitulo: "Busca capas para jogos já na biblioteca"
            enabled: preferencias.valores["sgdb"] === true
            emAndamento: preferencias.biblioteca.baixandoCapas
            onAcionada: preferencias.biblioteca.atualizarCapas()
        }
    }
}
