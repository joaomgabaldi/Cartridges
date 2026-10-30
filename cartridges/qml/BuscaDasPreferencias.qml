pragma Singleton
import QtQuick

// O texto da busca das Preferências, lido por toda linha (`passa`); o `DialogoDePreferencias` o escreve.
QtObject {
    property string texto: ""

    // Sem busca toda linha passa; com ela, vale o título ou o subtítulo (sem diferenciar maiúsculas nem acentos).
    function passa(titulo, subtitulo) {
        return texto === "" || preferencias.corresponde(titulo + " " + (subtitulo || ""), texto)
    }
}
