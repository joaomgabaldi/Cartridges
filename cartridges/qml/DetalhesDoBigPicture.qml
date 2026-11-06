import QtQuick

// Os dados do jogo selecionado, na coluna à direita do Big Picture. Só leitura. Os textos entram e saem só com fade.
Item {
    id: coluna
    objectName: "detalhesDoBigPicture"

    property bool mostrar: false
    property bool animar: true

    readonly property real larguraDoTexto: width
    readonly property var conquistas: conquistasDoJogo.pagina

    opacity: 0
    visible: opacity > 0

    function unir(partes) { return partes.filter(p => p !== "").join("  ·  ") }
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
        width: coluna.larguraDoTexto
        visible: text !== ""
        textFormat: Text.PlainText
        wrapMode: Text.Wrap
        color: "white"
        opacity: 0.8
        font { family: Tema.fonte; pixelSize: Tema.corpo }
    }

    Column {
        id: dados
        width: parent.width
        spacing: 10

        Linha {
            objectName: "linhaDeAutoria"
            text: coluna.unir([detalhes.desenvolvedora, detalhes.publicadora, detalhes.dataDeLancamento, detalhes.genero])
            opacity: 1
        }
        Linha {
            objectName: "linhaDeDestaques"
            text: coluna.unir([detalhes.tempoDeJogo, detalhes.jogadoPorUltimo, detalhes.status])
        }
        Column {
            objectName: "resumoDeConquistas"
            visible: coluna.conquistas.visivel === true
            width: Math.min(coluna.width, 320)
            spacing: 6
            Linha {
                width: parent.width
                text: coluna.unir([coluna.conquistas.contagem || "", coluna.conquistas.porcentagem || ""])
                opacity: 1
            }
            Rectangle {
                width: parent.width
                height: 6
                radius: 3
                color: Qt.rgba(1, 1, 1, 0.2)
                Rectangle {
                    width: parent.width * Math.max(0, Math.min(1, coluna.conquistas.fracao || 0))
                    height: parent.height
                    radius: 3
                    color: "white"
                }
            }
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
        Linha {
            objectName: "descricaoDoJogo"
            text: detalhes.descricao
            maximumLineCount: 6
            elide: Text.ElideRight
        }
    }

    Rectangle {
        id: pilula
        objectName: "botaoIniciar"
        anchors { left: parent.left; bottom: parent.bottom }
        width: rotulo.x + rotulo.width + 28
        height: 44
        radius: height / 2
        color: "white"
        Accessible.role: Accessible.Button
        Accessible.name: "Iniciar"

        GlifoDoBotao {
            id: glifo
            letra: "A"
            x: 14
            anchors.verticalCenter: parent.verticalCenter
        }
        Text {
            id: rotulo
            x: glifo.x + glifo.width + 10
            anchors.verticalCenter: parent.verticalCenter
            text: "Iniciar"
            textFormat: Text.PlainText
            color: "black"
            font { family: Tema.fonte; pixelSize: Tema.corpo; weight: Tema.pesoForte }
        }
        TapHandler {
            enabled: coluna.mostrar && !bigPicture.ocupada
            onTapped: bigPicture.ativar()
        }
    }
}
