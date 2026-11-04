import QtQuick

// O botão em cápsula dos modais (`button.pill`): `destaque` é a sugestão da `main`; `perigo`, a ação destrutiva.
Botao {
    property bool destaque: false
    property bool perigo: false

    pilula: true
    estilo: perigo ? "destrutivo" : destaque ? "sugestao" : "normal"
}
