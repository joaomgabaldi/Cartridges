import QtQuick
import QtQuick.Controls.Basic

// A `Adw.ActionRow` ativável: título, subtítulo e, à direita, um ícone ou o rótulo de um botão. A linha inteira aciona
// (como o `activatable-widget` do Adwaita). Os textos vão em PlainText: o subtítulo pode ser um caminho.
LinhaDoGrupo {
    id: linha

    // O nome do ícone em `data/icones`.
    property string icone
    // Obsoleto: glifo Segoe, até cada pacote trocar pelo `icone` (tabela em docs/auditoria-gtk-qt/COMPONENTES.md).
    property string glifo
    property string rotulo
    property string dica
    // Um segundo botão, à esquerda do rótulo (ex.: "Usar a padrão"); só existe com `rotuloSecundario`.
    property string rotuloSecundario
    property bool secundarioAtivo: true

    // O botão da linha inteira: quem hospeda a linha leva o foco até ele.
    property alias botaoDaLinha: botao

    signal acionada()
    signal secundaria()

    quebraDoSubtitulo: Text.WrapAnywhere
    reservaADireita: ladoDireito.width
    sobre: botao.hovered && !botaoSecundario.hovered
    pressionada: botao.down
    foco: botao.visualFocus

    Button {
        id: botao
        objectName: linha.objectName + "Botao"
        anchors.fill: parent
        focusPolicy: Qt.StrongFocus
        hoverEnabled: true
        Accessible.name: linha.dica !== "" ? linha.dica : linha.titulo
        Accessible.role: Accessible.Button
        Keys.onReturnPressed: click()
        Keys.onEnterPressed: click()
        onClicked: linha.acionada()
        contentItem: Item {}
        background: Item {}
        Dica { texto: linha.dica; ativa: botao.hovered }
    }

    Row {
        id: ladoDireito
        anchors { right: parent.right; rightMargin: 14; verticalCenter: parent.verticalCenter }
        spacing: 12
        // Acima do botão da linha inteira (fica depois dele na ordem de pintura).
        Botao {
            id: botaoSecundario
            objectName: linha.objectName + "BotaoSecundario"
            anchors.verticalCenter: parent.verticalCenter
            visible: linha.rotuloSecundario !== ""
            enabled: linha.secundarioAtivo
            opacity: linha.enabled && !enabled ? Tema.opacidadeDesabilitado : 1  // com a linha desabilitada, ela já apaga tudo
            text: linha.rotuloSecundario
            onClicked: linha.secundaria()
        }
        Icone {
            anchors.verticalCenter: parent.verticalCenter
            visible: linha.icone !== ""
            nome: linha.icone
        }
        Text {
            anchors.verticalCenter: parent.verticalCenter
            visible: linha.icone === "" && text !== ""
            text: linha.glifo !== "" ? linha.glifo : linha.rotulo
            textFormat: Text.PlainText
            color: Tema.texto
            font { family: linha.glifo !== "" ? Tema.fonteDeIcones : Tema.fonte; pixelSize: linha.glifo !== "" ? 16 : Tema.corpo }
        }
    }
}
