import QWindowKit

// Fica num arquivo à parte, criado só pela Principal fora dos testes: quem importa o QWindowKit precisa da ponte
// (qwk_ponte.dll) registrada no motor.
WindowAgent {
    function botaoDeSistema(qual, item) {
        setSystemButton(qual === "minimizar" ? WindowAgent.Minimize
                        : qual === "maximizar" ? WindowAgent.Maximize : WindowAgent.Close, item)
    }
}
