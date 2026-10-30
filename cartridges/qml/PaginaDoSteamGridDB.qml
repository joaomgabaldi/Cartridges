import QtQuick

// A página SteamGridDB das Preferências. Só desenha: as chaves são do `preferencias` (cartridges/modelos/preferencias.py).
Column {
    id: pagina
    objectName: "paginaDoSteamGridDB"

    width: parent ? parent.width : implicitWidth
    spacing: 24

    component Interruptor: LinhaDeAlternancia {
        property string chave
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
            // Sem chave da API não há o que usar.
            enabled: preferencias.estado.sgdbAtivo === true
        }
        Interruptor { chave: "sgdb-prefer"; titulo: "Priorizar o SteamGridDB às imagens oficiais" }
        Interruptor { chave: "sgdb-animated"; titulo: "Preferir imagens animadas" }
    }

    // shortcut: falta o grupo "Atualizar capas" (a linha com o botão "Atualizar" e o indicador), da Task 3 do plano 7; entra aqui, depois de "Comportamento".
}
