import QtQuick

Column {
    id: pagina
    objectName: "paginaDoSteamGridDB"

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
        objectName: "grupoAutenticacao"
        titulo: "Autenticação"
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
    }

    GrupoDePreferencias {
        objectName: "grupoComportamentoDoSgdb"
        titulo: "Comportamento"

        Interruptor {
            chave: "sgdb"
            titulo: "Usar o SteamGridDB"
            subtitulo: "Baixa imagens ao adicionar ou importar jogos"
            enabled: preferencias.estado.sgdbAtivo === true
        }
        Interruptor { chave: "sgdb-prefer"; titulo: "Priorizar o SteamGridDB às imagens oficiais" }
        Interruptor { chave: "sgdb-animated"; titulo: "Preferir imagens animadas" }
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
