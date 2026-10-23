<div align="center">
  <img src="data/icons/hicolor/scalable/apps/io.github.joaomgabaldi.Cartridges.svg" width="128" height="128">

  # Cartridges

  Seus jogos em um só lugar — launcher de jogos para Windows, em GTK4 e Libadwaita
</div>

Este é um fork da versão para Windows do [Cartridges](https://codeberg.org/kramo/cartridges), o launcher
criado por kramo para o GNOME. O projeto original (abandonado) reúne jogos de vários launchers do Linux; esta
versão reúne os jogos de um PC com Windows a partir de uma pasta de atalhos e acrescenta novas funções como:
acompanhamento de tempo de jogo por sessão, conquistas das lojas Steam, Epic, Ubisoft, Xbox e EA,
registro pessoal de cada jogo, metadados da Steam e do HowLongToBeat, navegação por controle Xbox,
papel de parede, busca por capas e logos e controle de iluminação inteligente que acompanham o
jogo aberto, além de backup completo, backup dos saves e atualização automática.

A interface é inteiramente em português do Brasil.

![Biblioteca de jogos](data/screenshots/biblioteca.jpg)

## Recursos

### Biblioteca e importação

- Importa uma pasta de atalhos, com ou sem subpastas:
  - atalhos `.lnk` de executáveis comuns;
  - atalhos de internet `.url` (Steam, Epic, Ubisoft Connect e outros);
  - atalhos de aplicativos da Microsoft Store e do Game Pass.
- Importação automática ao abrir o aplicativo, e remoção automática dos jogos desinstalados (opcional).
- Limpeza dos títulos importados (remove sufixos como "Windows", "DX11", "DX12" e "(DirectX 12)").
- Um jogo continua reconhecido quando o destino do atalho muda — atualização instalada, pasta
  movida, executável trocado —, sem perder tempo de jogo, capa, logo nem histórico.
- Jogos adicionados manualmente, com seletor de executável e opção "Abrir como administrador".
- Busca por título, desenvolvedora, publicadora e anotação.
- Ordenação por título, data de adição, jogados recentemente, mais jogados, data de lançamento,
  nota pessoal e tamanho no disco.
- Filtros por gênero, ano de lançamento e status, combináveis entre si e com a busca.
- Grade com número de colunas acompanhando a largura da janela, e capas que deslizam até a nova
  posição quando a grade se reorganiza.
- Capas animadas reproduzidas ao passar o mouse ou, se preferir, o tempo todo na biblioteca.
- **Tarefas em andamento**: importações, atualizações de metadados e outras tarefas em segundo
  plano aparecem num botão no canto da biblioteca, que abre uma janela com o progresso de cada
  uma. A janela pode ficar aberta ao lado do aplicativo, e o trabalho continua mesmo com a janela
  principal fechada.
- Navegação suave e agradável.

### Metadados e imagens

- Da Steam: título, desenvolvedora, publicadora, data de lançamento, gênero (pelas etiquetas da
  loja), descrição em português, avaliações, Metacritic, compatibilidade com controle e o selo
  "Gamepad Recomendado".
- Do [HowLongToBeat](https://howlongtobeat.com): tempos de História, Extras e Completista.
- Do [SteamGridDB](https://www.steamgriddb.com): capas em alta resolução, capas animadas
  (reproduzidas ao passar o mouse) e logos para o topo da tela de detalhes.
- "Atualizar metadados" e "Atualizar capas" para a biblioteca já importada, buscando só o que
  falta ou relendo tudo, com andamento e cancelamento.
- Campos editados manualmente não são sobrescritos pela busca automática.
- Capa e logo também podem vir de um arquivo do computador. Um vídeo (mp4, webm, mkv...) vira capa
  animada: os primeiros 15 segundos, sem áudio, convertidos pelo `ffmpeg`.
- Atalhos para buscar o jogo no IGDB, no SteamGridDB, no PCGamingWiki e no HowLongToBeat.

### Tela de detalhes

- Capa, logo, fundo desfocado, datas, tempo de jogo e tamanho no disco.
- Os tempos do HowLongToBeat e o andamento das conquistas, com as últimas desbloqueadas.
- Botão para abrir a pasta de instalação do jogo, quando ela pode ser determinada.

![Tela de detalhes de um jogo](data/screenshots/detalhes.jpg)

### Registro pessoal de cada jogo

- Status: "Quero jogar", "Jogando", "Zerado" ou "Abandonado", alterado com um clique.
- Nota pessoal de uma a cinco estrelas.
- Anotação livre "Onde eu parei", acessível pela tela de detalhes, pela janela do jogo em
  andamento e pelo aviso de fim de sessão.
- **Jogos Zerados**: os jogos desinstalados marcados como Zerado continuam no aplicativo, com capa,
  informações, nota e histórico de sessões. Quando o jogo é reinstalado, os dois registros se unem.
  Jogos também podem ser adicionados diretamente na tela de zerados, buscados na Steam ou
  somente pelo nome.

![Jogos Zerados](data/screenshots/zerados.jpg)

### Conquistas

- As conquistas desbloqueadas são acompanhadas enquanto você joga, nas lojas Steam, Epic Games,
  Ubisoft Connect, Xbox (incluindo o Game Pass) e EA app, e em alguns jogos 🏴‍☠️.
- Para o Xbox, a Epic e a EA, basta entrar na conta na aba Conquistas das Preferências. Para os jogos
  🏴‍☠️, uma chave da Steam Web API traz o nome e a descrição das conquistas em português.
- A janela de conquistas de cada jogo mostra o progresso, as desbloqueadas (com a data e a
  porcentagem de jogadores que também a têm), as bloqueadas e as ocultas.
- Ao abrir o aplicativo, um aviso informa quantas conquistas foram desbloqueadas desde a última
  vez.
- **Durante o jogo**: quando a loja não mostra o próprio aviso, o Cartridges mostra um no canto da
  tela, com som (volume ajustável) e posição à escolha. A iluminação inteligente pisca na cor e no
  estilo escolhidos. Várias conquistas de uma vez viram um único som e um único pulso.

![Conquistas de um jogo](data/screenshots/conquistas.jpg)

<p align="center"><img src="data/screenshots/conquistas-preferencias.png" width="480" alt="Opções das conquistas durante o jogo"></p>

### Tempo de jogo e sessões

- O tempo é contado automaticamente, observando o processo do jogo: pelo executável, pela pasta
  de instalação ou pelo pacote da Microsoft Store. Jogos com lançador separado ou que trocam de
  executável são acompanhados corretamente.
- Jogos abertos por um link de loja usam uma janela compacta para encerrar a sessão.
- Cada sessão é registrada individualmente: data, hora de término e duração.
- O histórico de sessões mostra um gráfico de horas por dia (semana, mês ou todo o período) e o
  total dos últimos 7 e 30 dias. Uma sessão pode ser excluída, e o tempo dela é descontado do total.
- O PC suspenso com o jogo aberto não conta como tempo de jogo, e um reinício rápido do jogo não
  divide a sessão.

![Histórico de sessões com gráfico de horas por dia](data/screenshots/historico.png)

### Durante a sessão

Todos estes recursos ficam na aba Personalização das Preferências e vêm desativados por padrão.

- **Outro monitor**: ao iniciar um jogo, a janela pode ir maximizada para o monitor escolhido, com
  o logo do jogo em destaque, um relógio contando o tempo da sessão e as conquistas do jogo (a
  descrição de cada uma aparece ao passar o mouse). Ao final, ela volta ao monitor e ao tamanho de
  antes.
- **Papel de parede**: os monitores além do principal podem exibir a arte do jogo, buscada no
  [wallhaven](https://wallhaven.cc) ou escolhida manualmente, com ajuste de enquadramento para
  monitores em retrato e em paisagem. Ao final da sessão, cada monitor volta ao papel de parede
  que tinha.
<p align="center"><img src="data/screenshots/personalizacao.png" width="480" alt="Aba Personalização das Preferências"></p>

### Iluminação inteligente

Fitas de LED e lâmpadas inteligentes da Tuya, configuradas uma vez por um assistente que busca os
dispositivos na sua conta; depois disso, o aplicativo conversa com eles direto pela rede de casa.

- A iluminação fica na cor do aplicativo enquanto ele está aberto e passa para a cor do jogo
  durante a sessão. Ao fechar o aplicativo, ela volta exatamente ao estado anterior.
- A cor de cada jogo é automática (extraída da capa) ou escolhida manualmente, e o brilho de cada
  jogo pode ser ajustado sem trocar a cor automática.
- **Cor acompanha a tela do jogo** (experimento): durante a sessão, a cor acompanha devagar a cor
  predominante do jogo na tela, com cores vivas e brilho menor nas cenas escuras. Na edição do
  jogo, a cor aparece como "Automático".
- **Brilho máximo por dispositivo**, aplicado proporcionalmente sobre o brilho geral e o de cada
  jogo.
- **Calibrar as cores**: um assistente, no estilo da calibração de HDR do Windows, ajusta cada
  dispositivo para reproduzir as cores como a tela, em seis cores de referência e no branco. Dá
  para calibrar um dispositivo por vez ou todos juntos, cada um com os seus controles, e testar o
  resultado antes de salvar.
- As trocas de cor acontecem em degradê. Um dispositivo que para de responder durante o jogo é
  procurado de novo sozinho, e um aviso no fim da sessão informa se ele ficou muito tempo sem
  responder.

<p align="center"><img src="data/screenshots/iluminacao.png" width="480" alt="Opções da iluminação inteligente"></p>

<p align="center"><img src="data/screenshots/calibracao.png" width="420" alt="Assistente de calibração das cores"></p>

### Controle Xbox

- Navegação completa pelo aplicativo usando um controle, com vibração opcional.

### Atualizações e novidades

- Aviso de atualização disponível por jogo, quando a instalação é realizada através de repacks (🏴‍☠️👀), a partir de um feed de atualizações, com brilho
  dourado na capa e link para a página da atualização. O aviso é configurado por jogo.
- Página "Novidades" com as publicações recentes do mesmo feed, e indicador quando há algo novo.
- O próprio aplicativo verifica se há uma versão nova ao abrir, mostra o que mudou e, com a sua
  confirmação, baixa, confere e instala a atualização, reabrindo em seguida. Durante uma sessão de
  jogo, a pergunta espera a sessão terminar.

### Backup

- Exporta um arquivo `.zip` com a biblioteca inteira e todas as configurações: jogos, capas,
  logos, papéis de parede, cores e dispositivos da iluminação inteligente, histórico de sessões e
  Jogos Zerados.
- Restaurar um backup reinicia o aplicativo e devolve a biblioteca e as configurações como
  estavam na exportação. Se algo falhar, os dados atuais são mantidos.
- Jogos restaurados cujo atalho não é encontrado neste computador aparecem na janela "Jogos sem
  atalho", onde é possível escolher o atalho, excluir o jogo ou decidir mais tarde. Quando o
  atalho escolhido já tem histórico neste computador, é possível manter o do backup, manter o
  deste computador ou mesclar os dois.
- A conta da Tuya vai no backup, mas só é lida no mesmo computador e na mesma conta do Windows;
  em outro, o assistente da iluminação inteligente pede os códigos novamente.

#### Saves dos jogos

- Ao fim de cada sessão, o aplicativo faz o backup dos saves do jogo, guardando as 5 versões mais
  recentes de cada um. Também entram os saves e os arquivos de conquistas dos emuladores. Esse backup
  depende da opção "Contar horas de jogo".
- As cópias dos saves ficam em uma pasta dentro da pasta do aplicativo, que pode ser trocada em
  Preferências, por exemplo, para uma pasta do OneDrive. Ao trocar, só as cópias dos saves mudam de
  lugar; o restante da pasta não é alterado.
- "Restaurar save", no menu do jogo, permite escolher a versão a devolver. Em Preferências, a opção
  "Restaurar saves de todos os jogos" devolve a versão mais recente de cada um.
- O backup `.zip` da biblioteca também leva as cópias dos saves. Se a pasta dos saves escolhida não
  for encontrada, ou se não tiver nenhuma cópia de save, o `.zip` é gerado sem elas e o aplicativo
  avisa. Ao restaurá-lo, elas voltam para a pasta padrão; um backup sem saves mantém as cópias
  atuais. Para devolver os saves aos jogos (por exemplo, depois de formatar o computador), use
  "Restaurar saves de todos os jogos".

### Integração com o Windows

- Tema claro e escuro e cor de destaque acompanham as configurações do Windows na hora.
- A janela reabre no monitor, na posição e no tamanho em que foi fechada.
- Abrir o aplicativo com ele já aberto traz a janela existente para a frente.
- As animações respeitam a opção de desativar animações do Windows.

## Diferenças em relação ao Cartridges original

- Somente Windows. As fontes de importação do Linux (Steam local, Lutris, Heroic, Bottles, itch,
  Flatpak e outras) deram lugar à importação de uma pasta de atalhos.
- Interface somente em português do Brasil.
- Removidos: atalhos de teclado, ocultar jogos e os links do projeto original na tela Sobre.
- Todas as outras funções que foram detalhadas acima.

## Instalação

1. Baixe e instale através do instalador `Cartridges.Windows.exe` da versão mais recente em
   [Releases](https://github.com/joaomgabaldi/Cartridges/releases).

O instalador pede permissão de administrador e instala para todos os usuários. Depois de instalado,
o aplicativo se atualiza sozinho.

**Placa de vídeo NVIDIA:** no modo padrão, o driver da NVIDIA desenha uma moldura preta em volta da
janela. O instalador evita isso sozinho: grava no driver um perfil "Cartridges" com o *método de
apresentação Vulkan/OpenGL* em *Preferir nativo*. Se não conseguir, ele mostra no fim da
instalação o passo a passo para fazer o ajuste no Painel de Controle NVIDIA. A desinstalação
remove o perfil.

Ao desinstalar, o instalador pergunta se deve remover também a biblioteca e as configurações.

## Compilação

A build é feita no [MSYS2](https://www.msys2.org), ambiente UCRT64, instalado em
`C:\msys64` (o caminho que o `build-installer.bat` espera; fora de `Program Files`, que exige
administrador para gravar). Os comandos abaixo rodam no terminal UCRT64.

### Dependências

No shell UCRT64 (GTK 4.24 e libadwaita 1.10 ou mais recente):

```bash
pacman -S mingw-w64-ucrt-x86_64-gtk4 mingw-w64-ucrt-x86_64-libadwaita \
  mingw-w64-ucrt-x86_64-python mingw-w64-ucrt-x86_64-python-gobject \
  mingw-w64-ucrt-x86_64-python-requests mingw-w64-ucrt-x86_64-python-pillow \
  mingw-w64-ucrt-x86_64-python-cryptography mingw-w64-ucrt-x86_64-python-pip \
  mingw-w64-ucrt-x86_64-ffmpeg mingw-w64-ucrt-x86_64-meson mingw-w64-ucrt-x86_64-ninja \
  mingw-w64-ucrt-x86_64-gcc mingw-w64-ucrt-x86_64-binutils
/ucrt64/bin/python.exe -m pip install --break-system-packages tinytuya
```

O `blueprint-compiler` é baixado pelo Meson na primeira configuração.

O `tinytuya` conversa com a iluminação inteligente, e o `python-cryptography` é necessário para ele.
O `ffmpeg` converte o vídeo escolhido como capa e vai junto no instalador.
Para gerar o instalador, também é preciso o [Inno Setup 6](https://jrsoftware.org/isinfo.php).

O aplicativo depende de uma correção no GTK que ainda não está no projeto oficial. Sem ela, a
janela é desenhada pela metade em monitores maiores que o principal. A correção e o procedimento
para instalá-la estão em [`build-aux/windows/gtk-patches`](build-aux/windows/gtk-patches/README.md).

### Instalador

O instalador oficial é gerado pelo workflow **Gerar instalador (beta)** do GitHub Actions, que o
publica como pré-release. Depois de testada, a pré-release é promovida a versão final.

Para gerar um instalador local de teste, execute `build-installer.bat`. Ele confere o GTK
corrigido, compila o aplicativo, empacota com o Inno Setup e grava o instalador em `_dist`.

### Build manual

```bash
export PATH="/ucrt64/bin:$PATH" PYTHONUTF8=1
meson setup _build
ninja -C _build
```

O `PYTHONUTF8=1` é necessário porque, sem ele, o compilador dos arquivos `.blp` os lê na
codificação do Windows e falha.

### Testes

```bash
/ucrt64/bin/python.exe -m pytest
```

Os testes usam o GTK real do MSYS2, e não o Python do sistema.

## Histórico de versões

A lista completa de mudanças de cada versão aparece no aplicativo, em *Sobre o Cartridges →
Novidades*, e está em [`data/io.github.joaomgabaldi.Cartridges.metainfo.xml.in`](data/io.github.joaomgabaldi.Cartridges.metainfo.xml.in).

## Créditos e licença

O Cartridges foi criado por kramo e pelos colaboradores do
[projeto original](https://codeberg.org/kramo/cartridges). Esta versão para Windows é mantida por
joaomgabaldi.

Distribuído sob a licença [GPL-3.0-or-later](LICENSE).
