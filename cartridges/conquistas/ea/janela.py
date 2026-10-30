"""O que a janela de login da EA diz: a página da EA abre no navegador, e o usuário cola
o pedido que copiou ("Copiar como cURL").

A regra e a tela são de `modelos/contas.py` (`LoginDaLoja`) e de `JanelaDeLogin.qml`; aqui só os textos.
"""

from cartridges.conquistas.ea import conta
from cartridges.modelos.contas import Loja

LOJA = Loja(
    titulo=_("Entrar na conta EA"),
    passos=(
        _("1. Entre na sua conta EA na página que foi aberta no navegador."),
        _("2. No navegador, pressione F12 e abra a aba Rede."),
        _("3. Clique em Abrir a página da conta, abaixo."),
        _(
            '4. Na aba Rede, clique com o botão direito no pedido que começa com "auth?client_id" '
            "e escolha Copiar › Copiar como cURL."
        ),
        _("5. Cole o texto abaixo."),
    ),
    rotulo_do_campo=_("Texto copiado do navegador"),
    multilinha=True,
    botao_da_pagina=_("Abrir a página da conta"),
    url_do_botao=conta.TOKEN,
    aviso_sem_navegador=_("Não foi possível abrir o navegador. Acesse ea.com/login manualmente."),
    mostra_endereco=False,
    texto_recusado=_("A EA não reconheceu o login. Entre novamente em ea.com e copie o pedido outra vez."),
    texto_falhou=_("Não foi possível entrar na conta EA. Verifique a conexão e tente novamente."),
    log="EA",
    conta=conta,
    extrair=conta.extrair,
    recusa=conta.LoginRecusado,
    # A EA recebe o texto colado inteiro: dele ela tira os cookies de novo.
    argumento=lambda texto, _extraido: texto,
)
