pragma Singleton
import QtQuick

// Cores, fonte e ritmo do app, no tema claro ou escuro do Windows 11.
QtObject {
    id: tema

    readonly property string fonte: "Segoe UI Variable"
    readonly property bool escuro: Qt.styleHints.colorScheme === Qt.Dark
    // A cor de destaque escolhida pelo usuário no Windows.
    readonly property color destaque: sistema.accent

    readonly property color fundo: escuro ? "#242424" : "#fafafa"
    readonly property color texto: escuro ? "#ffffff" : "#1a1a1a"
    readonly property color textoSecundario: escuro ? "#9a9a9a" : "#6b6b6b"
    readonly property color barra: escuro ? "#303030" : "#ebebeb"
    readonly property color barraInativa: escuro ? "#2a2a2a" : "#f3f3f3"
    readonly property color botaoSobre: escuro ? "#3d3d3d" : "#dcdcdc"
    readonly property color botaoFechar: "#c42b1c"
    readonly property color pressionado: escuro ? "#4a4a4a" : "#cccccc"
    readonly property color superficie: escuro ? "#2b2b2b" : "#ffffff"
    readonly property color borda: escuro ? "#454545" : "#d4d4d4"

    // Mesmos códigos nas duas fontes; a Fluent só existe no Windows 11.
    readonly property string fonteDeIcones: Qt.fontFamilies().includes("Segoe Fluent Icons") ? "Segoe Fluent Icons" : "Segoe MDL2 Assets"

    // Ritmo das animações do Windows 11, em ms.
    readonly property int duracaoCurta: 167
    readonly property int duracaoMedia: 250

    readonly property SystemPalette sistema: SystemPalette {}
}
