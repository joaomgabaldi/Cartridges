import QtQuick
import QtQuick.Layouts

// A casca dos seletores (`Adw.Dialog` + `ToolbarView` com a `HeaderBar` e a `SearchBar`): moldura, cabeçalho de 47 com o
// X à direita (depois do botão extra), a faixa de busca de 46 (campo de 34 centrado, até 450) e a área do conteúdo.
// O foco inicial é o do diálogo da `main`: o primeiro botão do cabeçalho, ou o campo; nunca forçado depois.
// `fim`: os botões do cabeçalho; o que for declarado dentro entra abaixo da faixa de busca (com `Layout.fillHeight: true`).
MolduraDoDialogo {
    id: base

    property string titulo
    // Os `objectName` do título e do campo (os testes de cada seletor): este prefixo mais "Titulo" e "Campo".
    property string prefixoDosObjetos: objectName
    property bool comBusca: true
    property string placeholder: "Buscar jogo…"
    property string nomeDaBusca: "Buscar jogo"
    // `Adw.Clamp (maximum-size: 450)`; Ludusavi e Zerados não têm clamp e margens de 12.
    property real larguraDoCampo: 450
    property real margemDoCampo: 6
    property bool campoAtivo: true
    // A linha de baixo da barra aparece com o conteúdo rolado.
    property bool rolado: false
    property alias fim: cabecalho.fim
    readonly property alias campo: campoDeBusca

    // O texto mudou por ação da pessoa; Enter no campo; seta para baixo no campo.
    signal buscaEditada(string texto)
    signal buscaConfirmada()
    signal setaParaBaixo()

    largura: 720
    altura: 620
    focoInicial: comBusca ? campoDeBusca : null

    CabecalhoDoDialogo {
        id: cabecalho
        objetoDoTitulo: base.prefixoDosObjetos + "Titulo"
        titulo: base.titulo
        sombra: base.rolado && !base.comBusca
        onFechar: base.fecharPedido()
    }

    Item {
        Layout.fillWidth: true
        implicitHeight: base.comBusca ? 46 : 0
        visible: base.comBusca

        CampoDeBusca {
            id: campoDeBusca
            objectName: base.prefixoDosObjetos + "Campo"
            x: Math.round((parent.width - width) / 2)
            y: 6
            width: Math.min(base.larguraDoCampo, parent.width - 2 * base.margemDoCampo)
            enabled: base.campoAtivo
            opacity: enabled ? 1 : Tema.opacidadeDesabilitado
            placeholderText: base.placeholder
            Accessible.name: base.nomeDaBusca
            onTextEdited: base.buscaEditada(text)
            onAccepted: base.buscaConfirmada()
            Keys.onDownPressed: base.setaParaBaixo()
        }
        Rectangle {
            anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
            height: 1
            visible: base.rolado
            color: Tema.sombraDaBarra
        }
    }
}
