import QtQuick

// O botão em cápsula dos modais: `destaque` é a sugestão; `perigo`, a ação destrutiva.
Botao {
    property bool destaque: false
    property bool perigo: false

    pilula: true
    estilo: perigo ? "destrutivo" : destaque ? "sugestao" : "normal"
}
