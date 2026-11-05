import QtQuick

Column {
    id: pagina
    objectName: "paginaDoAplicativo"

    readonly property QtObject servicoDeAtualizacao: typeof atualizador === "undefined" ? null : atualizador

    width: parent ? parent.width : implicitWidth
    spacing: 24

    GrupoDePreferencias {
        objectName: "grupoAtualizacoes"
        titulo: "Atualizações"

        LinhaDeBotoes {
            buscavel: true
            objectName: "linhaBuscarAtualizacoes"
            titulo: "Buscar atualizações"
            subtitulo: "Versão atual: " + (pagina.servicoDeAtualizacao ? pagina.servicoDeAtualizacao.versao : "")

            Botao {
                objectName: "linhaBuscarAtualizacoesBotao"
                text: "Buscar"
                enabled: !pagina.servicoDeAtualizacao || !pagina.servicoDeAtualizacao.buscando
                onClicked: {
                    if (pagina.servicoDeAtualizacao) pagina.servicoDeAtualizacao.buscarAgora()
                    else aplicativo.avisar("Não foi possível buscar atualizações")
                }
            }
        }
    }

    GrupoDePreferencias {
        objectName: "grupoZonaDePerigo"
        titulo: "Zona de perigo"
        separada: true

        LinhaDeBotao {
            buscavel: true
            objectName: "linhaRedefinir"
            titulo: "Redefinir Kyron"
            destrutivo: true
            onAcionada: preferencias.backup.redefinir()
        }
    }
}
