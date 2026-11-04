import QtQuick
import QtQuick.Window

// Um ícone simbólico da `main` (`data/icones/<nome>-symbolic.svg`), na cor do texto ao redor.
Image {
    id: icone

    property string nome
    property color cor: Tema.texto
    property int tamanho: 16

    width: tamanho
    height: tamanho
    sourceSize: Qt.size(tamanho * Screen.devicePixelRatio, tamanho * Screen.devicePixelRatio)
    source: nome ? "image://icone/" + nome + "/" + String(cor).slice(1) : ""
    fillMode: Image.PreserveAspectFit
    smooth: true
}
