import QtQuick

// A linha de interruptor das Preferências: liga uma chave de `preferencias.valores` e entra na busca.
LinhaDeAlternancia {
    property string chave
    buscavel: true
    objectName: "interruptor-" + chave
    checked: preferencias.valores[chave] === true
    onAlternado: preferencias.definir(chave, checked)
}
