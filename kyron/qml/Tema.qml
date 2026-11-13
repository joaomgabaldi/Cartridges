pragma Singleton
import QtQuick

QtObject {
    id: tema

    readonly property string fonte: "Segoe UI"
    // A cor de destaque do Windows (`AccentColor` cru), posta na paleta por `aplicar_cor_de_destaque`.
    readonly property color destaque: sistema.accent
    readonly property color textoDoDestaque: "#ffffff"
    // O destaque como texto, foco e link. Nunca o `destaque` cru sobre o fundo do app.
    readonly property color destaqueTexto: derivada(destaque)

    // Tipografia: Segoe UI 9 pt = 12 px a 96 DPI; os títulos são percentuais do corpo.
    readonly property int corpo: 12
    readonly property int titulo1: 22       // 181%
    readonly property int titulo2: 16       // 136%
    readonly property int titulo3: 16       // 136%
    readonly property int titulo4: 14       // 118%
    readonly property int legenda: 10       // legenda e subtítulo das linhas, 82%
    // A altura de linha esperada: 1 px a mais que a do Qt. Onde a altura do bloco conta, use com
    // `lineHeightMode: Text.FixedHeight`.
    readonly property int alturaDoCorpo: 17
    readonly property int alturaDaLegenda: 14
    readonly property int alturaDoTitulo2: 23
    readonly property int pesoCorpo: 400
    readonly property int pesoTitulo1: 800
    readonly property int pesoTitulo2: 800
    readonly property int pesoTitulo3: 700
    readonly property int pesoTitulo4: 700
    readonly property int pesoForte: 700    // títulos, legendas em destaque e todo botão com texto

    // A cor do texto. As misturas abaixo somam o alfa do estado a esse.
    readonly property color corBase: "#ffffff"

    readonly property color fundo: "#222226"
    readonly property color texto: "#ffffff"
    readonly property color textoSecundario: Qt.rgba(1, 1, 1, 0.55)
    // Só o anel do selo usa; a barra da janela é plana, da cor do `fundo`.
    readonly property color barra: "#2e2e32"
    readonly property color barraInativa: "#222226"
    readonly property color sombraDaBarra: Qt.rgba(0, 0, 6 / 255, 0.36)
    readonly property color botao: mistura(0.10)
    readonly property color botaoSobre: mistura(0.15)
    readonly property color pressionado: mistura(0.30)
    readonly property color planoSobre: mistura(0.07)
    readonly property color planoPressionado: mistura(0.16)
    readonly property color planoLigado: mistura(0.10)
    readonly property color linhaSobre: mistura(0.04)
    readonly property color linhaPressionada: mistura(0.08)
    readonly property color menuSobre: mistura(0.10)
    readonly property color menuPressionado: mistura(0.19)
    readonly property color destrutivo: "#c01c28"
    readonly property color destrutivoTexto: derivada(destrutivo)
    // Propriedade `color`, e não texto: a `derivada` lê `.r .g .b`, e de um texto sairia preto.
    readonly property color avisoBase: "#cd9309"
    readonly property color avisoIcone: derivada(avisoBase)
    readonly property color erro: "#ff938c"
    readonly property color cartao: Qt.rgba(1, 1, 1, 0.08)
    readonly property color sombraDoCartao: Qt.rgba(0, 0, 6 / 255, 0.36)
    readonly property color dialogo: "#36363a"
    readonly property color popover: "#36363a"
    readonly property color vista: "#1d1d20"
    // `shade_color` dobrado: o escurecimento atrás de um diálogo.
    readonly property color esmaecido: Qt.rgba(0, 0, 6 / 255, 0.5)
    readonly property color superficie: dialogo
    readonly property color borda: mistura(0.15)
    readonly property color aviso: "#505053"
    readonly property color contorno: Qt.rgba(1, 1, 1, 0.07)
    readonly property real opacidadeDesabilitado: 0.5
    readonly property real opacidadeApagado: 0.55

    readonly property var sombraCartao: [[0, 0, 1, 0, 0, 6 / 255, 0.03], [1, 3, 1, 0, 0, 6 / 255, 0.07], [2, 6, 2, 0, 0, 6 / 255, 0.03]]
    readonly property var sombraDialogo: [[0, 14, 2, 0, 0, 6 / 255, 0.03], [0, 5, 2, 0, 0, 6 / 255, 0.10], [0, 0, 1, 0, 0, 0, 0.05]]
    readonly property var sombraPopover: [[0, 0, 1, 0, 0, 0, 0.05], [1, 5, 1, 0, 0, 0, 0.09], [2, 14, 3, 0, 0, 0, 0.05]]
    readonly property var sombraAviso: [[1, 3, 1, 0, 0, 6 / 255, 0.07], [2, 6, 2, 0, 0, 6 / 255, 0.03]]

    readonly property string fonteDeIcones: Qt.fontFamilies().includes("Segoe Fluent Icons") ? "Segoe Fluent Icons" : "Segoe MDL2 Assets"

    // Transições: 200 ms cubic-bezier(0.25, 0.46, 0.45, 0.94). Use com `Easing.Bezier`, em `easing.bezierCurve`.
    readonly property int duracaoCurta: 200
    readonly property int duracaoMedia: 200
    readonly property var curva: [0.25, 0.46, 0.45, 0.94, 1, 1]

    // Os efeitos de animação do Windows; os testes rodam sem a animação de abrir e fechar diálogos, para o `visible` ser síncrono.
    readonly property bool animacoes: !Qt.application.arguments.includes("--sem-animacao-de-dialogo")
        && (typeof aplicativo === "undefined" || aplicativo === null || aplicativo.animacoesDoSistema !== false)

    // Os anéis de uma lista de camadas, calculados uma vez por lista (cada cartão da grade pede os mesmos).
    readonly property var _aneisPorCamadas: ({})
    // Como o `box-shadow` do CSS (GTK): gaussiana de desvio desfoque/2 depois do espalhamento, até 3 desvios.
    // O anel `d` cobre a faixa de 0 a d e os anéis se compõem (1 - Π(1 - α)), então cada α é o que leva
    // a composição até a força `forca(d - 1)`.
    function aneis(camadas) {
        const chave = JSON.stringify(camadas)
        if (_aneisPorCamadas[chave]) return _aneisPorCamadas[chave]
        var aneis = []
        const fi = z => {  // Φ, a normal acumulada (Abramowitz-Stegun 7.1.26: erro < 1,5e-7)
            const t = 1 / (1 + 0.3275911 * Math.abs(z) / Math.SQRT2)
            const erf = 1 - t * (0.254829592 + t * (-0.284496736 + t * (1.421413741 + t * (-1.453152027 + t * 1.061405429)))) * Math.exp(-z * z / 2)
            return 0.5 * (1 + (z < 0 ? -erf : erf))
        }
        for (var c of camadas) {
            const [dy, desfoque, espalhamento, r, g, b, a] = c
            const sigma = desfoque / 2
            const fim = espalhamento + Math.ceil(3 * sigma)
            const forca = x => x >= fim ? 0 : sigma === 0 ? (x < espalhamento ? a : 0) : a * (1 - fi((x - espalhamento) / sigma))
            for (var d = 1; d <= fim; ++d) {
                const alfa = (forca(d - 1) - forca(d)) / Math.max(1e-6, 1 - forca(d))
                if (alfa * 255 >= 0.5)  // abaixo de meio passo de 8 bits o anel não muda nenhum pixel: não vira Rectangle
                    aneis.push({ dy: dy, d: d, cor: Qt.rgba(r, g, b, alfa) })
            }
        }
        _aneisPorCamadas[chave] = aneis
        return aneis
    }

    readonly property SystemPalette sistema: SystemPalette {}

    function mistura(alfa) { return Qt.rgba(corBase.r, corBase.g, corBase.b, corBase.a * alfa) }

    // `oklab(from cor max(l, 0.85) a b)`: a cor de texto sobre o fundo escuro.
    function derivada(cor) {
        const linear = c => c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4)
        const srgb = c => { c = Math.min(1, Math.max(0, c)); return c <= 0.0031308 ? c * 12.92 : 1.055 * Math.pow(c, 1 / 2.4) - 0.055 }
        const r = linear(cor.r), g = linear(cor.g), b = linear(cor.b)
        const m = Math.cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b)
        const n = Math.cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b)
        const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b)
        const l0 = 0.2104542553 * m + 0.7936177850 * n - 0.0040720468 * s
        const a0 = 1.9779984951 * m - 2.4285922050 * n + 0.4505937099 * s
        const b0 = 0.0259040371 * m + 0.7827717662 * n - 0.8086757660 * s
        const l1 = Math.max(l0, 0.85)
        const p = Math.pow(l1 + 0.3963377774 * a0 + 0.2158037573 * b0, 3)
        const q = Math.pow(l1 - 0.1055613458 * a0 - 0.0638541728 * b0, 3)
        const u = Math.pow(l1 - 0.0894841775 * a0 - 1.2914855480 * b0, 3)
        return Qt.rgba(srgb(4.0767416621 * p - 3.3077115913 * q + 0.2309699292 * u),
                       srgb(-1.2684380046 * p + 2.6097574011 * q - 0.3413193965 * u),
                       srgb(-0.0041960863 * p - 0.7034186147 * q + 1.7076147010 * u), 1)
    }
}
