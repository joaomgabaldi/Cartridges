import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// "Configurar a iluminação inteligente": busca os dispositivos na conta da Tuya; só desenha, o estado é do `assistente`
// (kyron/fita_wizard.py).
MolduraDoDialogo {
    id: dialogo
    objectName: "dialogoDaConfiguracaoDasFitas"

    property var assistente: preferencias.configuracaoDasFitas
    readonly property string pagina: assistente ? assistente.pagina : ""
    property string paginaAnterior: ""
    property bool segredoVisivel: false

    aberto: !!assistente
    largura: 480
    altura: 520
    focoInicial: campoDoId
    nomeAcessivel: "Configurar a iluminação inteligente"
    onFecharPedido: if (assistente) assistente.fechar()

    // Na busca o foco fica no próprio diálogo, para o Esc seguir valendo.
    function focarPagina() {
        if (!aberto) return
        if (pagina === "credenciais") (paginaAnterior === "" ? campoDoId : botaoBuscar).forceActiveFocus(Qt.TabFocusReason)
        else if (pagina === "dispositivos") botaoAplicar.forceActiveFocus(Qt.TabFocusReason)
        else if (pagina === "buscando") forceActiveFocus()
        paginaAnterior = pagina
    }
    onPaginaChanged: Qt.callLater(focarPagina)
    onAbertoChanged: if (aberto) { paginaAnterior = ""; segredoVisivel = false }

    CabecalhoDoDialogo {
        titulo: "Configurar a iluminação inteligente"
        sombra: rolagem.contentY > 0
        onFechar: dialogo.assistente.fechar()
    }

    Flickable {
        id: rolagem
        Layout.fillWidth: true
        Layout.fillHeight: true
        visible: dialogo.pagina !== "buscando"
        contentWidth: width
        contentHeight: paginas.implicitHeight + 48
        boundsBehavior: Flickable.StopAtBounds
        RolagemDaRoda { alvo: rolagem }
        clip: true
        ScrollBar.vertical: BarraDeRolagem {}

        Column {
            id: paginas
            x: 12
            y: 24
            width: rolagem.width - 24
            spacing: 24

            Column {
                width: parent.width
                spacing: 24
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
                            color: Tema.destaqueTexto
                            font { family: Tema.fonte; pixelSize: Tema.corpo; underline: true }
                        }
                        background: Rectangle {
                            radius: 4
                            color: "transparent"
                            AnelDeFoco { ativo: botaoDoPainel.visualFocus; raio: 4; afastamento: 0 }
                        }
                    }

                    LinhaDeTexto {
                        id: campoDoId
                        objectName: "campoDoAccessId"
                        titulo: "Access ID (Client ID)"
                        text: dialogo.assistente ? dialogo.assistente.chave : ""
                        onEditado: dialogo.assistente.chave = text
                    }
                    LinhaDeTexto {
                        objectName: "campoDoAccessSecret"
                        titulo: "Access Secret (Client Secret)"
                        echoMode: dialogo.segredoVisivel ? TextInput.Normal : TextInput.Password
                        text: dialogo.assistente ? dialogo.assistente.segredo : ""
                        onEditado: dialogo.assistente.segredo = text
                        Botao {
                            objectName: "botaoMostrarOSegredo"
                            estilo: "plano"
                            icone: dialogo.segredoVisivel ? "view-conceal" : "view-reveal"
                            dica: dialogo.segredoVisivel ? "Ocultar o texto" : "Mostrar o texto"
                            onClicked: dialogo.segredoVisivel = !dialogo.segredoVisivel
                        }
                    }
                    LinhaDeEscolha {
                        objectName: "regiaoDasFitas"
                        titulo: "Região"
                        model: ["Américas (us)", "Europa (eu)", "China (cn)", "Índia (in)"]
                        currentIndex: dialogo.assistente ? dialogo.assistente.regiao : 0
                        onEscolhido: indice => dialogo.assistente.regiao = indice
                    }
                }

                ColumnLayout {
                    width: parent.width
                    spacing: 12

                    Text {
                        objectName: "avisoSemResultado"
                        Layout.fillWidth: true
                        visible: dialogo.assistente ? dialogo.assistente.semResultado : false
                        text: "Nenhum dispositivo encontrado. Confira as credenciais e a região."
                        textFormat: Text.PlainText
                        wrapMode: Text.Wrap
                        horizontalAlignment: Text.AlignHCenter
                        color: Tema.erro
                        font { family: Tema.fonte; pixelSize: Tema.corpo }
                    }
                    Botao {
                        id: botaoBuscar
                        objectName: "botaoBuscarDasFitas"
                        Layout.alignment: Qt.AlignHCenter
                        estilo: "sugestao"
                        pilula: true
                        text: "Buscar dispositivos"
                        onClicked: dialogo.assistente.buscar()
                    }
                }
            }

            Column {
                width: parent.width
                spacing: 24
                visible: dialogo.pagina === "dispositivos"

                GrupoDePreferencias {
                    objectName: "grupoDosDispositivos"
                    titulo: "Selecione os dispositivos"
                    descricao: "Ao aplicar, somente os dispositivos marcados são mantidos. Desmarcar um dispositivo o remove."

                    // Pela contagem, e não pela lista: marcar um dispositivo refaz a lista, e as linhas (com o foco) têm
                    // de ficar onde estão.
                    Repeater {
                        model: dialogo.assistente ? dialogo.assistente.dispositivos.length : 0
                        LinhaDeAlternancia {
                            id: linhaDoDispositivo
                            required property int index
                            readonly property var dispositivo: dialogo.assistente && index < dialogo.assistente.dispositivos.length
                                ? dialogo.assistente.dispositivos[index] : { id: "", nome: "", subtitulo: "", ativo: false, marcado: false }
                            objectName: "dispositivoDasFitas-" + dispositivo.id
                            // O nome vem da conta da Tuya: sempre PlainText.
                            titulo: dispositivo.nome
                            subtitulo: dispositivo.subtitulo
                            enabled: dispositivo.ativo
                            checked: dispositivo.marcado
                            onAlternado: dialogo.assistente.marcar(dispositivo.id, checked)
                        }
                    }
                }
                Botao {
                    id: botaoAplicar
                    objectName: "botaoAplicarDasFitas"
                    anchors.horizontalCenter: parent.horizontalCenter
                    estilo: "sugestao"
                    pilula: true
                    text: "Aplicar"
                    onClicked: dialogo.assistente.salvar()
                }
            }
        }
    }

    Item {
        Layout.fillWidth: true
        Layout.fillHeight: true
        visible: dialogo.pagina === "buscando"

        Column {
            anchors.centerIn: parent
            width: parent.width - 24
            spacing: 12

            Text {
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap
                text: "Buscando os dispositivos…"
                textFormat: Text.PlainText
                color: Tema.texto
                font { family: Tema.fonte; pixelSize: Tema.titulo1; weight: Tema.pesoTitulo1 }
                Accessible.role: Accessible.Heading
                Accessible.name: text
            }
            Item {
                anchors.horizontalCenter: parent.horizontalCenter
                width: 32
                height: 32 + 24
                Girador {
                    objectName: "buscandoDispositivos"
                    anchors.bottom: parent.bottom
                    width: 32
                    height: 32
                    running: parent.visible
                    Accessible.name: "Buscando"
                }
            }
        }
    }
}
