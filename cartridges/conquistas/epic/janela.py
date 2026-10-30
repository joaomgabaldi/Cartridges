"""O que a janela de login da Epic diz: a página da Epic abre no navegador, e o usuário
cola o código que ela mostra.

A regra e a tela são de `modelos/contas.py` (`LoginDaLoja`) e de `JanelaDeLogin.qml`; aqui só os textos.
"""

from cartridges.conquistas.epic import conta
from cartridges.modelos.contas import Loja

LOJA = Loja(
    titulo=_("Entrar na conta Epic"),
    passos=(
        _("1. Entre na sua conta na página que foi aberta no navegador."),
        _('2. Copie o código exibido em "authorizationCode".'),
        _("3. Cole o código abaixo."),
    ),
    rotulo_do_campo=_("Código de autorização"),
    multilinha=False,
    botao_da_pagina=_("Abrir a página novamente"),
    url_do_botao=conta.PAGINA_DE_LOGIN,
    aviso_sem_navegador=_("Não foi possível abrir o navegador. Copie o endereço abaixo e abra-o no navegador."),
    # Sem navegador, o código só aparece na página de redirecionamento: o endereço fica à mostra.
    mostra_endereco=True,
    texto_recusado=_("O código não foi aceito. Gere um novo código na página da Epic e tente novamente."),
    texto_falhou=_("Não foi possível entrar na conta Epic."),
    log="Epic",
    conta=conta,
    extrair=conta.extrair_codigo,
    recusa=conta.CodigoRecusado,
    argumento=lambda _texto, codigo: codigo,
)
