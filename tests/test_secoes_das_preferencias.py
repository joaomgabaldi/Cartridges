# test_secoes_das_preferencias.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""A distribuição das opções pelas dez seções das Preferências (tabela do desenho de 05/11/2026)."""

from cartridges.saves import backup_de_saves
from tests.apoio_qml_preferencias import _abrir, _avaliar, app  # noqa: F401

# seção -> títulos das linhas buscáveis, na ordem da tela (ordem do código dentro de cada grupo)
DISTRIBUICAO = {
    "geral": [
        "Minimizar ao iniciar um jogo",
        "Contar horas de jogo", "Tempo de espera ao fechar o jogo",
        "Nome do jogador", "Idioma dos jogos",
        "Mostrar o botão Novidades", "Reproduzir capas animadas automaticamente",
    ],
    "controle": [
        "Usar controle Xbox", "Vibração",
        "Abrir o Big Picture ao usar um controle", "Som ao trocar de capa",
    ],
    "monitores": [
        "Mover para outro monitor", "Monitor", "Identificar monitores",
        "Trocar o papel de parede dos outros monitores", "Chave da API do wallhaven (opcional)",
    ],
    "iluminacao": [
        "Brilho máximo por dispositivo", "Calibrar as cores", "Configurar a iluminação inteligente", "Testar",
        "Mudar a cor da iluminação inteligente", "Brilho (%)", "Cor acompanha a tela do jogo", "Cor do app",
    ],
    "importacao": ["Importar jogos automaticamente", "Remover jogos desinstalados", "Atalhos"],
    "metadados": [
        "Buscar metadados da Steam", "Buscar tempos do HowLongToBeat",
        "Atualizar metadados",
        "Chave da API", "Usar o SteamGridDB", "Priorizar o SteamGridDB às imagens oficiais", "Preferir imagens animadas",
        "Atualizar capas",
    ],
    "conquistas": [
        "Chave da API",
        "Mostrar descrição das conquistas ocultas",
        "Mostrar aviso durante o jogo", "Tocar som com o aviso", "Volume do som (%)", "Posição do aviso",
        "Mostrar um aviso de exemplo",
        "Piscar a iluminação inteligente", "Cor do alerta", "Estilo do alerta", "Testar o alerta",
    ],
    "contas": ["Conta Microsoft", "Conta Epic", "Conta EA"],
    "backup": [
        "Exportar para arquivo", "Importar de arquivo",
        "Pasta dos saves", "Restaurar saves de todos os jogos",
    ],
    "aplicativo": ["Buscar atualizações", "Redefinir Kyron"],
}


def test_cada_opcao_esta_em_exatamente_uma_secao(app, monkeypatch):  # noqa: F811
    # Com os saves disponíveis, "Pasta dos saves" e "Restaurar saves" aparecem.
    monkeypatch.setattr(backup_de_saves, "disponivel", lambda: True)
    _abrir(app)
    vistas = set()
    for secao, esperados in DISTRIBUICAO.items():
        titulos = _avaliar(
            app.achar("dialogoDePreferencias"), f"linhasBuscaveis('{secao}').map(l => l.titulo)"
        )
        assert titulos == esperados, secao
        vistas.update((secao, t) for t in titulos)
    # o par (seção, título) é único: "Chave da API" existe em Metadados e em Conquistas
    assert len(vistas) == sum(len(ts) for ts in DISTRIBUICAO.values())
