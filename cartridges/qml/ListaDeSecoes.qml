import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// A coluna da esquerda das Preferências: título, busca e uma linha por seção (com o contador de opções). Só desenha: quem
// guarda a seção atual é o diálogo.
Rectangle {
    id: lista
    objectName: "listaDeSecoes"

    property var secoes: []
    property string secao
    // Cartão estreito: lista menor e sem contadores, para as linhas da direita não ficarem espremidas.
    property bool compacta: false
    property var contagem: id => 0
    property real raio: 15
    property alias texto: campoDeBusca.text
    readonly property alias campo: campoDeBusca

    signal escolhida(string id)
    signal entrarNasLinhas()
    signal buscaEncerrada()

    function focarSecao(id) {
        var k = secoes.findIndex(s => s.id === id)
        if (k >= 0) repetidor.itemAt(k).forceActiveFocus(Qt.TabFocusReason)
    }
    // A lista rola só se não couber: o item nunca fica fora da vista.
    function mostrarItem(item) {
        var topo = item.mapToItem(rolagemDaLista.contentItem, 0, 0).y, base = topo + item.height
        if (topo < rolagemDaLista.contentY) rolagemDaLista.contentY = topo
        else if (base > rolagemDaLista.contentY + rolagemDaLista.height)
            rolagemDaLista.contentY = Math.max(0, base - rolagemDaLista.height)
    }
    // Ao abrir numa seção abaixo da dobra (janela muito baixa), traz o item atual à vista.
    function mostrarAtual() {
        var k = secoes.findIndex(s => s.id === secao)
        var item = k >= 0 ? repetidor.itemAt(k) : null  // sem delegates ainda, não há o que mostrar
        if (item) mostrarItem(item)
    }
    function irPara(indice) {
        if (indice >= 0 && indice < secoes.length) repetidor.itemAt(indice).forceActiveFocus(Qt.TabFocusReason)
    }

    color: Tema.cartao
    topLeftRadius: raio
    bottomLeftRadius: raio

    Rectangle {
        anchors { right: parent.right; top: parent.top; bottom: parent.bottom }
        width: 1
        color: Tema.contorno
    }

    ColumnLayout {
        anchors { fill: parent; rightMargin: 1; leftMargin: 12; topMargin: 16 }
        spacing: 10

        Text {
            Layout.fillWidth: true
            Layout.rightMargin: 12
            Layout.leftMargin: 8
            text: "Preferências"
            textFormat: Text.PlainText
            elide: Text.ElideRight
            color: Tema.texto
            font { family: Tema.fonte; pixelSize: Tema.titulo4; weight: Tema.pesoForte }
            Accessible.role: Accessible.Heading
            Accessible.name: text
        }

        CampoDeBusca {
            id: campoDeBusca
            objectName: "campoDeBuscaDasPreferencias"
            Layout.fillWidth: true
            Layout.rightMargin: 12
            placeholderText: "Buscar nas Preferências"
            Accessible.name: "Buscar nas Preferências"
            Keys.onDownPressed: lista.focarSecao(lista.secao)
            // Sem texto o Esc segue para a moldura e fecha o diálogo.
            Keys.onEscapePressed: event => {
                event.accepted = text !== ""
                if (event.accepted) lista.buscaEncerrada()
            }
        }

        Flickable {
            id: rolagemDaLista
            objectName: "rolagemDaLista"
            Layout.fillWidth: true
            Layout.fillHeight: true
            contentWidth: width
            contentHeight: itens.implicitHeight + 12
            boundsBehavior: Flickable.StopAtBounds
            clip: true
            ScrollBar.vertical: BarraDeRolagem {}
            // O cartão só ganha a altura final depois de aberto: reajusta a vista quando ela muda.
            onHeightChanged: lista.mostrarAtual()

            Column {
                id: itens
                width: parent.width - 12
                spacing: 2

                Repeater {
                    id: repetidor
                    model: lista.secoes

                    Button {
                        id: item
                        required property var modelData
                        required property int index
                        readonly property bool atual: lista.secao === modelData.id
                        objectName: "secao-" + modelData.id
                        width: itens.width
                        height: 36
                        padding: 0
                        text: modelData.titulo
                        hoverEnabled: true
                        focusPolicy: Qt.StrongFocus
                        // Uma parada só no Tab (a da seção atual); as demais, pelas setas.
                        activeFocusOnTab: atual
                        readonly property bool setasProprias: true  // ver `passoNosPopups` no Aplicativo.qml
                        Accessible.role: Accessible.PageTab
                        Accessible.name: text
                        // A seção acompanha o foco: o teclado e o controle já mostram a seção ao chegar no item.
                        onActiveFocusChanged: if (activeFocus) {
                            lista.escolhida(modelData.id)
                            lista.mostrarItem(item)
                        }
                        // Clique/Enter encerram a busca (senão a direita seguiria nos resultados). Não no foco: o Tab
                        // do campo aos resultados passa por este item e não pode apagar o texto.
                        onClicked: { lista.texto = ""; lista.escolhida(modelData.id) }
                        Keys.onReturnPressed: click()
                        Keys.onEnterPressed: click()
                        Keys.onDownPressed: lista.irPara(index + 1)
                        Keys.onUpPressed: index === 0 ? campoDeBusca.forceActiveFocus(Qt.TabFocusReason) : lista.irPara(index - 1)
                        Keys.onRightPressed: lista.entrarNasLinhas()

                        contentItem: RowLayout {
                            spacing: 10
                            Icone {
                                Layout.leftMargin: 12
                                nome: item.modelData.icone
                                opacity: item.atual ? 1 : 0.8
                            }
                            Text {
                                Layout.fillWidth: true
                                text: item.text
                                textFormat: Text.PlainText
                                elide: Text.ElideRight
                                color: Tema.texto
                                font { family: Tema.fonte; pixelSize: Tema.corpo; weight: item.atual ? Tema.pesoForte : Font.Normal }
                            }
                            Text {
                                objectName: "contadorDaSecao-" + item.modelData.id
                                Layout.rightMargin: 12
                                visible: !lista.compacta
                                text: lista.compacta ? "" : String(lista.contagem(item.modelData.id))
                                textFormat: Text.PlainText
                                color: Tema.textoSecundario
                                font { family: Tema.fonte; pixelSize: Tema.legenda }
                            }
                        }
                        background: Rectangle {
                            radius: 8
                            color: item.down ? Tema.planoPressionado : item.atual ? Tema.planoLigado : item.hovered ? Tema.planoSobre : "transparent"
                            Behavior on color { ColorAnimation { duration: Tema.duracaoCurta } }
                            Rectangle {
                                visible: item.atual
                                x: 0
                                anchors.verticalCenter: parent.verticalCenter
                                width: 3
                                height: 16
                                radius: 1.5
                                color: Tema.destaque
                            }
                            AnelDeFoco { ativo: item.visualFocus; raio: 8; afastamento: -2 }
                        }
                    }
                }
            }
        }
    }
}
