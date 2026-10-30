import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Window

// "Calibrar as cores", por cima das Preferências: a cor de referência de cada etapa em um quadro, o dispositivo aceso
// nela e os controles até os dois ficarem iguais. Só desenha: o que ele mostra e grava é o `assistente` (um
// `AssistenteDeCalibracao`, cartridges/calibracao_janela.py), que existe só enquanto a janela está aberta. As
// Preferências o ligam ao `preferencias.calibracao`; quem o usar em outro lugar passa o próprio `assistente`.
// Esc cancela; o foco volta a quem o abriu.
Rectangle {
    id: dialogo
    objectName: "assistenteDeCalibracao"

    property var assistente: preferencias.calibracao
    readonly property string pagina: assistente ? assistente.paginaAtual : ""
    // Quem tinha o foco ao abrir: volta a tê-lo ao fechar.
    property Item retorno: null

    Accessible.role: Accessible.Dialog
    Accessible.name: "Calibrar as cores"

    anchors.fill: parent
    z: 10
    visible: assistente !== null
    color: "#80000000"
    Keys.onEscapePressed: assistente.cancelar()
    // Modal para o teclado e o controle: nenhuma tecla chega às Preferências de trás (que ficam apagadas). O Tab passa,
    // para circular entre os botões e os controles.
    Keys.onPressed: event => event.accepted = event.key !== Qt.Key_Tab && event.key !== Qt.Key_Backtab

    function devolverAoRetorno() {
        if (!visible && retorno && retorno.visible && retorno.enabled) retorno.forceActiveFocus(Qt.TabFocusReason)
    }
    // O foco acompanha a página: o primeiro dispositivo da lista, o "Próximo" nas etapas e o "Pausar" no teste.
    function focarPagina() {
        if (!visible) return
        if (pagina === "inicio") {
            const primeira = listaDeDispositivos.itemAt(0)
            if (primeira) primeira.botaoDaLinha.forceActiveFocus(Qt.TabFocusReason)
        } else if (pagina === "etapa") botaoProxima.forceActiveFocus(Qt.TabFocusReason)
        else if (pagina === "etapa_todos") botaoProximaDeTodos.forceActiveFocus(Qt.TabFocusReason)
        else if (pagina === "teste") botaoPausar.forceActiveFocus(Qt.TabFocusReason)
    }
    onPaginaChanged: Qt.callLater(focarPagina)
    onVisibleChanged: {
        if (visible) {
            retorno = Window.window ? Window.window.activeFocusItem : null
            // Depois de o `visible` assentar, como no `DialogoDeConfirmacao`.
            Qt.callLater(focarPagina)
        } else {
            // Depois das Preferências de trás voltarem a ficar habilitadas.
            Qt.callLater(devolverAoRetorno)
        }
    }

    MouseArea { anchors.fill: parent } // o que está embaixo não recebe cliques

    component Botao: Button {
        id: botao
        property bool destaque: false
        focusPolicy: Qt.StrongFocus
        implicitHeight: 36
        leftPadding: 14
        rightPadding: 14
        Keys.onReturnPressed: click()
        Keys.onEnterPressed: click()
        contentItem: Text {
            text: botao.text
            textFormat: Text.PlainText
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            color: botao.destaque ? "white" : Tema.texto
            font { family: Tema.fonte; pixelSize: 14 }
        }
        background: Rectangle {
            radius: 6
            color: botao.destaque ? Tema.destaque : Tema.superficie
            opacity: botao.down ? 0.75 : botao.hovered ? 0.9 : 1
            border { width: botao.visualFocus ? 2 : 1; color: botao.visualFocus ? Tema.texto : Tema.borda }
        }
    }

    // Os botões da base de cada página, à direita.
    component FilaDeBotoes: Item {
        default property alias botoes: fila.data
        width: parent ? parent.width : implicitWidth
        height: 36
        Row {
            id: fila
            anchors.right: parent.right
            spacing: 10
        }
    }

    // A cor de referência: o quadro que a pessoa compara com o dispositivo.
    component Amostra: Rectangle {
        radius: 12
        color: dialogo.assistente ? dialogo.assistente.corNaTela : "transparent"
        border { width: 1; color: Tema.borda }
    }

    component Titulo: Text {
        textFormat: Text.PlainText
        elide: Text.ElideRight
        color: Tema.texto
        font { family: Tema.fonte; pixelSize: 20; weight: Font.DemiBold }
        Accessible.role: Accessible.Heading
        Accessible.name: text
    }

    // Um controle deslizante com o rótulo à esquerda. `neutro` é o ponto sem ajuste, marcado na barra: para onde o
    // "Restaurar" leva.
    component LinhaDeControle: Row {
        id: linhaDeControle
        property string rotulo
        property string nomeDoControle
        property int de
        property int ate
        property int neutro
        property int valor
        signal movido(int valor)

        width: parent ? parent.width : implicitWidth
        height: 32
        spacing: 12

        Text {
            width: 100
            height: parent.height
            text: linhaDeControle.rotulo
            textFormat: Text.PlainText
            verticalAlignment: Text.AlignVCenter
            color: Tema.texto
            font { family: Tema.fonte; pixelSize: 14 }
        }
        Slider {
            id: barra
            objectName: linhaDeControle.nomeDoControle
            width: parent.width - 112
            height: parent.height
            from: linhaDeControle.de
            to: linhaDeControle.ate
            stepSize: 1
            value: linhaDeControle.valor
            focusPolicy: Qt.StrongFocus
            Accessible.name: linhaDeControle.rotulo
            onMoved: linhaDeControle.movido(Math.round(value))
            background: Rectangle {
                x: barra.leftPadding
                y: barra.topPadding + barra.availableHeight / 2 - height / 2
                width: barra.availableWidth
                height: 4
                radius: 2
                color: Tema.borda
                Rectangle { width: barra.visualPosition * parent.width; height: parent.height; radius: 2; color: Tema.destaque }
                Rectangle {
                    x: (linhaDeControle.neutro - barra.from) / (barra.to - barra.from) * (parent.width - width)
                    y: -3
                    width: 2
                    height: 10
                    color: Tema.textoSecundario
                }
            }
            handle: Rectangle {
                x: barra.leftPadding + barra.visualPosition * (barra.availableWidth - width)
                y: barra.topPadding + barra.availableHeight / 2 - height / 2
                width: 18
                height: 18
                radius: 9
                color: Tema.destaque
                border { width: barra.visualFocus ? 3 : 1; color: barra.visualFocus ? Tema.texto : Tema.borda }
            }
        }
    }

    // Os controles de um dispositivo (`indice` em `assistente.controles`): Tom e Intensidade nas cores, Temperatura
    // no Branco.
    component Controles: Item {
        id: controles
        required property int indice
        readonly property var dado: dialogo.assistente && indice < dialogo.assistente.controles.length
            ? dialogo.assistente.controles[indice]
            : { id: "", nome: "", tom: 0, intensidade: 100, temperatura: 0, branco: false }

        width: parent ? parent.width : implicitWidth
        implicitHeight: coluna.implicitHeight + 8

        Column {
            id: coluna
            y: 4
            width: parent.width
            spacing: 6

            LinhaDeControle {
                visible: !controles.dado.branco
                rotulo: "Tom"
                nomeDoControle: "tomDaCalibracao-" + controles.dado.id
                de: dialogo.assistente ? -dialogo.assistente.tomMaximo : 0
                ate: dialogo.assistente ? dialogo.assistente.tomMaximo : 0
                neutro: 0
                valor: controles.dado.tom
                onMovido: v => dialogo.assistente.mudarTom(v, controles.dado.id)
            }
            LinhaDeControle {
                visible: !controles.dado.branco
                rotulo: "Intensidade"
                nomeDoControle: "intensidadeDaCalibracao-" + controles.dado.id
                de: dialogo.assistente ? dialogo.assistente.intensidadeMinima : 0
                ate: dialogo.assistente ? dialogo.assistente.intensidadeMaxima : 0
                neutro: 100
                valor: controles.dado.intensidade
                onMovido: v => dialogo.assistente.mudarIntensidade(v, controles.dado.id)
            }
            LinhaDeControle {
                visible: controles.dado.branco
                rotulo: "Temperatura"
                nomeDoControle: "temperaturaDaCalibracao-" + controles.dado.id
                de: -100
                ate: 100
                neutro: 0
                valor: controles.dado.temperatura
                onMovido: v => dialogo.assistente.mudarTemperatura(v, controles.dado.id)
            }
            // As pontas da Temperatura, em rótulos próprios, sob a barra.
            Item {
                visible: controles.dado.branco
                width: parent.width
                height: quente.implicitHeight
                Text {
                    id: quente
                    x: 112
                    text: "Mais quente"
                    textFormat: Text.PlainText
                    color: Tema.textoSecundario
                    font { family: Tema.fonte; pixelSize: 12 }
                }
                Text {
                    anchors.right: parent.right
                    text: "Mais frio"
                    textFormat: Text.PlainText
                    color: Tema.textoSecundario
                    font { family: Tema.fonte; pixelSize: 12 }
                }
            }
        }
    }

    Rectangle {
        anchors.centerIn: parent
        width: Math.min(520, parent.width - 48)
        height: Math.min(620, parent.height - 48)
        radius: 8
        color: Tema.fundo
        border.color: Tema.botaoSobre
        clip: true

        Item {
            id: cabecalho
            width: parent.width
            height: 56

            Botao {
                objectName: "botaoCancelarCalibracao"
                anchors { left: parent.left; leftMargin: 12; verticalCenter: parent.verticalCenter }
                text: "Cancelar"
                onClicked: dialogo.assistente.cancelar()
            }
            Text {
                anchors.centerIn: parent
                text: "Calibrar as cores"
                textFormat: Text.PlainText
                color: Tema.texto
                font { family: Tema.fonte; pixelSize: 15; weight: Font.DemiBold }
                Accessible.role: Accessible.Heading
                Accessible.name: text
            }
            Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Tema.borda }
        }

        Item {
            id: area
            anchors { left: parent.left; right: parent.right; top: cabecalho.bottom; bottom: parent.bottom; margins: 24; topMargin: 16 }

            // A escolha do dispositivo.
            Column {
                width: parent.width
                spacing: 18
                visible: dialogo.pagina === "inicio"

                Text {
                    width: parent.width
                    text: "Escolha o dispositivo a calibrar. Em cada etapa, ajuste os controles até a cor do dispositivo ficar igual à da tela. Para um resultado melhor, deixe o ambiente com pouca luz."
                    textFormat: Text.PlainText
                    wrapMode: Text.Wrap
                    color: Tema.textoSecundario
                    font { family: Tema.fonte; pixelSize: 14 }
                }
                GrupoDeLinhas {
                    width: parent.width
                    // Pela contagem, e não pela lista: as linhas (com o foco) ficam onde estão quando algo muda.
                    Repeater {
                        id: listaDeDispositivos
                        model: dialogo.assistente ? dialogo.assistente.linhas.length : 0
                        LinhaDeAcao {
                            id: linhaDoDispositivo
                            required property int index
                            readonly property var dispositivo: dialogo.assistente && index < dialogo.assistente.linhas.length
                                ? dialogo.assistente.linhas[index] : { id: "", nome: "", subtitulo: "" }
                            objectName: "dispositivoDaCalibracao-" + dispositivo.id
                            // O nome vem da conta da Tuya: a linha o mostra em PlainText.
                            titulo: dispositivo.nome
                            subtitulo: dispositivo.subtitulo
                            glifo: ""  // seguir
                            onAcionada: dialogo.assistente.escolherDispositivo(dispositivo.id)
                        }
                    }
                }
                FilaDeBotoes {
                    Botao {
                        objectName: "botaoTestarCalibracao"
                        text: "Testar calibração"
                        onClicked: dialogo.assistente.testar()
                    }
                }
            }

            // Uma cor de um dispositivo.
            Column {
                width: parent.width
                spacing: 16
                visible: dialogo.pagina === "etapa"

                Titulo { width: parent.width; text: dialogo.assistente ? dialogo.assistente.titulo : "" }
                Amostra {
                    objectName: "amostraDaCalibracao"
                    width: parent.width
                    height: 240
                }
                Repeater {
                    model: dialogo.pagina === "etapa" ? dialogo.assistente.controles.length : 0
                    Controles { required property int index; indice: index }
                }
                FilaDeBotoes {
                    Botao { objectName: "botaoRestaurarCalibracao"; text: "Restaurar"; onClicked: dialogo.assistente.restaurar() }
                    Botao { objectName: "botaoVoltarCalibracao"; text: "Voltar"; onClicked: dialogo.assistente.anterior() }
                    Botao {
                        id: botaoProxima
                        objectName: "botaoProximaCalibracao"
                        text: "Próximo"
                        destaque: true
                        onClicked: dialogo.assistente.proxima()
                    }
                }
            }

            // Uma cor de todos os dispositivos: a amostra menor e, embaixo, os controles de cada um, numa área que rola.
            Item {
                anchors.fill: parent
                visible: dialogo.pagina === "etapa_todos"

                Titulo {
                    id: tituloDeTodos
                    width: parent.width
                    text: dialogo.assistente ? dialogo.assistente.titulo : ""
                }
                Amostra {
                    id: amostraDeTodos
                    objectName: "amostraDeTodosDaCalibracao"
                    anchors { top: tituloDeTodos.bottom; topMargin: 16 }
                    width: parent.width
                    height: 72
                }
                Flickable {
                    id: rolagem
                    anchors { left: parent.left; right: parent.right; top: amostraDeTodos.bottom; topMargin: 16; bottom: botoesDeTodos.top; bottomMargin: 16 }
                    contentWidth: width
                    contentHeight: grupos.implicitHeight
                    boundsBehavior: Flickable.StopAtBounds
                    clip: true
                    ScrollBar.vertical: BarraDeRolagem {}

                    Column {
                        id: grupos
                        width: rolagem.width - 12
                        spacing: 18

                        Repeater {
                            model: dialogo.pagina === "etapa_todos" ? dialogo.assistente.controles.length : 0
                            GrupoDePreferencias {
                                id: grupoDoDispositivo
                                required property int index
                                // O nome vem da conta da Tuya: o grupo o mostra em PlainText.
                                titulo: dialogo.assistente && index < dialogo.assistente.controles.length
                                    ? dialogo.assistente.controles[index].nome : ""
                                Controles { indice: grupoDoDispositivo.index }
                            }
                        }
                    }
                }
                FilaDeBotoes {
                    id: botoesDeTodos
                    anchors.bottom: parent.bottom
                    Botao { objectName: "botaoRestaurarTodosCalibracao"; text: "Restaurar"; onClicked: dialogo.assistente.restaurar() }
                    Botao { objectName: "botaoVoltarTodosCalibracao"; text: "Voltar"; onClicked: dialogo.assistente.anterior() }
                    Botao {
                        id: botaoProximaDeTodos
                        objectName: "botaoProximaTodosCalibracao"
                        text: "Próximo"
                        destaque: true
                        onClicked: dialogo.assistente.proxima()
                    }
                }
            }

            // O teste final: as cores passam sozinhas.
            Column {
                width: parent.width
                spacing: 16
                visible: dialogo.pagina === "teste"

                Titulo { width: parent.width; text: dialogo.assistente ? dialogo.assistente.titulo : "" }
                Amostra {
                    objectName: "amostraDoTesteDaCalibracao"
                    width: parent.width
                    height: 240
                }
                FilaDeBotoes {
                    Botao { objectName: "botaoVoltarAosAjustes"; text: "Voltar aos ajustes"; onClicked: dialogo.assistente.voltarAosAjustes() }
                    Botao {
                        id: botaoPausar
                        objectName: "botaoPausarCalibracao"
                        text: dialogo.assistente && dialogo.assistente.pausado ? "Continuar" : "Pausar"
                        onClicked: dialogo.assistente.pausar()
                    }
                    Botao { objectName: "botaoAvancarTeste"; text: "Avançar"; onClicked: dialogo.assistente.avancarTeste() }
                    Botao { objectName: "botaoConcluirCalibracao"; text: "Concluir"; destaque: true; onClicked: dialogo.assistente.concluir() }
                }
            }
        }
    }
}
