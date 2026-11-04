import QtQuick

Botao {
    property bool destaque: false
    property bool perigo: false

    pilula: true
    estilo: perigo ? "destrutivo" : destaque ? "sugestao" : "normal"
}
