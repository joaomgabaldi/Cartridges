# Cartridges — auditoria de código de 18/09/2026

**Escopo:** todo o código da aplicação (`cartridges/`, 80 arquivos, ~24 mil linhas), os `.blp` de
`data/gtk/`, gschema, metainfo, gresource e a infraestrutura de build (meson, Inno Setup,
`build-installer.ps1`). Fora do escopo: `subprojects/blueprint-compiler` (vendorizado) e os testes
como alvo (usados como evidência).
**Método:** seis varreduras paralelas por subsistema, cada arquivo lido por inteiro; todo achado
re-verificado contra o código antes de entrar aqui; os incertos medidos no runtime real (MSYS2
ucrt64, Python 3.14, GTK 4.22, Adw 1.9). Suíte completa executada; endpoint da Steam testado ao vivo.
**Contexto:** a auditoria de 26/08 fechou os 29 achados (ver `fechamento-auditoria-2026-08-26.md`).
Desde então entraram ~70 commits: sessão multimonitor e papel de parede, atualizador do próprio app,
fitas de LED Tuya (com fade e cor fora do jogo). Esta auditoria cobre tudo de novo, com atenção a
esse código novo.

## Resumo

**55 achados: 3 altos, 14 médios, 31 baixos, 7 de higiene.** Nenhuma vulnerabilidade explorável
remotamente. O atualizador está sólido (SHA256 conferido antes do rename, token não vaza no
redirecionamento, versão validada antes de virar nome de arquivo). O peso está em três lugares:

1. **Escolhas do usuário perdidas em silêncio.** Comando editado à mão, capa `.webp` escolhida, cor
   da fita e estado de antes das fitas.
2. **Sessão de jogo.** O bloqueador só barra o mouse. A queda para a janela manual desfaz e refaz a
   sessão com o jogo rodando. O histórico não recebe a sessão fechada pelo app. A suspensão do PC
   vira tempo de jogo.
3. **Arestas das fitas.** Os caminhos de arranque, suspensão e fechamento podem deixar uma fita na
   cor do app para sempre.

**Suíte:** verde no runtime real, com **830 testes + 3.241 subtests** (1 skip ambiental: symlink
exige privilégio). Os testes chamam `_fetch_metadata_done` e disparam uma busca **de verdade** no
HowLongToBeat, que loga erro depois do fim da suíte (H1).

**Prioridade sugerida:**

1. A1–A3: são os que desfazem escolhas do usuário. A2 é uma linha.
2. M1 + M2: teclado atrás do bloqueador e atalhos globais. Mesma causa, mesmo conserto de
   sensibilidade.
3. M4 + M5: sessão na queda para a janela manual e no fechamento.
4. M8–M10: reset e JSON editado à mão.
5. O resto é oportunista.

---

## Severidade alta

### A1 — Drive do jogo desligado no import troca o id e a adoção joga fora o comando editado

`cartridges/importer/shortcuts_source.py:435-443` vs `:495-503` + `cartridges/store/store.py` (`adopt_legacy_game`)

O caso: atalho em C:\ e jogo em D:\ (HD externo), com o HD desligado no auto-import da
inicialização.

- `Path(target).is_file()` falha, e o `.lnk` cai no ramo de URI: identidade `target` sem `|args` e
  comando sem `/D` e sem argumentos.
- O id muda. A âncora adota o registro antigo e troca `legacy.executable` pelo comando pobre. O
  comando que o usuário tinha editado nos detalhes se perde.
- Quando o drive volta, o id muda de novo e há outra adoção. O comando volta a ser o gerado pelo
  scan, e a edição continua perdida.

Provado no harness com o mesmo `.lnk` antes e depois de apagar o exe:

- `shortcuts_095df3fc…` com `start "" /D "…" "…/game.exe" -dx11`
- `shortcuts_da8768bc…` com `start "" "…/game.exe"`

**Conserto:** alvo com cara de caminho absoluto (`X:\` ou `\\`) mantém a identidade `target|args` e
o comando clássico mesmo com o arquivo ausente. Só alvo com esquema (`xxx://`) é URI. Vale também
não sobrescrever `executable` na adoção quando o registro tem edição do usuário.

### A2 — "Atualizar capas" sobrescreve capa animada `.webp` escolhida à mão

`cartridges/utils/steamgriddb.py:239-246`

O teste de "já tem capa" olha só `.tiff` e `.gif`. Um jogo com capa `.webp` animada (do seletor ou
de arquivo próprio; `save_cover` guarda WEBP animado como `.webp`) passa por jogo sem capa, mesmo
com "preferir SGDB" desligado. O SGDB baixa uma capa, e `save_cover` grava `.tiff`/`.gif` e **apaga
o `.webp`**.

**Conserto de uma linha:** testar `(*ANIMATED_SUFFIXES, ".tiff")` ou usar `game.get_cover_path()`.

### A3 — Fitas ficam na cor do app para sempre por quatro caminhos

`cartridges/utils/session_fita.py`, chamada por `cartridges/preferences.py:478-497, 558-567`

A chave `fita-estado-anterior` guarda o estado das fitas de antes do app, e é o que o fechamento
devolve. Quatro caminhos a perdem ou a deixam incompleta:

1. **Re-arranque com o app aberto (confirmado no runtime).** Fechar o assistente, mesmo pelo X, ou
   religar o interruptor chama `abrir()` de novo. O `restaurar_orfaos()` trata a chave da execução
   atual como órfã:
   - devolve as fitas ao estado de antes, e elas piscam apagadas;
   - limpa a chave e repinta de roxo.
   - Se uma fita não responder à releitura, ela sai da chave nova e nunca mais é devolvida. Provado
     com as fitas falsas de `tests/test_session_fita.py`: eb1 muda no re-arranque deixou a chave só
     com `{'eb0': …}`.
2. **Fita suspensa no fechamento** (`:412-413`, `:1069-1085`). Um roteador que reinicia no meio do
   jogo soma falhas e suspende a fita, e só o "Testar" chama `retomar()`. No fechamento, `_devolver`
   pula a fita suspensa sem tentar e **limpa a chave mesmo assim**.
3. **Fita que não respondeu à leitura do arranque** (`:999-1026`). `_estado_de_todas` deixa essa fita
   de fora, mas `_vestir` logo em seguida pinta todas. Se ela responder ao vestir, fica roxa sem
   estado a devolver. Se todas falharem, a chave vira `"{}"`, que não é vazia, e bloqueia uma nova
   gravação.
4. **Fechamento logo depois de abrir** (`:1100-1115`, `:1152-1171`). `_devolver` e `_vestir` do
   arranque disputam a geração de cada fita. Se o vestir vencer, a fita fica roxa e a chave é limpa.
   Plausível, com janela estreita.

**Conserto:**

- Separar "desfazer órfão" (só no arranque do app) de "reacender" (o que as Preferências chamam: só
  `_vestir(cor_do_app())`).
- `retomar()` no começo do `_devolver` do fechamento, limitado pelo `PRAZO_FECHAMENTO`.
- No arranque, pintar só as fitas cujo estado foi lido e gravado, e não gravar `"{}"`.
- `_devolver` do fechamento pega `_TRAVA_ARRANQUE` com timeout.

---

## Severidade média

### M1 — O bloqueador de sessão só barra o mouse; teclado e atalhos agem por trás dele

`cartridges/window.py:482-523`, `cartridges/game.py:395, 409-414`

O jogo é iniciado pelo "Jogar" dos detalhes, que fica com o foco. Com "mudar de monitor" ligado, a
janela fica visível no outro monitor. Clicar nela e apertar Enter ou Espaço ativa o "Jogar"
escondido (provado com PostMessage):

- `move_to_session_monitor` sobrescreve `_before_session` com a posição já estacionada;
- a sessão anterior é fechada sem relógio;
- no fim, a janela fica no monitor do jogo, e `save_window_geometry` grava esse lugar.

Delete remove o jogo que está rodando, e Ctrl+N, Ctrl+I e Ctrl+vírgula funcionam. O próprio
`gamepad.py:427-431` reconhece o furo ("overlay stops clicks, but not focus traversal") e protege
só o controle.

**Conserto:** `navigation_view.set_sensitive(False)` e foco no `session_blocker_button` em
`show_session_blocker`; desfazer no `hide`.

### M2 — Delete e Ctrl+Z globais roubam a tecla das caixas de busca

`cartridges/main.py:466, 477, 783-785`; `data/gtk/window.blp:171, 339`

`remove_game_details_view` (Delete) e `undo` (Ctrl+Z) são atalhos do app e ficam sempre habilitados.

- Com o cursor na busca, Delete dispara a ação (que não faz nada fora dos detalhes), consome a tecla
  e não apaga o caractere. Provado: com a ação desabilitada, "abc" virou "bc".
- Ctrl+Z na busca não desfaz a digitação: reverte uma ocultação, uma remoção ou uma importação (M3).

**Conserto:** habilitar `remove_game_details_view` só com os detalhes visíveis, no mesmo handler de
`pushed`/`popped` que já existe.

### M3 — Ctrl+Z desfaz uma importação de horas atrás em vez da última ação

`cartridges/window.py:1911-1916`; `cartridges/importer/importer.py:170, 405-421`

`imported_game_ids` fica preenchido até a próxima importação. O auto-import da abertura traz 3
jogos. Horas depois, o usuário remove o jogo X e aperta Ctrl+Z. `on_undo_action` testa primeiro os
importados: **marca os 3 como removidos**, e X continua removido. Isso viola a regra de
`game.py:347-348` ("Ctrl+Z can't undo actions whose toast is long gone").

**Conserto:** zerar `imported_game_ids`/`removed_game_ids` no "dismissed" do toast de resumo.

### M4 — A queda para a janela manual desfaz e refaz a sessão com o jogo rodando

`cartridges/process_session.py:321-330`; `cartridges/window.py:525-555` (achado por duas varreduras)

Jogo rastreado por pasta ou exe cujo processo nunca aparece (inicializador com outro nome): depois de
300 s, `stop(fall_back=True)` chama `hide_session_blocker()` inteiro.

- `restore_from_monitor` usa `SetWindowPlacement(SW_SHOWNORMAL)`, que mostra e ativa a janela no
  monitor principal, por cima do jogo.
- O papel de parede é devolvido e as fitas deslizam para o roxo. Logo depois, `SessionWindow`
  chama `show_session_blocker` e veste tudo de novo, e as telas e as fitas piscam.
- O relógio some, porque `session_geometry()` passa a ser `None`.
- O comentário da linha 327 ("the main window was minimised on launch") é falso quando a janela foi
  estacionada.

**Conserto:** no `fall_back`, trocar só o rastreador. Não chamar `hide_session_blocker`, e fazer o
`show_session_blocker` pular a parede, as fitas, o monitor e o controle quando `session_game is game`.

### M5 — Fechar o app no meio da sessão soma o tempo, mas não grava a sessão no histórico

`cartridges/main.py:584-587`; `process_session.py:286-294`; `session_window.py:86-96` (achado por duas varreduras)

`do_shutdown` chama só `flush()`, que soma a `playtime` e salva; nunca chama `session_log.record`.
Depois de 2 h de jogo e Ctrl+Q:

- o total fica 2 h acima da soma das sessões;
- "Últimos 7/30 dias" sai subcontado;
- a diferença não pode ser apagada pela tela.

Isso contradiz a premissa de `window.py:848` ("O total é a soma das sessões").

**Conserto:** depois de cada `flush()`, `session_log.record(game_id, session_seconds)` (em
`ProcessSession`, só se `started`).

### M6 — Suspensão do PC com o jogo aberto vira tempo de jogo

`cartridges/process_session.py:258-277`; `session_window.py:86-97`

No runtime, `time.monotonic()` é `QueryPerformanceCounter`, que conta o tempo dormido. Um jogo
pausado com o PC dormindo a noite toda: o primeiro poll ao acordar ainda vê o processo e credita as
8 h. A docstring promete o contrário. Plausível: a base é a documentação do relógio, sem teste de
suspensão.

**Conserto:** no `_poll`, se `now - last_tick` passar muito do `POLL_INTERVAL` (mais de 30 s),
creditar só um intervalo.

### M7 — Pasta de editora vigiada como se fosse de um jogo só

`cartridges/utils/process_monitor.py:394-405, 435-466`

`_game_root` sobe até o pai ser um contêiner conhecido, e pastas de editora não estão na lista.
Provado no runtime:

- `…\Epic Games\GTAV\PlayGTAV.exe` devolve `C:\Program Files\Epic Games`
- `…\EA Games\Battlefield 6\SP\bf6.exe` devolve `…\EA Games`
- `…\Rockstar Games\Red Dead Redemption 2\RDR2.exe` devolve `…\Rockstar Games`

Na Rockstar, o Launcher e o Social Club moram em `…\Rockstar Games\Launcher` e `\Social Club` e
ficam na bandeja depois do jogo: a sessão não termina e o tempo infla por horas.

**Conserto:** parar a subida no primeiro nível abaixo de `Program Files` / `Program Files (x86)`
(melhor que crescer `_CONTAINER_DIRS`).

### M8 — Reset com "Atualizar capas" em voo traz jogos apagados de volta, na grade e no disco

`cartridges/preferences.py:816-819`; `store/managers/sgdb_manager.py:64`

O reset cancela o cancellable e o substitui na hora, e o `SgdbManager.main` lê o atributo atual.
Resultado:

- as tarefas já na fila veem "não cancelado" e gravam capas depois da limpeza;
- o callback do lote roda `game.update()` nos `Game` apagados, e a grade volta a mostrá-los (provado
  com `DisplayManager` real: de 0 para 1 filho, com `store.get(id) is None`);
- clicar no fantasma chama `launch()` e depois `save()`, e o JSON volta ao disco.

**Conserto:** `game.update()` só se `shared.store.get(game.game_id) is game`; o manager captura o
cancellable no `process_game`.

### M9 — "Remover todos os jogos" deixa as paredes e as cores de fita, que voltam na reimportação

`cartridges/preferences.py:842-853`; `store.py:287-299` (`cleanup_game`) (achado por duas varreduras)

A limpeza apaga `games`, `covers` e `logos`, mas não `wallpapers\` (imagens de vários MB mais os
sidecars) nem `fitas\`. Os ids são estáveis (`imported_1`, hash do atalho), então os jogos
reimportados herdam o papel de parede e a cor travados do jogo antigo. `cleanup_game` também não
limpa esses dois sidecars.

**Conserto:** incluir `wallpapers_dir` (menos `cache`, se ele deve sobreviver) e `fitas_dir`; o
`fitas.json`, que é configuração, fica.

### M10 — JSON editado à mão com tipo errado impede a janela de abrir ou quebra telas

`cartridges/main.py:207-239, 653-660`; `store/store.py:52, 568`; `window.py:68, 977-982, 1360`

`sanitize_numeric_fields` pula `None` e só cobre números. Provado com `Game` real:

- `"version": null` leva a `None > 1.6` e a `TypeError` em `add_game`.
- `"shortcut_path": 5` leva a `AttributeError` em `_path_key`.
- Essas duas escapam de `load_games_from_disk` antes do `present()`: **a janela não abre**.
- `"shortcut_mtime": null` carrega, mas estoura na próxima importação.
- `"removed": "false"` conta como verdadeiro, e o jogo some.
- `"notes": 5` quebra `show_details_page`.
- `"developer": 1` quebra `filter_func` a cada tecla.
- `"hltb_chapters": "x"` quebra os capítulos.

`docs/game_id.json.md` convida a editar à mão.

**Conserto:** validar texto, bool e lista como já se faz com os números (tratando `None` como
inválido), e um try por arquivo no `add_game` da carga.

### M11 — Todo `.lnk` com aspas nos argumentos é descartado (GOG Galaxy, Battle.net, emuladores)

`cartridges/importer/shortcuts_source.py:55, 74-88, 431-433`

`args_safe` chama `cmd_safe`, que recusa qualquer `"`, incluindo o exemplo legítimo da própria
docstring (`"C:\\saves\\a.sav"`). Parênteses também são recusados, mesmo dentro de aspas
(`Program Files (x86)`, `Game (USA).sfc`). Atalhos descartados em silêncio:

- GOG (`/path="D:\GOG Games\X"`)
- Battle.net (`--exec="launch Pro"`)
- RetroArch (`-L "cores\x.dll" "…(USA).sfc"`)

Provado no harness real: o atalho do GOG dá `[]`.

**Conserto (com cuidado, é fronteira de segurança):** percorrer o texto acompanhando as aspas:

- aspas balanceadas: aceitas;
- `&|<>^()`: aceitos só dentro de aspas;
- `%`: recusado sempre, porque expande mesmo entre aspas;
- aspas desbalanceadas e caracteres de controle: recusados.

Testes de injeção antes do merge.

### M12 — O fallback pela lista de apps da Steam está morto: `GetAppList` não existe mais

`cartridges/utils/steam_applist.py:50, 131-142`; chamado de `steam.py:302-313`

`ISteamApps/GetAppList/v2/` responde **404** (verificado ao vivo hoje; `v1` e `v0002` também).
Consequências:

- toda busca sem confiança pela loja tenta baixar a lista e cai no backoff de 60/300/900 s;
- os jogos que saíram da loja (o motivo do módulo) nunca são achados;
- os testes usam cache falso e não pegam isso.

O substituto `IStoreService/GetAppList` exige chave.

**Decisão:** migrar para `IStoreService` com chave da Steam Web API (paginado), ou remover o
fallback e o módulo.

### M13 — Adoção de jogo não leva a cor de fita escolhida à mão

`cartridges/store/store.py:94-179` (`_migrate_game_files`) (achado por duas varreduras)

A migração move o registro, a capa, o logo e a parede, mas não `fitas_dir/<id>.json`. A docstring
ainda fala em "quatro conjuntos". Provado: `salvar_cor(OLD)` seguido de `adopt_legacy_game(NEW,
[OLD])` dá `escolhida(NEW) == False`. A cor volta à da capa e o arquivo antigo fica órfão.

**Conserto:** mais uma tupla em `moves`, com teste irmão do T1.12.

### M14 — Desligar "Contar horas de jogo" trava a configuração das fitas, que seguem funcionando

`data/gtk/preferences.blp:90-97` vs `cartridges/main.py:400`, `session_fita.ligada()`

`sensitive: bind playtime_tracking_switch.active` está na **página** Personalização inteira, que
contém o grupo das fitas. Com a contagem de horas desligada:

- as fitas continuam acendendo no arranque e sendo devolvidas no fechamento;
- não dá para desligá-las, trocar a cor, testar ou rodar o assistente.

O comentário do `.blp` é de antes das fitas.

**Conserto:** pôr o `sensitive` só nos grupos de monitor e papel de parede.

---

## Severidade baixa

### Sessão, atualizador e fitas

- **B1 — O atualizador pode fechar o app no meio de uma sessão.** `app_updater.py:315-344, 383-407`.
  A caixa chega segundos depois do `present()`, e quem já clicou em Jogar responde Sim com o jogo
  aberto. `_finish` chama `quit()`, e o app reaberto não volta a rastrear o jogo. **Conserto:**
  `_ask` adia ou descarta a pergunta se houver `SessionWindow.active`/`ProcessSession.active`.
- **B2 — Corrida `comecar`×`voltar` das fitas em sessão curta.** `session_fita.py:1123-1139`. A
  cor do jogo é calculada na thread antes de reservar a geração. Um "Já terminei" rápido perde para
  ela, e as fitas ficam na cor do jogo sem jogo. Plausível. **Conserto:** reservar a geração na
  thread de UI.
- **B3 — O batimento pode ressuscitar uma conexão descartada.** `session_fita.py:439, 475-500`.
  `_descartar` roda fora da trava, e a tinytuya reabre o soquete de um objeto fechado
  (`_get_socket(False)`). Sobra uma conexão que ninguém fecha. Plausível. **Conserto:** reconferir
  `_conexoes.get(id) is modulo` já com a trava.
- **B4 — Módulos Tuya 3.4/3.5 nunca funcionam.** `fita_wizard.py:80`, `session_fita.py:668,
  816-823`. Toda fita é gravada como "3.3", e a versão que a varredura descobre é jogada fora.
  `ler_estado` aceita só `cmd == 10` (a 3.4+ usa 16). O hardware atual é 3.3; afeta fita nova.
- **B5 — Papel de parede com Windows Spotlight vira imagem fixa.** `session_wallpaper.py:219-231`.
  Só a apresentação de slides é detectada. Plausível.
- **B6 — O Restart Manager pode matar o app no meio do fechamento das fitas.** `app_updater.py:62`
  (`/FORCECLOSEAPPLICATIONS`) com `session_fita.fechar()` (até 8 s sem atender mensagens). O dano é
  limitado: a chave órfã é desfeita na reabertura. Repetir o teste de ponta a ponta com as fitas
  ligadas.

### Integridade de dados e arquivos

- **B7 — Escritas de JSON sem tmp+replace.** Viola o padrão obrigatório em três lugares:
  - sidecar do papel de parede (`session_wallpaper.py:423-441`, com `mkdir` fora do `try`);
  - sidecar do logo (`game_logo.py:214-218`: com a escolha manual perdida, a busca automática pode
    apagar o logo do usuário);
  - backup exportado (`preferences.py:904-912`).
- **B8 — Restaurar backup.** `preferences.py:71-88, 946-952`.
  - `Infinity` no JSON dá `OverflowError`, que escapa no meio da restauração, com parte já somada.
  - Jogos removidos (lápides) recebem o tempo e entram na contagem "N restaurados".
- **B9 — `DecompressionBombError` sem tratamento em dois lugares.**
  - `save_cover.py:108-131`: o fallback via Gdk chama `convert_cover` de novo, que recusa de novo, e
    a recursão não tem fim, com um TIFF enorme em %TEMP% a cada nível.
  - `wallpaper_picker.py:393-418`: o spinner fica eterno, porque a exceção não herda de `OSError`.
- **B10 — Temporários de logo e de capa do SGDB vazam em %TEMP%.** `logo_picker.py:316-318` (o
  fluxo do `new_tmp` nem é fechado); `details_dialog.py:901-903, 931-950`. É o mesmo vazamento
  do M7 de 26/08, agora em caminhos vizinhos. **Conserto:** `_logo_tmp`/`_cover_tmp`, como
  `_wallpaper_tmp`.
- **B11 — Sweeps reiniciados no reset continuam trabalhando.** `preferences.py:806-810`;
  `hltb_backfill.py:75-89`; `install_size.py:198-209`. O `start()` logo depois do `stop()` desfaz o
  `_stopped`, e o worker antigo segue fazendo centenas de buscas no HLTB para uma biblioteca apagada.
  **Conserto:** contador de geração.
- **B12 — `HLTBBackfill._apply` não reconfere "só o que falta".** `hltb_backfill.py:185-201`. Um
  resultado tardio sobrescreve a correção feita pelo botão dos detalhes. Plausível.
- **B13 — Troca de capa animada durante a decodificação.** `save_cover.py:157-162`;
  `game_cover.py:184-199`.
  - O `replace` sobre um GIF aberto pela Pillow dá `WinError 5` (provado), e o `apply_preferences`
    aborta sem salvar.
  - `_frames_decoded` compara só o caminho, então pode instalar os quadros da capa antiga.
- **B14 — Depois da adoção, `GameCover.path` aponta para o arquivo antigo.** `store.py:550-557`.
  O desfoque cai no placeholder, e a animação some até reiniciar.
- **B15 — Sidecar de cor da fita com tipo errado derruba os detalhes.**
  `session_fita.py:202-208`. `"matiz": null` faz `int()` levantar na main thread.
- **B16 — Tamanho de instalação antigo fica depois que o jogo sai do disco.**
  `install_size.py:276-287`. O `continue` não zera o tamanho, e o "o que apagar" põe no topo um
  jogo que já não ocupa nada.
- **B17 — `session_log.delete` quebra com byte que não é UTF-8.** `session_log.py:124-128`. O
  `load` usa `errors="replace"`, e o `delete` não.

### Importadores e metadados

- **B18 — "Executar como administrador" parte comandos com duas aspas.** `run_executable.py:75`. O
  caminho elevado passa `"/c " + cmd` sem as aspas externas que o `shell=True` põe. Provado com
  `"…\Dir (x86)\x.exe" -cfg "…"`. **Conserto:** `'/c "' + executable + '"'`.
- **B19 — `rglob` dos atalhos segue junções NTFS.** `shortcuts_source.py:277-282`. Uma junção em
  laço repete cada `.lnk` cerca de 64 vezes (provado). Deve pular `is_junction()`, como
  `folder_size` já faz.
- **B20 — `_squash` da lista de apps ainda é só ASCII.** `steam_applist.py:74-83`. Um título CJK
  tem âncora vazia e ranqueia a lista inteira (1,6 s por busca). Hoje neutralizado pelo M12.
  **Conserto:** `[\W_]+`.
- **B21 — Formato inesperado escapa do contrato.** `steam_applist.py:140` (`applist: null` dá
  `AttributeError`) e `steam.py:320` (`id: null` dá `TypeError`). A thread morre e o spinner fica
  eterno.
- **B22 — A capa automática do SGDB pega o primeiro resultado.** `steamgriddb.py:116-126`. O
  "match exato" compara o nome já limpo com o nome cru, então "Alien: Isolation" nunca casa.
  **Conserto:** `best_candidate` + `confident`. Plausível.
- **B23 — `.url` em ANSI (cp1252) é descartado.** `shortcuts_source.py:355-357`. Se o jogo já
  estava na biblioteca, `remove_games` o marca como removido. Plausível.
- **B24 — O filtro "não-jogo" derruba títulos reais.** `shortcuts_source.py:91-95`. `\bmanual\b`
  pega "Manual Samuel", e `support`/`benchmark` também pegam títulos legítimos.

### Corpos HTTP e interface

- **B25 — Corpos HTTP sem teto de bytes (viola o padrão).**
  - download do instalador (`app_updater.py:239-247`: o `release.size` existe mas só serve à barra);
  - wallhaven (`wallhaven.py:145-149`);
  - Steam (`steam.py:247, 399, 604, 658`, `steam_applist.py:136`);
  - SGDB (`steamgriddb.py:69, 85`).

  **Conserto:** mover o `_read_capped` do HLTB para `utils/download.py` e reusar.
- **B26 — "Novidades atualizadas" aparece quando a busca falhou.** `news_checker.py:187-191`. Sem
  rede e com cache, `poll-finished(bool(self._posts))` emite True (provado).
- **B27 — `relative_date` erra na virada do mês e do ano.** `relative_date.py:73-80`.
  - Em 18/09, 31/08 sai como "Este mês" (`<=` deveria ser `<`).
  - 31/12/2024 sai como "Ano passado".
  - Os 30 dias fixos erram o mês anterior de verdade.

  **Conserto:** comparar por (ano, mês).
- **B28 — Busca que termina depois de fechar os detalhes abre o seletor ou o alerta numa janela
  solta.** `details_dialog.py:1245-1275`; `preferences.py:244-246`. `present()` num diálogo fechado
  cria um `GtkWindow` próprio (provado). **Conserto:** `_closed` e saída cedo.
- **B29 — Depois do seletor da Steam, o HLTB corre sem spinner e com o botão clicável.**
  `details_dialog.py:1258-1262`.

### Build e instalação

- **B30 — `build-installer.ps1` promete atualizar a trava da libgtk sozinho, mas nada a grava.**
  `:46-57`. Quem segue a mensagem cai no mesmo erro. O README diz o contrário.
- **B31 — Desinstalar em modo "todos os usuários" com UAC de outra conta apaga os dados do
  admin.** `Cartridges.iss.in:210-213`. `{localappdata}`/HKCU seguem o elevado. No mínimo,
  documentar.

---

## Higiene

- **H1 — A suíte faz rede de verdade.** `tests/test_ui_logic.py:535, 709, 726` chamam
  `_fetch_metadata_done`, que dispara `_fetch_hltb_thread` real. O erro "Could not fetch
  HowLongToBeat times" aparece depois do fim da suíte. **Conserto:** monkeypatch de `fetch_times`
  (ou de `threading.Thread`) nesses testes.
- **H2 — Arquivos velhos entram no instalador e nunca saem nas atualizações.** O curinga
  `lib\python…\*` do `.iss` empacota `site-packages\cartridges\utils\sqlite.py` (de maio; não existe
  no repo). Sem `[InstallDelete]`, módulo removido fica em `{app}` para sempre. **Conserto:** limpar
  `site-packages\cartridges` antes do `meson install` e/ou `[InstallDelete]`.
- **H3 — `data/gtk/style-dark.css` é código morto.** Fora do gresource; o conteúdo já está em
  `style.css` com `@media (prefers-color-scheme: dark)`.
- **H4 — `meson.build` exige libadwaita ≥ 1.7, mas `Adw.ShortcutsDialog` é 1.8** (conferido no
  `.gir`).
- **H5 — `importer/location.py` é código morto no fork.** A única fonte tem `locations = ()`.
- **H6 — Docs e comentários desatualizados:**
  - spec do atualizador: fala em `browser_download_url`, o código usa `assets[].url`;
  - `docs/game_id.json.md`: faltam `wallpapers\` e `fitas\`, e a regra de tipo errado não vale para
    `null`;
  - `shared.pyi`: falta `details_size`;
  - `session_fita.py:408-410, 460-461`: "a varredura tira da suspensão", o que contradiz a ADR
    0001;
  - `session_fita.py:1019-1022`, `_arrancar` e a spec: "`do_activate` dispara de novo", o que não
    acontece;
  - `fita_wizard.py:55-57`: "broadcast na hora de acender";
  - `preferences.blp:141, 218`: "roxo", quando a cor do app é configurável;
  - `process_session.py:327`: ver M4.
- **H7 — Textos de UI.**
  - "Tente uma busca diferente" aparece quando quem esvaziou a grade foi o filtro do menu
    (`window.blp:4-18`).
  - A confirmação de apagar sessão usa "Dispensar" como cancelar e não marca "Apagar" como
    destrutivo (`session_history.py:173-186`).
  - O seletor de papel de parede aberto com um arquivo mostra "Nenhum papel de parede encontrado"
    numa falha de leitura (`wallpaper-picker.blp:53`).

---

## Verificado e limpo (para não re-flagar)

- **Atualizador:**
  - URL do anexo vem da API autenticada por TLS, e o `requests` tira o `Authorization` no
    redirecionamento ao CDN;
  - anexo sem `digest` é recusado antes de baixar, e o hash é calculado enquanto grava;
  - o `.part` só é renomeado com o hash batendo e é apagado em qualquer exceção, Cancelar incluído;
  - a versão passa por `fullmatch AAAA.MM.DD` antes de virar nome de arquivo;
  - as notas são escapadas;
  - `[Run] postinstall` não herda a elevação;
  - a página da NVIDIA é pulada no modo silencioso.
- **Segredos:**
  - o logger da tinytuya fica em WARNING, inclusive os sub-loggers (provado com `dictConfig`);
  - API Secret, local key e chave do SGDB não aparecem em log;
  - o `getdevices()` da tinytuya 1.20 não devolve o IP público.
- **Fitas:**
  - trava reentrante por fita, com fade e comando final na mesma trava;
  - `_esvaziar` antes de cada conversa;
  - geração por fita interrompe o fade;
  - IP vazio nunca chega à tinytuya;
  - `fechar()` com prazo;
  - `devolver_removidas` no assistente;
  - sem fita configurada, o Aplicar não grava cor;
  - a prévia é desfeita ao fechar.
- **Win32:**
  - protótipos ctypes do `process_monitor` e do `window_geometry`, com `CloseHandle` em `finally`;
  - dois passos de `SetWindowPlacement` nos dois sentidos;
  - janela minimizada não é lida;
  - posição fora de monitor é recusada;
  - vtable do `IDesktopWallpaper` (3-7, 17), `CoTaskMemFree`, `Release`/`CoUninitialize` só quando o
    COM é nosso;
  - mutex `Local\` de instância única.
- **MSYS2:** `_win32_path`/`_win32_dir` em todos os pontos de comparação, conferido empiricamente.
- **Consertos de 26/08 que continuam de pé:**
  - `folder_size` com `is_junction()` (provado);
  - `_keep_user_edits` nos dois ramos do `SteamAPIManager`;
  - guard de identidade no `MetadataRefresh` e no `HLTBBackfill`;
  - `_read_capped` no HLTB;
  - `_dump_json_atomic` no `FileManager`;
  - geometria não grava janela minimizada;
  - `_loading_ops` balanceado com o Enter respeitando a trava;
  - pickers com geração, `_closed` e `_finish_results`.
- **Build:**
  - `meson.build` e metainfo em 2026.09.18, com releases em ordem, datas coerentes e changelog em
    pt-BR;
  - os 10 `.blp` no gresource e no `data/meson.build`;
  - todo `.py` instalado, com `__pycache__` excluído;
  - toda chave de gschema usada existe com o tipo certo.
- **Runtime:** suíte completa verde, com 830 + 3.241 subtests em 50 s.

## Registro de método

Seis passadas por subsistema (Opus), cada uma lendo o escopo por inteiro, com licença para ler
vizinhos:

1. UI principal e ciclo de vida
2. Diálogos e pickers
3. Store e persistência
4. Importadores e metadados
5. Sessões, processos e fitas
6. Rede, logging, gamepad e build

Seis achados apareceram em duas passadas independentes e foram fundidos: M4, M5, M9, M13, B7 e A3.1.
Antes de entrar aqui, cada achado de peso foi re-verificado contra o código:

- A1: harness;
- A2: linha do sufixo;
- A3: `_devolver`, `_estado_de_todas` e `_conversar`;
- M5: `do_shutdown`;
- M11: regex;
- M12: `curl` ao vivo, com 404;
- M13: `moves`;
- M14: `.blp`;
- B1 e B25: `_ask`/`_finish` e o laço do download;
- B9: fallback do `convert_cover`;
- B27: linha 73.

O agente citou o `relative_date` com numeração errada, e a linha foi corrigida na verificação.
Nenhum achado foi descartado. Os scripts de prova dos agentes ficaram no diretório temporário do job.
