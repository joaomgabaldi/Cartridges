import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Window

// "Configurar a iluminação inteligente": o assistente que busca os dispositivos na conta da Tuya. Só desenha: o que ele
// mostra e grava é o `assistente` (um `FitaWizard`, cartridges/fita_wizard.py). Modal por cima de quem o hospeda: as
// Preferências o ligam ao `preferencias.configuracaoDasFitas`; quem o usar em outro lugar passa o próprio `assistente`.
// Esc fecha; o foco volta a quem o abriu.
Rectangle {
    id: dialogo
    objectName: "dialogoDaConfiguracaoDasFitas"

    property var assistente: preferencias.configuracaoDasFitas
    readonly property string pagina: assistente ? assistente.pagina : ""
    // Quem tinha o foco ao abrir: volta a tê-lo ao fechar.
    property Item retorno: null
    property string paginaAnterior: ""

    Accessible.role: Accessible.Dialog
    Accessible.name: "Configurar a iluminação inteligente"

    anchors.fill: parent
    z: 10
    visible: !!assistente
    color: "#80000000"
    Keys.onEscapePressed: assistente.fechar()
    // Modal para o teclado e o controle: nenhuma tecla chega às Preferências de trás (que ficam apagadas). O Tab passa,
    // para circular entre os campos e os botões.
    Keys.onPressed: event => event.accepted = event.key !== Qt.Key_Tab && event.key !== Qt.Key_Backtab

    function devolverAoRetorno() {
        if (!visible && retorno && retorno.visible && retorno.enabled) retorno.forceActiveFocus(Qt.TabFocusReason)
    }
    // O foco acompanha a página: o primeiro campo ao abrir, o botão ao voltar de uma busca, o "Aplicar" na lista. Na
    // busca o foco fica no próprio diálogo, para o Esc seguir valendo.
    function focarPagina() {
        if (!visible) return
        if (pagina === "credenciais") (paginaAnterior === "" ? campoDoId : botaoBuscar).forceActiveFocus(Qt.TabFocusReason)
        else if (pagina === "dispositivos") botaoAplicar.forceActiveFocus(Qt.TabFocusReason)
        else if (pagina === "buscando") forceActiveFocus()
        paginaAnterior = pagina
    }
    onPaginaChanged: Qt.callLater(focarPagina)
    onVisibleChanged: {
        if (visible) {
            retorno = Window.window ? Window.window.activeFocusItem : null
            paginaAnterior = ""
            // Depois de o `visible` assentar, como no `DialogoDeConfirmacao`.
            Qt.callLater(focarPagina)
        } else {
            // Depois das Preferências de trás voltarem a ficar habilitadas.
            Qt.callLater(devolverAoRetorno)
        }
    }

    MouseArea { anchors.fill: parent } // o que está embaixo não recebe cliques

    component BotaoEmPilula: Button {
        id: botao
        focusPolicy: Qt.StrongFocus
        implicitHeight: 40
        leftPadding: 24
        rightPadding: 24
        Keys.onReturnPressed: click()
        Keys.onEnterPressed: click()
        contentItem: Text {
            text: botao.text
            textFormat: Text.PlainText
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            color: "white"
            font { family: Tema.fonte; pixelSize: 15; weight: Font.DemiBold }
        }
        background: Rectangle {
            radius: height / 2
            color: Tema.destaque
            opacity: botao.down ? 0.75 : botao.hovered ? 0.9 : 1
            border { width: botao.visualFocus ? 2 : 0; color: Tema.texto }
        }
    }

    Rectangle {
        anchors.centerIn: parent
        width: Math.min(480, parent.width - 48)
        height: Math.min(520, parent.height - 48)
        radius: 8
        color: Tema.fundo
        border.color: Tema.botaoSobre
        clip: true

        Item {
            id: cabecalho
            width: parent.width
            height: 56

            Text {
                anchors { left: parent.left; leftMargin: 16; right: botaoFechar.left; rightMargin: 8; verticalCenter: parent.verticalCenter }
                text: "Configurar a iluminação inteligente"
                textFormat: Text.PlainText
                elide: Text.ElideRight
                color: Tema.texto
                font { family: Tema.fonte; pixelSize: 15; weight: Font.DemiBold }
                Accessible.role: Accessible.Heading
                Accessible.name: text
            }
            Button {
                id: botaoFechar
                objectName: "botaoFecharConfiguracaoDasFitas"
                anchors { right: parent.right; rightMargin: 12; verticalCenter: parent.verticalCenter }
                focusPolicy: Qt.StrongFocus
                implicitWidth: 34
                implicitHeight: 34
                Accessible.name: "Fechar"
                ToolTip.visible: hovered
                ToolTip.text: "Fechar"
                ToolTip.delay: 600
                onClicked: dialogo.assistente.fechar()
                contentItem: Text {
                    text: ""  // fechar
                    textFormat: Text.PlainText
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    color: Tema.texto
                    font { family: Tema.fonteDeIcones; pixelSize: 14 }
                }
                background: Rectangle {
                    radius: 6
                    color: botaoFechar.down ? Tema.pressionado : botaoFechar.hovered ? Tema.botaoSobre : "transparent"
                    border { width: botaoFechar.visualFocus ? 2 : 0; color: Tema.destaque }
                }
            }
            Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: Tema.borda }
        }

        Flickable {
            id: rolagem
            anchors { left: parent.left; right: parent.right; top: cabecalho.bottom; bottom: parent.bottom }
            contentWidth: width
            contentHeight: paginas.implicitHeight + 32
            boundsBehavior: Flickable.StopAtBounds
            clip: true
            ScrollBar.vertical: BarraDeRolagem {}

            Column {
                id: paginas
                x: 16
                y: 16
                width: rolagem.width - 32
                spacing: 16

                // As credenciais da conta de desenvolvedor.
                Column {
                    width: parent.width
                    spacing: 16
                    visible: dialogo.pagina === "credenciais"

                    GrupoDePreferencias {
                        objectName: "grupoDaContaDaTuya"
                        titulo: "Conta de desenvolvedor da Tuya"
                        descricao: "O Access ID e o Access Secret são obtidos em uma conta de desenvolvedor da Tuya vinculada ao app Smart Life. Após uma busca bem-sucedida, as credenciais são salvas de forma criptografada e não serão solicitadas novamente."

                        sufixo: Button {
                            id: botaoDoPainel
                            objectName: "botaoAbrirPainelDaTuya"
                            focusPolicy: Qt.StrongFocus
                            padding: 4
                            Keys.onReturnPressed: click()
                            Keys.onEnterPressed: click()
                            onClicked: dialogo.assistente.abrirPainel()
                            contentItem: Text {
                                text: "Abrir o painel da Tuya"
                                textFormat: Text.PlainText
                                color: Tema.destaque
                                font { family: Tema.fonte; pixelSize: 13; underline: true }
                            }
                            background: Rectangle {
                                radius: 4
                                color: "transparent"
                                border { width: botaoDoPainel.visualFocus ? 2 : 0; color: Tema.destaque }
                            }
                        }

                        LinhaDeTexto {
                            id: campoDoId
                            objectName: "campoDoAccessId"
                            titulo: "Access ID (Client ID)"
                            text: dialogo.assistente ? dialogo.assistente.chave : ""
                            onEditado: dialogo.assistente.chave = text
                            onConfirmado: dialogo.assistente.buscar()
                        }
                        LinhaDeTexto {
                            objectName: "campoDoAccessSecret"
                            titulo: "Access Secret (Client Secret)"
                            echoMode: TextInput.Password
                            text: dialogo.assistente ? dialogo.assistente.segredo : ""
                            onEditado: dialogo.assistente.segredo = text
                            onConfirmado: dialogo.assistente.buscar()
                        }
                        LinhaDeEscolha {
                            objectName: "regiaoDasFitas"
                            titulo: "Região"
                            model: ["Américas (us)", "Europa (eu)", "China (cn)", "Índia (in)"]
                            currentIndex: dialogo.assistente ? dialogo.assistente.regiao : 0
                            onEscolhido: indice => dialogo.assistente.regiao = indice
                        }
                    }

                    // Uma busca sem resultado volta para cá, e não para a lista: lá o único botão é "Aplicar".
                    Text {
                        objectName: "avisoSemResultado"
                        width: parent.width
                        visible: dialogo.assistente ? dialogo.assistente.semResultado : false
                        text: "Nenhum dispositivo encontrado. Confira as credenciais e a região."
                        textFormat: Text.PlainText
                        wrapMode: Text.Wrap
                        horizontalAlignment: Text.AlignHCenter
                        color: Tema.erro
                        font { family: Tema.fonte; pixelSize: 14 }
                    }
                    BotaoEmPilula {
                        id: botaoBuscar
                        objectName: "botaoBuscarDasFitas"
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: "Buscar dispositivos"
                        onClicked: dialogo.assistente.buscar()
                    }
                }

                // A busca na nuvem.
                Column {
                    width: parent.width
                    spacing: 16
                    topPadding: 96
                    visible: dialogo.pagina === "buscando"

                    BusyIndicator {
                        objectName: "buscandoDispositivos"
                        anchors.horizontalCenter: parent.horizontalCenter
                        running: parent.visible
                        implicitWidth: 32
                        implicitHeight: 32
                        Accessible.name: "Buscando"
                    }
                    Text {
                        width: parent.width
                        text: "Buscando os dispositivos…"
                        textFormat: Text.PlainText
                        horizontalAlignment: Text.AlignHCenter
                        color: Tema.texto
                        font { family: Tema.fonte; pixelSize: 18; weight: Font.DemiBold }
                    }
                }

                // Os dispositivos achados: marcar é manter; desmarcar remove.
                Column {
                    width: parent.width
                    spacing: 16
                    visible: dialogo.pagina === "dispositivos"

                    GrupoDePreferencias {
                        objectName: "grupoDosDispositivos"
                        titulo: "Selecione os dispositivos"
                        descricao: "Ao aplicar, somente os dispositivos marcados são mantidos. Desmarcar um dispositivo o remove."

                        // Pela contagem, e não pela lista: marcar um dispositivo refaz a lista, e as linhas (com o
                        // foco) têm de ficar onde estão.
                        Repeater {
                            model: dialogo.assistente ? dialogo.assistente.dispositivos.length : 0
                            LinhaDeAlternancia {
                                id: linhaDoDispositivo
                                required property int index
                                // Ao refazer a lista a contagem pode andar um instante atrás: sem a linha, o vazio.
                                readonly property var dispositivo: dialogo.assistente && index < dialogo.assistente.dispositivos.length
                                    ? dialogo.assistente.dispositivos[index] : { id: "", nome: "", subtitulo: "", ativo: false, marcado: false }
                                objectName: "dispositivoDasFitas-" + dispositivo.id
                                // O nome vem da conta da Tuya: a linha o mostra em PlainText.
                                titulo: dispositivo.nome
                                subtitulo: dispositivo.subtitulo
                                enabled: dispositivo.ativo
                                checked: dispositivo.marcado
                                onAlternado: dialogo.assistente.marcar(dispositivo.id, checked)
                            }
                        }
                    }
                    BotaoEmPilula {
                        id: botaoAplicar
                        objectName: "botaoAplicarDasFitas"
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: "Aplicar"
                        onClicked: dialogo.assistente.salvar()
                    }
                }
            }
        }
    }
}
