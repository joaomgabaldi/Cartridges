import QtQuick

// Os dados do jogo selecionado, na coluna à direita do Big Picture. Só leitura. Os textos entram e saem só com fade.
// Em cima o que ajuda a escolher (gênero, descrição, Iniciar); no pé da capa, os números e o resto, menor.
Item {
    id: coluna
    objectName: "detalhesDoBigPicture"

    property bool mostrar: false
    property bool animar: true
    property real alturaDaTela: 1080

    readonly property real unidade: Math.max(0.85, alturaDaTela / 1080)  // lido do sofá: o texto acompanha a tela
    readonly property var conquistas: conquistasDoJogo.pagina

    opacity: 0
    visible: opacity > 0

    function unir(partesDoTexto) {
        return partesDoTexto.filter((p, i, todas) => p !== "" && todas.indexOf(p) === i).join("  ·  ")
    }
    // "Tempo de jogo: 12 h" vira ["Tempo de jogo", "12 h"]: o rótulo pequeno e o valor em destaque.
    function partes(texto) {
        const corte = texto.indexOf(": ")
        return corte < 0 ? ["", texto] : [texto.slice(0, corte), texto.slice(corte + 2)]
    }
    // Os tempos do HowLongToBeat, sem link: "Principal 10 h  ·  ..."
    function tempos(hltb) {
        return unir((hltb.celulas || []).map(c => c.valor === "" ? "" : c.rotulo + " " + c.valor))
    }

    onMostrarChanged: {
        aparecer.stop()
        sumir.stop()
        if (!animar) opacity = mostrar ? 1 : 0
        else if (mostrar) aparecer.start()
        else sumir.start()
    }
    SequentialAnimation {
        id: aparecer
        PauseAnimation { duration: 450 }
        NumberAnimation { target: coluna; property: "opacity"; to: 1; duration: 450 }
    }
    NumberAnimation { id: sumir; target: coluna; property: "opacity"; to: 0; duration: 300 }

    component Linha: Text {
        property real tamanho: 16
        width: coluna.width
        visible: text !== ""
        textFormat: Text.PlainText
        wrapMode: Text.Wrap
        color: "white"
        opacity: 0.6
        font { family: Tema.fonte; pixelSize: Math.round(tamanho * coluna.unidade) }
    }
    component Destaque: Column {
        id: destaque
        property string rotulo
        property string valor
        visible: valor !== ""
        spacing: 2 * coluna.unidade
        Text {
            text: destaque.valor
            textFormat: Text.PlainText
            color: "white"
            font { family: Tema.fonte; pixelSize: Math.round(20 * coluna.unidade); features: { "tnum": 1 } }
        }
        Text {
            text: destaque.rotulo
            textFormat: Text.PlainText
            color: "white"
            opacity: 0.6
            font { family: Tema.fonte; pixelSize: Math.round(13 * coluna.unidade) }
        }
    }

    Column {
        id: dados
        objectName: "dadosDoJogoNoBigPicture"
        width: parent.width
        spacing: 14 * coluna.unidade

        Linha {
            objectName: "linhaDeGenero"
            tamanho: 18
            opacity: 0.8
            text: coluna.unir([detalhes.genero, coluna.partes(detalhes.dataDeLancamento)[1]])
        }
        Linha {
            objectName: "descricaoDoJogo"
            tamanho: 20
            opacity: 0.9
            lineHeight: 1.15
            text: detalhes.descricao
            maximumLineCount: 5
            elide: Text.ElideRight
        }
    }

    BotaoDoBigPicture {
        id: iniciar
        objectName: "botaoIniciar"
        y: dados.height + 24
        unidade: coluna.unidade
        texto: "Iniciar"
        ativo: coluna.mostrar && !bigPicture.ocupada
        onAcionado: bigPicture.ativar()
    }

    Column {
        // No pé da capa; numa tela pequena, logo abaixo do botão.
        y: Math.max(iniciar.y + iniciar.height + 20, coluna.height - height)
        width: parent.width
        spacing: 12 * coluna.unidade

        Flow {
            objectName: "destaquesDoJogo"
            width: parent.width
            spacing: 32 * coluna.unidade
            bottomPadding: 8 * coluna.unidade
            Destaque {
                rotulo: coluna.partes(detalhes.tempoDeJogo)[0]
                valor: coluna.partes(detalhes.tempoDeJogo)[1]
            }
            Destaque {
                rotulo: coluna.partes(detalhes.jogadoPorUltimo)[0]
                valor: coluna.partes(detalhes.jogadoPorUltimo)[1]
            }
            Destaque {
                objectName: "resumoDeConquistas"
                rotulo: "Conquistas"
                valor: coluna.conquistas.visivel === true ? coluna.conquistas.contagem : ""
            }
            Destaque {
                rotulo: "Status"
                valor: detalhes.status
            }
        }
        Linha {
            objectName: "linhaDeAutoria"
            text: coluna.unir([detalhes.desenvolvedora, detalhes.publicadora])
        }
        Linha {
            objectName: "linhaDeAvaliacoes"
            text: coluna.unir([detalhes.nota, detalhes.metacritic, detalhes.avaliacoes, detalhes.controle])
        }
        Linha {
            objectName: "controleRecomendado"
            text: detalhes.controleRecomendado ? "★ Os desenvolvedores recomendam o uso de um controle." : ""
        }
        Linha {
            objectName: "linhaDoHltb"
            text: coluna.tempos(detalhes.hltb)
        }
    }
}
