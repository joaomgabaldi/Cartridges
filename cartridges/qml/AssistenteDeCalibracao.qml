import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// "Calibrar as cores", por cima das Preferências (`Adw.Dialog` de 520 por 620 com a `HeaderBar` e uma página por passo): a
// cor de referência de cada etapa em um quadro, o dispositivo aceso nela e os controles até os dois ficarem iguais. Só
// desenha: o que ele mostra e grava é o `assistente` (um `AssistenteDeCalibracao`, cartridges/calibracao_janela.py), que
// existe só enquanto a janela está aberta. As Preferências o ligam ao `preferencias.calibracao`; quem o usar em outro
// lugar passa o próprio `assistente`. Esc cancela; o foco volta a quem o abriu.
MolduraDoDialogo {
    id: dialogo
    objectName: "assistenteDeCalibracao"

    property var assistente: preferencias.calibracao
    readonly property string pagina: assistente ? assistente.paginaAtual : ""

    aberto: !!assistente
    largura: 520
    altura: 620
    nomeAcessivel: "Calibrar as cores"
    onFecharPedido: if (assistente) assistente.cancelar()

    // O foco acompanha a página: o primeiro dispositivo da lista, o "Próximo" nas etapas e o "Pausar" no teste. (Fica a
    // cargo do GTK na `main`; aqui o Qt perderia o foco ao esconder a página e o Esc deixaria de chegar ao diálogo.)
    function focarPagina() {
        if (!aberto) return
        if (pagina === "inicio") {
            const primeira = cargaDaLista.item ? cargaDaLista.item.lista.itemAt(0) : null
            if (primeira) primeira.botaoDaLinha.forceActiveFocus(Qt.TabFocusReason)
        } else if (pagina === "etapa") botaoProxima.forceActiveFocus(Qt.TabFocusReason)
        else if (pagina === "etapa_todos") botaoProximaDeTodos.forceActiveFocus(Qt.TabFocusReason)
        else if (pagina === "teste") botaoPausar.forceActiveFocus(Qt.TabFocusReason)
    }
    onPaginaChanged: Qt.callLater(focarPagina)
    // Depois do foco inicial da moldura, que também é adiado.
    onAbertoChanged: if (aberto) Qt.callLater(() => Qt.callLater(focarPagina))

    // A página de cada passo: 12 em cima, 24 embaixo e dos lados, 18 entre os blocos.
    component Pagina: ColumnLayout {
        anchors { fill: parent; topMargin: 12; bottomMargin: 24; leftMargin: 24; rightMargin: 24 }
        spacing: 18
    }

    // Os botões da base de cada página, à direita, com 12 entre eles.
    component FilaDeBotoes: RowLayout {
        Layout.alignment: Qt.AlignRight
        spacing: 12
    }

    // A cor de referência: o quadro que a pessoa compara com o dispositivo (`DrawingArea` sem borda, raio 12).
    component Amostra: Rectangle {
        Layout.fillWidth: true
        radius: 12
        color: dialogo.assistente ? dialogo.assistente.corNaTela : "transparent"
    }

    component Titulo: Text {
        Layout.fillWidth: true
        textFormat: Text.PlainText
        elide: Text.ElideRight
        color: Tema.texto
        font { family: Tema.fonte; pixelSize: Tema.titulo2; weight: Tema.pesoTitulo2 }
        Accessible.role: Accessible.Heading
        Accessible.name: text
    }

    // A coluna dos rótulos tem a largura do maior (a grade do GTK usa a natural).
    TextMetrics {
        id: medidaDaIntensidade
        font { family: Tema.fonte; pixelSize: Tema.corpo }
        text: "Intensidade"
    }
    TextMetrics {
        id: medidaDaTemperatura
        font { family: Tema.fonte; pixelSize: Tema.corpo }
        text: "Temperatura"
    }
    readonly property real larguraDosRotulos: Math.ceil(Math.max(medidaDaIntensidade.width, medidaDaTemperatura.width))

    // Um controle deslizante com o rótulo à esquerda (`Gtk.Scale` do Adwaita: trilha de 10, botão branco de 20 e 12 de
    // respiro). `neutro` é o ponto sem ajuste, marcado embaixo da barra: para onde o "Restaurar" leva.
    component LinhaDeControle: Item {
        id: linhaDeControle
        property string rotulo
        property string nomeDoControle
        property int de
        property int ate
        property int neutro
        property int valor
        signal movido(int valor)

        width: parent ? parent.width : implicitWidth
        height: 34
        Text {
            width: dialogo.larguraDosRotulos
            y: 0
            height: 22
            text: linhaDeControle.rotulo
            textFormat: Text.PlainText
            verticalAlignment: Text.AlignVCenter
            color: Tema.texto
            font { family: Tema.fonte; pixelSize: Tema.corpo }
        }
        Slider {
            id: barra
            objectName: linhaDeControle.nomeDoControle
            x: dialogo.larguraDosRotulos + 12
            width: parent.width - x
            height: parent.height
            from: linhaDeControle.de
            to: linhaDeControle.ate
            stepSize: 1
            value: linhaDeControle.valor
            focusPolicy: Qt.StrongFocus
            hoverEnabled: true
            // `scale`: 12 de respiro em volta; o botão fica a 2 px das pontas da trilha.
            leftPadding: 12 + 2
            rightPadding: 12 + 2
            topPadding: 0
            bottomPadding: 0
            Accessible.name: linhaDeControle.rotulo
            onMoved: linhaDeControle.movido(Math.round(value))
            background: Item {
                readonly property real inicio: barra.leftPadding - 2
                readonly property real larguraDaTrilha: barra.width - 2 * 12
                Rectangle {
                    x: parent.inicio
                    y: 11
                    width: parent.larguraDaTrilha
                    height: 10
                    radius: 5
                    color: Tema.mistura(barra.hovered || barra.pressed ? 0.20 : 0.15)
                    Rectangle {
                        width: barra.visualPosition * (parent.width - 4) + 2
                        height: parent.height
                        radius: height / 2
                        color: Tema.destaque
                        Rectangle {
                            anchors.fill: parent
                            radius: parent.radius
                            color: Tema.mistura(0.10)
                            visible: barra.hovered || barra.pressed
                        }
                    }
                }
                // A marca do ponto sem ajuste: 1 x 6, a 6 da trilha, apagada.
                Rectangle {
                    x: parent.inicio + 2 + (linhaDeControle.neutro - barra.from) / (barra.to - barra.from) * (parent.larguraDaTrilha - 4)
                    y: 11 + 10 + 6
                    width: 1
                    height: 6
                    color: Qt.alpha(Tema.texto, Tema.opacidadeApagado)
                }
            }
            handle: Rectangle {
                x: barra.leftPadding + barra.visualPosition * (barra.availableWidth) - width / 2
                y: 16 - height / 2
                width: 20
                height: 20
                radius: 10
                color: barra.hovered || barra.pressed ? "white"
                    : Qt.rgba(0.8 + 0.2 * Tema.vista.r, 0.8 + 0.2 * Tema.vista.g, 0.8 + 0.2 * Tema.vista.b, 1)
                Sombra { camadas: [[0, 0, 1, 0, 0, 6 / 255, 0.10], [2, 4, 0, 0, 0, 6 / 255, 0.2]]; raio: 10 }
                AnelDeFoco { ativo: barra.visualFocus; raio: 10; afastamento: 0 }
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
        implicitWidth: parent ? parent.width : 0
        implicitHeight: coluna.implicitHeight
        Layout.fillWidth: true
        Layout.preferredHeight: implicitHeight

        Column {
            id: coluna
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
                    x: dialogo.larguraDosRotulos + 12
                    text: "Mais quente"
                    textFormat: Text.PlainText
                    color: Tema.textoSecundario
                    font { family: Tema.fonte; pixelSize: Tema.corpo }
                }
                Text {
                    anchors.right: parent.right
                    text: "Mais frio"
                    textFormat: Text.PlainText
                    color: Tema.textoSecundario
                    font { family: Tema.fonte; pixelSize: Tema.corpo }
                }
            }
        }
    }

    CabecalhoDoDialogo {
        titulo: "Calibrar as cores"
        comFechar: false
        inicio: [
            Botao {
                objectName: "botaoCancelarCalibracao"
                estilo: "plano"
                text: "Cancelar"
                onClicked: dialogo.assistente.cancelar()
            }
        ]
    }

    Item {
        Layout.fillWidth: true
        Layout.fillHeight: true

        // A escolha do dispositivo.
        Pagina {
            visible: dialogo.pagina === "inicio"

            Text {
                Layout.fillWidth: true
                text: "Escolha o dispositivo a calibrar. Em cada etapa, ajuste os controles até a cor do dispositivo ficar igual à da tela. Para um resultado melhor, deixe o ambiente com pouca luz."
                textFormat: Text.PlainText
                wrapMode: Text.Wrap
                color: Tema.texto
                font { family: Tema.fonte; pixelSize: Tema.corpo }
            }
            // Criada com o diálogo já à vista: o cartão some enquanto a altura é zero, e um `Column` não conta as linhas que
            // nascem sob um pai escondido (a altura nunca sairia de zero).
            Loader {
                id: cargaDaLista
                Layout.fillWidth: true
                Layout.preferredHeight: item ? item.implicitHeight : 0
                active: dialogo.visible
                sourceComponent: GrupoDeLinhas {
                    property alias lista: listaDeDispositivos
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
                            icone: "go-next"
                            onAcionada: dialogo.assistente.escolherDispositivo(dispositivo.id)
                        }
                    }
                }
            }
            // Os botões da base ficam no pé (`Gtk.Box` do fim, sem `vexpand`: o vão sobra embaixo do último bloco).
            FilaDeBotoes {
                Botao {
                    objectName: "botaoTestarCalibracao"
                    text: "Testar calibração"
                    onClicked: dialogo.assistente.testar()
                }
            }
            Item { Layout.fillHeight: true }
        }

        // Uma cor de um dispositivo.
        Pagina {
            visible: dialogo.pagina === "etapa"

            Titulo { text: dialogo.assistente ? dialogo.assistente.titulo : "" }
            // A amostra ocupa o que sobra (`vexpand`), com 240 no mínimo.
            Amostra {
                objectName: "amostraDaCalibracao"
                Layout.fillHeight: true
                Layout.minimumHeight: 240
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
                    estilo: "sugestao"
                    onClicked: dialogo.assistente.proxima()
                }
            }
        }

        // Uma cor de todos os dispositivos: a amostra menor e, embaixo, os controles de cada um, numa área que rola.
        Pagina {
            visible: dialogo.pagina === "etapa_todos"

            Titulo { text: dialogo.assistente ? dialogo.assistente.titulo : "" }
            Amostra {
                objectName: "amostraDeTodosDaCalibracao"
                Layout.preferredHeight: 72
            }
            Flickable {
                id: rolagem
                Layout.fillWidth: true
                Layout.fillHeight: true
                contentWidth: width
                contentHeight: grupos.implicitHeight
                boundsBehavior: Flickable.StopAtBounds
                RolagemDaRoda { alvo: rolagem }
                clip: true
                ScrollBar.vertical: BarraDeRolagem {}

                Column {
                    id: grupos
                    width: rolagem.width
                    spacing: 18

                    // Um grupo por dispositivo: só o título e os controles, sem cartão (`PreferencesGroup.add` de um
                    // widget que não é linha).
                    Repeater {
                        model: dialogo.pagina === "etapa_todos" ? dialogo.assistente.controles.length : 0
                        Column {
                            id: grupoDoDispositivo
                            required property int index
                            width: grupos.width - 12
                            spacing: 6
                            // O nome vem da conta da Tuya: o grupo o mostra em PlainText.
                            Text {
                                width: parent.width
                                height: 34
                                verticalAlignment: Text.AlignVCenter
                                text: dialogo.assistente && grupoDoDispositivo.index < dialogo.assistente.controles.length
                                    ? dialogo.assistente.controles[grupoDoDispositivo.index].nome : ""
                                textFormat: Text.PlainText
                                wrapMode: Text.Wrap
                                color: Tema.texto
                                font { family: Tema.fonte; pixelSize: Tema.corpo; weight: Tema.pesoForte }
                                Accessible.role: Accessible.Heading
                                Accessible.name: text
                            }
                            Controles { width: parent.width; indice: grupoDoDispositivo.index }
                        }
                    }
                }
            }
            FilaDeBotoes {
                Botao { objectName: "botaoRestaurarTodosCalibracao"; text: "Restaurar"; onClicked: dialogo.assistente.restaurar() }
                Botao { objectName: "botaoVoltarTodosCalibracao"; text: "Voltar"; onClicked: dialogo.assistente.anterior() }
                Botao {
                    id: botaoProximaDeTodos
                    objectName: "botaoProximaTodosCalibracao"
                    text: "Próximo"
                    estilo: "sugestao"
                    onClicked: dialogo.assistente.proxima()
                }
            }
        }

        // O teste final: as cores passam sozinhas.
        Pagina {
            visible: dialogo.pagina === "teste"

            Titulo { text: dialogo.assistente ? dialogo.assistente.titulo : "" }
            Amostra {
                objectName: "amostraDoTesteDaCalibracao"
                Layout.fillHeight: true
                Layout.minimumHeight: 240
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
                Botao { objectName: "botaoConcluirCalibracao"; text: "Concluir"; estilo: "sugestao"; onClicked: dialogo.assistente.concluir() }
            }
        }
    }
}
