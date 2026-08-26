# Cartridges — auditoria de código de 26/08/2026

**Escopo:** todo o código da aplicação (`cartridges/`, 64 arquivos, ~18 mil linhas), mais infraestrutura
de build (meson, Inno Setup, gschema, entry point). Fora do escopo: `subprojects/blueprint-compiler`
(vendorizado, só build) e os testes como alvo de auditoria (foram usados como evidência).
**Método:** seis varreduras paralelas por subsistema, cada arquivo lido linha a linha; todo achado
verificado por segunda leitura independente antes de entrar aqui; os incertos foram medidos no
runtime real (MSYS2 ucrt64, Python 3.14.6, GTK 4.22). Suíte completa executada; HowLongToBeat
testado ao vivo nas duas rotas.
**Contexto:** a auditoria de 01/08 fechou os 38 achados originais (ver
`fechamento-auditoria-2026-08-01.md`). Esta cobre tudo de novo, com atenção ao que entrou nas
releases 2026.08.05 → 2026.08.25 (status, nota, sessões, anotações, tamanho em disco, logo no
histórico, endpoint novo do HLTB).

## Resumo

**29 achados: 3 altos, 10 médios, 14 baixos, 2 de higiene.** Nenhum é crash em fluxo comum nem
vulnerabilidade explorável remotamente — a higiene de segurança herdada da auditoria anterior
segue de pé (timeouts em toda requisição, TLS nunca desabilitado, markup escapado, `shell=True`
blindado por validação a montante, separadores MSYS2 corretos em todos os pontos). O peso está em
**integridade de dados** (edições do usuário revertidas, JSON reescrito sem atomicidade, capas
destruídas antes de copiadas) e em **arestas das features novas** (tamanho em disco seguindo
junções, geometria de janela minimizada, pickers pendurados).

Verificação viva: suíte verde no runtime real — **594 testes + 3.241 subtests passando** (1 skip
legítimo: symlink exige privilégio); HLTB respondendo e parseando nas rotas `/api/search/site` e
`/game/<id>`.

**Prioridade sugerida:** A1–A3 primeiro (A1 e A2 são correções de poucas linhas; A3 é o maior
conserto, mas é o único que desfaz trabalho manual do usuário em silêncio). Depois o bloco de
integridade M1/M2/M6–M8, depois os spinners M9. O resto é oportunista.

---

## Severidade alta

### A1 — Fechar minimizado grava o retângulo icônico; a janela reabre minúscula

`cartridges/utils/window_geometry.py:96-116` + `cartridges/main.py:480-508`

`read()` devolve o que `GetWindowRect` disser, sem checar `IsIconic`. Janela minimizada no Win32
fica estacionada em (-32000,-32000) com ~160×28 — e o app **minimiza a si mesmo** ao lançar um
jogo, então o estado é o fluxo normal, não a exceção. Fechar pela taskbar (`close-request`) ou
sair por Ctrl+Q/menu (`do_shutdown` chama `save_window_geometry` incondicionalmente) grava esse
retângulo: -32000 passa no `usable` (só rejeita `UNSET`) e 160×28 passa como tamanho real.
Na abertura seguinte `_place` até rejeita a posição (nenhum monitor contém -32000), mas
`apply_size` já pediu 160×28 — a janela abre no menor tamanho que o GTK permitir, e a posição
lembrada se perdeu junto. **Conserto:** em `read()`, tratar janela icônica como "não perguntável"
(`IsIconic` → `None`) ou ler `GetWindowPlacement.rcNormalPosition`, que ignora o estado icônico.

### A2 — `folder_size` segue junções NTFS, ao contrário do que promete

`cartridges/utils/install_size.py:141`

O guarda é `entry.is_dir(follow_symlinks=False)`, e o docstring afirma "Links e junções não são
seguidos". No runtime que o app embarca, **junção passa**: `is_dir(follow_symlinks=False)` → True,
`is_symlink()` → False (só symlink verdadeiro é filtrado). Provado empiricamente: pasta de 10 bytes
com uma junção para uma irmã de 1.000 bytes mediu **1.010**. Junção é o tipo de link que se cria
**sem** privilégio (`mklink /J`) e é o jeito clássico de mover metade de um jogo para outro disco —
exatamente o usuário da feature "o que eu apago para liberar espaço" recebe o número dobrado. Pior:
junção apontando para um ancestral re-varre o subtree em ciclo até o caminho estourar o limite do
SO — a varredura de fundo mói o disco por muito tempo e então grava um número absurdo. O teste
existente (`tests/test_install_size.py:83`) usa `os.symlink` e é pulado sem privilégio, então o
caso que o próprio docstring nomeia nunca foi exercitado. **Conserto de uma linha** neste runtime
(Python ≥ 3.12): exigir também `not entry.is_junction()`.

### A3 — "Buscar só o que falta" reverte campos editados à mão

`cartridges/metadata_refresh.py:99-101` + `cartridges/store/managers/steam_api_manager.py`

O modo "só o que falta" filtra **quais jogos** entram na fila (`needs_steam`: alguma lacuna, ou
`steam_checked < STEAM_METADATA_VERSION`), mas o manager aplica o dict **inteiro** de
`parse_app_data` via `game.update_values(...)` — nome, desenvolvedora, publicadora, data e gênero,
presentes ou não. Um jogo renomeado à mão ("Witcher 3") com o gênero vazio entra na fila pela
lacuna e sai com o nome e a desenvolvedora revertidos para os da Steam — em silêncio, e em toda a
biblioteca de uma vez quando `STEAM_METADATA_VERSION` for bumpado (o bump re-enfileira tudo).
É a violação direta da promessa do modo, e o único achado desta lista que **desfaz trabalho manual
do usuário**. **Conserto:** no modo só-o-que-falta, aplicar por campo — só o que estiver vazio no
jogo (a mesma regra que a restauração de backup de 2026.08.24 já implementa para status/nota/anotação).

---

## Severidade média

### M1 — Reset não para os dois sweeps novos; resultado tardio ressuscita jogo apagado

`cartridges/preferences.py:452-515`

`reset_app_data` encerra sessões e cancela o metadata refresh, mas não chama
`hltb_backfill.stop()` nem `install_size_sweep.stop()` (ambos existem — `main.py:537-541` os chama
no shutdown) nem cancela um lote SGDB em voo. Os guards internos dos sweeps checam
`self._stopped or game.removed` — o reset não seta nenhum dos dois nos `Game` já snapshotados. Um
`_apply` que chegue depois do wipe roda `game.save()` (o FileManager continua conectado ao próprio
`Game`, não ao store) e **recria o JSON no disco** e re-adiciona o jogo à grade recém-esvaziada.

### M2 — Enter no campo executável aplica no meio do fetch, driblando a trava de loading

`cartridges/details_dialog.py:292,300` vs `:397`

`begin_loading` só desabilita o **botão** Aplicar; `entry-activated` das linhas executável e
processo chama `apply_preferences` direto, que não consulta `_loading_ops`. Enter durante um
"Buscar" salva o jogo sem os dados ainda em voo (que depois escrevem num diálogo fechado). Com
capa escolhida e conversão em andamento, o apply pula `save_cover` mas o `finish` tardio atualiza o
`GameCover` em memória: a capa **aparece na sessão e some no restart** — nunca foi gravada.

### M3 — "Sobre" lê todos os logs sem nenhum tratamento de erro

`cartridges/main.py:575-589`

`on_about_action` abre cada log (incluindo os `.xz` de sessões anteriores) com UTF-8 estrito e sem
try/except. Um byte mutilado — o caso que a própria rotação documenta **preservar**
(`session_file_handler.py:110-114`) — ou um `.xz` truncado faz o diálogo Sobre falhar toda vez,
até o arquivo sair da rotação (várias execuções). Secundário: o handle vaza quando `read()` levanta,
e até 3×32 MiB são lidos e descomprimidos sincronamente na main thread.

### M4 — Trocar de aviso de biblioteca vazia empilha os dois

`cartridges/window.py:686-717`

`set_library_child` só remove os avisos no ramo `else` (quando há jogos visíveis). Na transição
direta "Nenhum jogo" → "Nenhum jogo encontrado" (biblioteca vazia + busca ativa antes do primeiro
import, e as variantes da grade de ocultos), o aviso novo é adicionado sem remover o anterior —
os dois `AdwStatusPage` ficam sobrepostos com os textos um por cima do outro.

### M5 — Tokenização apaga scripts não-latinos; títulos CJK não resolvem ou casam errado

`cartridges/utils/title_match.py:170,274`

`_NON_ALNUM_RE = [^a-z0-9]+` deleta kana/kanji/cirílico após o casefold. Título sem dígito
("ペルソナ") tokeniza para `[]` → mismatch "empty title" → metadado nunca resolve, em silêncio.
Com dígito é pior: "ペルソナ5" e "ペルソナ5 スクランブル" (jogos **diferentes**) reduzem ambos a
`["5"]` com core `[]`, e o `wanted_core == candidate_core` da linha 274 vem **antes** do guard de
core vazio da 284 → `[] == []` → SCORE_EXACT, adotado sem perguntar (`match.confident`). Rota
real: os aliases japoneses do HLTB (`rank_candidates` sobre `game_alias`). O corpus de fuzz cobre
acentos, nenhum script não-latino.

### M6 — Adoção reescreve JSON do jogo e sidecar do logo sem atomicidade

`cartridges/store/store.py:130-131,148-149`

`_migrate_game_files` regrava o registro adotado (e o sidecar de logo) com `open("w")` +
`json.dump` — truncate e escreve, no lugar. Queda no meio deixa JSON truncado; o loader
(`main.py:559`) pula o arquivo, e playtime, anotações e status daquele jogo somem — o próximo scan
o reimporta zerado. O `FileManager` do mesmo subsistema grava com tmp de uuid + `replace()`
exatamente para fechar essa janela; estes dois escritores ficaram de fora.

### M7 — Toda capa escolhida à mão vaza um TIFF em %TEMP% para sempre

`cartridges/utils/save_cover.py:50-52,86`

O ramo `pixbuf` escreve um TIFF temporário intermediário, e o bloco Pillow em seguida escreve um
**segundo** temporário e devolve só ele — o primeiro nunca é apagado, e o chamador nem o vê.
O ramo de fallback do mesmo arquivo tem o cleanup com um comentário descrevendo exatamente esse
problema (linhas 107-115); o ramo pixbuf ficou sem. Confirmado empiricamente: uma chamada, dois
temporários, um órfão. ~0,5–2 MB por capa escolhida no diálogo de edição, e o Windows não limpa
%TEMP% sozinho.

### M8 — Troca de capa destrói as antigas antes de copiar a nova

`cartridges/utils/save_cover.py:124-136`

`save_cover` primeiro apaga as três formas possíveis da capa existente e então `copyfile` sem
tmp + rename. Disco cheio ou queda no meio deixa a capa ausente ou truncada — e truncada passa no
`still.is_file()` do `conditionaly_update_cover`, então o SGDB considera "tem capa" e **nunca
re-busca**: arte quebrada até troca manual. Copiar para um tmp no próprio diretório de capas e
`replace()` fecha as duas janelas.

### M9 — Pickers penduram no spinner quando a thread de busca morre ou nada materializa

três gatilhos da mesma família:

- `cartridges/logo_picker.py:159-177` — se **toda** pré-visualização falhar (API do SGDB ok, CDN
  de imagens fora — split real; até 24 downloads seriais de 15 s), o loop termina sem chamar
  `_show_empty` nem `_add_result`: o stack fica em "loading" pela vida do diálogo.
- `cartridges/utils/steamgriddb.py:95,120,147,169,186` + `cartridges/logo_picker.py:139` — um 200
  com JSON válido de shape inesperado (`{"success":false}` de um proxy) faz `res.json()["data"]` /
  `games[0]["id"]` levantar `KeyError`, que nenhum `except (SgdbError, RequestException)` cobre:
  a thread morre e o spinner é eterno.
- `cartridges/utils/steam.py:283` — mesma classe no Steam: `response.json().get(...)` sobre corpo
  não-objeto (`null`, lista) levanta `AttributeError`, fora do
  `except (SteamError, RequestException)` do `steam_picker.py:123`.

### M10 — Rastreio por pasta abre handle de todo processo da máquina, a cada 2 s, na main thread

`cartridges/utils/process_monitor.py:365-367`

`is_process_running_under` chama `_process_path(pid)` (um `OpenProcess` +
`QueryFullProcessImageNameW`) para **cada** processo do snapshot, ignorando o nome de executável
que o snapshot já entrega. O pré-filtro `_PSEUDO_PIDS`/`_SYSTEM_PROCESS_NAMES`, construído neste
mesmo módulo depois que esse custo chegou a "centenas de ms por poll" com EDR (linhas 285-290), só
foi ligado em `is_package_running`. É comprovadamente aplicável aqui: `_is_watchable_dir` garante
que o prefixo vigiado nunca está sob `%SystemRoot%`, e o argumento de solidez do set é que esses
nomes só existem lá. Vale pelo grace de entrada inteiro (até 300 s), o de saída e a sessão toda.

---

## Severidade baixa

### B1 — `get_review_summary` repete para erros de shape o bug consertado para transporte

`cartridges/utils/steam.py:686-687` — `response.json().get("query_summary", {})` sobre corpo
não-objeto levanta `AttributeError`, fora do `except (RequestException, ValueError)`. Escapa
**depois** do appdetails já ter respondido — joga fora nome/desenvolvedora/Metacritic e vira
diálogo de erro, exatamente o que o comentário das linhas 688-694 diz ter consertado (para
transporte).

### B2 — Timestamp fora de faixa no histórico derruba o diálogo que o log prometeu proteger

`cartridges/session_history.py:33` — `session_log.load` valida tipo, não faixa; um `end` negativo
ou gigante (edição manual) passa e `datetime.fromtimestamp` levanta `OSError [Errno 22]` (provado
no runtime) dentro do `__init__` do diálogo: o histórico não abre até consertar o arquivo à mão —
contra o contrato do módulo ("uma linha ilegível custa a linha, nunca a leitura").

### B3 — `UnicodeDecodeError` escapa do `session_log.load` e quebra a tela de detalhes

`cartridges/utils/session_log.py:74-79` — o guard cobre `FileNotFoundError`/`OSError`, mas
`UnicodeDecodeError` é `ValueError` e escapa do `read_text`. Byte não-UTF-8 no `sessions.jsonl`
(lixo de cauda pós-queda — o cenário do próprio docstring — ou edição salva em ANSI) →
`window.py:643` (`update_playtime_label`) levanta dentro de `show_details_page`: nenhum jogo com
playtime abre mais a tela de detalhes.

### B4 — Validação de load não cobre tipo dos campos com default

`cartridges/main.py:566-571` + `game.py` — só os quatro campos sem default são validados como
string não-vazia; o resto entra por `setattr` sem checagem. `"playtime": "5h"` num JSON editado
carrega, e quebra a tela de detalhes (`format_playtime` → TypeError) e a ordenação por tempo.
`rating` e `status` ganharam blindagem individual; os numéricos não.

### B5 — Marcador de AUMID comparado com case sensível

`cartridges/utils/run_executable.py:108-113` — `executable.find("shell:AppsFolder\\")` não casa
com `shell:appsfolder\...` digitado à mão, que o Windows aceita: o jogo lança, mas não é tratado
como empacotado — tracking cai no relógio manual e a elevação toma o ramo `cmd /c` sem identidade
de pacote (o modo de falha que o próprio docstring descreve). `casefold()` nos dois lados resolve.

### B6 — Guarda anti-DOCTYPE do feed é contornável por comentário no prólogo

`cartridges/utils/updates_feed.py:292-296` — a janela de busca do `<!DOCTYPE` termina no primeiro
`<`+letra, inclusive **dentro de um comentário**: `<?xml…?><!-- <a --><!DOCTYPE rss [...]><rss>`
passa (provado no runtime: o mesmo doc recusado sem o comentário é aceito com ele). Mitigado por
TLS pinado no host e pelo limitador de amplificação do expat 2.8.2 embarcado — exatamente o
backstop em que o comentário do código diz não confiar. Ancorar a busca ou parar a janela no
primeiro `<` que não abra `<!--`/`<?` fecha o furo.

### B7 — Respostas do HLTB lidas sem teto de tamanho

`cartridges/utils/hltb.py:394,481,670` — `.json()`/`.text` puxam o corpo inteiro para a memória;
o timeout de 15 s limita silêncio entre bytes, não o total. É a única exceção num codebase em que
`download_bytes` e `fetch_feed_text` fazem stream com teto deliberado.

### B8 — Logo sem teto de dimensão, decodificado na main thread

`cartridges/utils/game_logo.py:364-369` — o teto de 25 MiB é de **bytes**; um PNG dessas bytes
pode ter 15.000×8.000 px, o ranking desempata **para o maior** (`width` na chave), e `load_logo`
roda `new_from_file_at_scale` na main thread a cada visita à página de detalhes — o loader PNG
decodifica inteiro antes de escalar: pico de centenas de MB + engasgo visível, repetido, para um
upload comunitário hostil ou só desmedido.

### B9 — Picker de logo busca duas vezes ao abrir

`cartridges/logo_picker.py:94-102` — `set_text` programático emite `search-changed` **atrasado**
(depois do connect da linha 96) → debounce → segunda busca idêntica ~650 ms depois da primeira:
chamada de API e downloads em dobro, e os previews já adicionados são varridos pelo
`_clear_results`. Um guard de texto-inalterado (ou conectar só depois do primeiro `search()`)
resolve. Mesmo padrão latente em `sgdb_picker.py:84-86` e `steam_picker.py:79-81`.

### B10 — Queda no meio da rotação de log deixa a próxima sessão inteira sem log

`cartridges/logging/session_file_handler.py:98-137` + `main.py:338-341` — entre comprimir e
`unlink` existe uma janela em que `cartridges.log` e `cartridges.log.xz` coexistem no número 0.
A próxima inicialização itera a lista snapshotada antes dos renames e levanta
(`FileNotFoundError`/`FileExistsError` — `rename` não sobrescreve no Windows) → `dictConfig`
embrulha em `ValueError` → o `except ValueError: pass` do main deixa a sessão rodar **sem handler
nenhum** — justamente a sessão seguinte a um crash. Auto-cura na execução posterior.

### B11 — Widgets de jogos removidos ficam pinados até fechar o app

`cartridges/store/managers/display_manager.py:108-136` — a remoção tira o jogo da grade mas nada
o evita de `shared.win.game_covers` nem chama `release_picture`: o `GameCover` segue pintando o
widget morto a cada troca de frame, e cada remoção pina a árvore inteira do `Game` até o fim da
sessão. Só memória, limitado pelas remoções da sessão.

### B12 — CoverManager: dois defeitos latentes num caminho hoje morto

`cartridges/store/managers/cover_manager.py:110-113,89-101` — nenhuma fonte deste fork produz
`online_cover_url`/`local_image_path` (grep no repo: só o próprio manager referencia as chaves),
então nada disso roda hoje. Se um dia rodar: (a) o temp é criado **antes** do download — cada URL
que falha vaza um arquivo vazio × 3 tentativas; (b) o manager é `blocking` atrás de um async, e o
callback do `Gio.Task` entrega na main thread (verificado empiricamente) — o retry com
`sleep(3)` congela a UI em até ~21 s por capa que falha.

### B13 — `Game` (um `Gtk.Box`) é construído na worker thread do import

`cartridges/importer/shortcuts_source.py:583` via `importer.py:221-248` — arquitetura herdada do
upstream; `Game.__init__` roda template + controllers fora da main thread. Tolerado na prática
(verificado em runtime nesta base), registrado como risco latente, não como defeito observado.

### B14 — `get_manifest_data` é código morto e frágil

`cartridges/utils/steam.py:160-173` — sem nenhum chamador no fork (import de Steam é via `.url`);
se for reusado: a regex exige `\n` final (CRLF ou última linha sem newline não casam) e a leitura
UTF-8 é sem guard. Candidato a remoção.

---

## Higiene de repositório

### H1 — Página do Instagram commitada no repositório

`rodollfe-2023.html` na raiz, rastreado pelo git: um HTML salvo do Instagram, sem relação com o
projeto (e conteúdo pessoal em controle de versão). Remover do índice.

### H2 — Spec do `game_id.json` descreve o upstream, não este fork

`docs/game_id.json.md` diz "Version 2.0"; o código grava `SPEC_VERSION = 1.6`
(`shared.py.in:41`, com justificativa deliberada), e nenhum campo do fork está documentado:
status, nota, anotação, sessões, campos HLTB, `install_size`, `shortcut_path`. Quem for mexer no
formato vai ler o documento errado.

---

## Verificado e limpo (para não re-flagar)

- **Rede:** timeout em toda requisição (10–15 s); TLS nunca desabilitado; chave do SGDB só em
  header; `open_uri` e feed com allowlist http/https; downloads e feed com teto de bytes e guarda
  de bomba de descompressão; updates checker não baixa nem executa nada e compara timestamps, não
  strings de versão.
- **Injeção:** todo texto externo chega a GTK com `set_use_markup(False)` ou `set_label`;
  `shell=True` recebe apenas comandos validados a montante (`cmd_safe`/`args_safe`/`fullmatch` de
  AUMID no importador).
- **MSYS2:** a inversão de `os.sep` segue real e dependente de `MSYSTEM`; os quatro pontos de
  comparação de `process_monitor` e o `_path_key` do store continuam normalizando dos dois lados,
  com testes fixando as duas convenções e as duas caixas.
- **Win32:** todo `OpenProcess`/snapshot fecha em `finally` em todos os caminhos; COM
  init/uninit balanceado; mutex de instância única correto (incl. `c_void_p` contra truncamento).
- **Sessões:** relógio monotônico com carry; PID reuse tratado e testado; `delete` reescreve via
  tmp + `replace`; flush dos dois rastreadores no shutdown.
- **Threading:** todo salto worker→UI via `GLib.idle_add`; store iterado sob `RLock` (stress
  testado); gamepad inteiro na main loop; rate limiter FIFO correto dormindo só na própria thread.
- **Runtime:** suíte completa verde (594 + 3.241 subtests em 7,6 s, 1 skip ambiental); HLTB ao
  vivo ok nas duas rotas; instalador coerente com o `app_dir` novo (uninstall apaga
  `AppData\Local\Cartridges`); versão consistente entre `meson.build` e metainfo (2026.08.25).

## Registro de método

Seis passadas por subsistema (UI/ciclo de vida; store/persistência; importadores/Steam;
sessões/processos; rede/APIs; gamepad/logging/utils), cada uma lendo os arquivos do escopo por
inteiro, com licença para ler vizinhos como evidência. Cada achado entrou no relatório só depois
de re-verificado contra o código pela revisão final — dois achados de agente foram **endurecidos**
na verificação (M5: o furo é anterior ao guard da linha 284; A1: `do_shutdown` também salva), e
nenhum precisou ser descartado. Os empíricos (junção, `fromtimestamp`, bypass do DOCTYPE, vazamento
de TIFF, callback do `Gio.Task` na main thread) foram reproduzidos no runtime embarcado, não
deduzidos.
