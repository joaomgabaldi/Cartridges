pragma Singleton
import QtQuick

// As capas animadas pausadas de todas as grades (Todos e Zerados): guardam o quadro e o arquivo, no máximo 8 ao todo
// (`MAX_PAUSADAS_ABERTAS` de `tocador_capas.py`); passando disso, a mais antiga volta ao primeiro quadro (`liberar`).
QtObject {
    property var lista: []
    readonly property int maximo: 8

    function registrar(cartao) {
        var nova = lista.filter(c => c !== cartao)
        nova.push(cartao)
        while (nova.length > maximo) nova.shift().liberar()
        lista = nova
    }
    function esquecer(cartao) { lista = lista.filter(c => c !== cartao) }
}
