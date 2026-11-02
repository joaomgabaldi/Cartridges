import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// "Brilho máximo por dispositivo", por cima das Preferências (`Adw.Dialog` com a `HeaderBar` e uma `PreferencesPage`): uma
// linha de número por fita. Só desenha: o que ele mostra e grava é o `preferencias.brilhoPorDispositivo`
// (cartridges/modelos/preferencias.py), que existe só enquanto a janela está aberta. Cada mudança acende as fitas no número
// dela; só o Salvar grava. Esc cancela.
MolduraDoDialogo {
    id: dialogo
    objectName: "dialogoDoBrilhoPorDispositivo"

    readonly property var modelo: preferencias.brilhoPorDispositivo

    aberto: !!modelo
    largura: 420
    // O foco abre no primeiro controle, o Cancelar (o `Adw.Dialog` da `main` não tem resposta padrão).
    focoInicial: botaoCancelar
    nomeAcessivel: "Brilho máximo por dispositivo"
    onFecharPedido: if (modelo) modelo.cancelar()

    CabecalhoDoDialogo {
        titulo: "Brilho máximo por dispositivo"
        comFechar: false
        sombra: rolagem.contentY > 0
        inicio: [
            Botao {
                id: botaoCancelar
                objectName: "botaoCancelarDoBrilho"
                estilo: "plano"
                text: "Cancelar"
                onClicked: dialogo.modelo.cancelar()
            }
        ]
        fim: [
            Botao {
                objectName: "botaoSalvarDoBrilho"
                estilo: "sugestao"
                text: "Salvar"
                onClicked: dialogo.modelo.salvar()
            }
        ]
    }

    Flickable {
        id: rolagem
        Layout.fillWidth: true
        Layout.fillHeight: true
        Layout.preferredHeight: contentHeight
        contentWidth: width
        contentHeight: grupos.implicitHeight + 48
        boundsBehavior: Flickable.StopAtBounds
        clip: true
        ScrollBar.vertical: BarraDeRolagem {}

        // `PreferencesPage`: 24 em cima e embaixo, 12 dos lados.
        Column {
            id: grupos
            x: 12
            y: 24
            width: rolagem.width - 24

            // Criado com o diálogo já à vista: o grupo some enquanto a altura é zero, e um `Column` não conta as linhas
            // que nascem sob um pai escondido (a altura nunca sairia de zero).
            Loader {
                width: parent.width
                active: dialogo.visible
                sourceComponent: GrupoDePreferencias {
                    descricao: "Brilho máximo de cada dispositivo, em porcentagem. O brilho definido nas Preferências e em cada jogo é aplicado proporcionalmente sobre estes valores."

                    Repeater {
                        model: dialogo.modelo ? dialogo.modelo.linhas : []
                        LinhaDeNumero {
                            required property var modelData
                            objectName: "brilhoDoDispositivo-" + modelData.id
                            // O nome é texto de fora (a conta da Tuya): a `LinhaDeNumero` o mostra em PlainText.
                            titulo: modelData.nome
                            de: 1
                            ate: 100
                            passo: 1
                            value: modelData.brilho
                            onAlterado: valor => {
                                value = valor
                                dialogo.modelo.mudar(modelData.id, valor)
                            }
                        }
                    }
                }
            }
        }
    }
}
