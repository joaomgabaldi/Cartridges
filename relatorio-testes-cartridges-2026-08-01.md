# Cartridges — relatório de execução do plano de testes

**Data:** 01/08/2026
**Escopo:** implementação completa de `plano-de-testes-cartridges.md` (seções 0 a 7).
**Runtime:** MSYS2 ucrt64 (`C:/msys64/ucrt64/bin/python.exe`), com `gi` 3.56 / GTK 4.22 / Adw 1.9 reais.

```bash
C:/msys64/ucrt64/bin/python.exe -m pytest tests/ -q
```

**Resultado:** 369 passando, 3241 subtests, sem `xfail`. Determinístico em execuções repetidas.
A biblioteca real do usuário não é tocada (fixture `app_dirs` é `autouse`).

**Histórico:** a primeira execução terminou em 353 passando + 2 `xfail(strict=True)` cobrindo o F1.
Após a correção do F1 (e a varredura que ela motivou), os `xfail` viraram `XPASS` e foram removidos,
e os testes de regressão dos achados novos entraram.

---

## 1. Achados

### F1 — Separadores invertidos no runtime MSYS2 — **ALTO**

**Status:** corrigido. Os dois `xfail` foram removidos; a garantia agora é coberta por testes normais.

O Python do MSYS2 — o que a aplicação usa em produção — reporta `os.name == 'nt'` e usa `ntpath`,
mas com `os.sep == '/'` e `os.altsep == '\\'`, invertidos em relação ao CPython padrão do Windows.
Tudo que passa por `normpath`/`realpath`/`join` volta com barra normal, enquanto todo caminho que o
Win32 reporta (`QueryFullProcessImageNameW`, `%SystemRoot%`) usa barra invertida. Comparar os dois
como string nunca casa.

Reprodução:

```
install_dir_from_command('start "" "D:\XboxGames\Halo\Content\halo.exe"')
  → 'D:/XboxGames/Halo'
_as_path_prefix(...)        → 'd:/xboxgames/halo/'
processo reportado pelo Win32 → 'D:\XboxGames\Halo\Content\halo.exe'
startswith → False
```

#### Onde falhava

Linhas na numeração **anterior à correção**; a seção seguinte dá as atuais.

| Linha | Código | Produz | Comparado contra |
|---|---|---|---|
| `process_monitor.py:463` | `return os.path.join(resolved, "").casefold()` (fim de `_as_path_prefix`) | `d:/xboxgames/halo/` | caminho de `QueryFullProcessImageNameW`, com `\` |
| `process_monitor.py:142` | `_system_root = os.path.join(os.environ.get("SystemRoot", ...), "").casefold()` | `c:\windows/` | idem |
| `process_monitor.py:499` | `if path and path.casefold().startswith(_system_root):` em `_process_package_family` | nunca `True` | — |
| `process_monitor.py:440` | `return not resolved.casefold().startswith(_system_root)` em `_is_watchable_dir` | nunca exclui | — |
| `process_monitor.py:397` | `_game_root` devolve o resultado de `normpath` | `D:/XboxGames/Halo` | alimenta `_as_path_prefix` |

**F1a — `is_process_running_under` nunca casa** (consumidor de `:463`). Rastreamento de tempo de jogo
por pasta está morto em produção. É a via que o docstring de `process_monitor` descreve como "the
broadest of the three and needs no configuring", e a única que cobre jogo que troca de executável no
meio da sessão sem ser empacotado.
Teste: `tests/test_process_monitor.py::test_folder_matching_accepts_a_win32_process_path`

**F1b — a checagem de `_system_root` nunca exclui os hosts do shell** (`:142` → `:499` e `:440`).
`_process_package_family` deixa de descartar `RuntimeBroker.exe` e afins pelo caminho de imagem.
**Mascarado na prática** por `_SYSTEM_PROCESS_NAMES` (`:205`), que pega esses nomes antes de abrir
handle — então não há inflação de playtime hoje. O que fica falso é o argumento de solidez escrito
naquele conjunto ("would throw it away on the image-path check anyway"): a segunda linha de defesa não
existe. Mesmo efeito faz `_is_watchable_dir` não excluir `%SystemRoot%`.
Teste: `tests/test_process_monitor.py::test_windows_own_folder_is_never_watchable`

#### Correção aplicada

Um normalizador único, aplicado dos dois lados de toda comparação, em vez de depender de `os.sep`:

```python
def _win32_path(path: str) -> str:
    """Backslash-separated, whatever os.sep says on this build of Python."""
    return path.replace("/", "\\")
```

Definido em `process_monitor.py:138`, com **quatro** pontos de aplicação:

| Linha | Função |
|---|---|
| `:164` | `_system_root` |
| `:455` | `_game_root`, na saída |
| `:469` | `_is_watchable_dir`, sobre o `normpath` do próprio argumento |
| `:500` | `_as_path_prefix`, na saída |

`:499` (`_process_package_family`) não muda: o caminho ali vem direto do `QueryFullProcessImageNameW`
e nunca passa por `normpath`, então já está em forma Win32 dos dois lados.

> **Correção do diagnóstico original.** A primeira versão deste relatório dizia três pontos, alegando
> que `:440` (hoje `:469`) já ficaria em forma Win32 depois que `_game_root` normalizasse na saída.
> Errado. `_is_watchable_dir` faz `os.path.normpath(directory)` de novo sobre o argumento, e `normpath`
> é justamente a chamada que reintroduz a barra normal — normalizar na saída de A não protege B se B
> re-normaliza. Vale para `:499`, cujo caminho vem direto do `QueryFullProcessImageNameW` e nunca passa
> por `normpath`; não vale para `_is_watchable_dir`.
>
> A regra que sobrou: **a forma só se mantém enquanto ninguém no caminho chamar `normpath`/`realpath`/
> `join` de novo.** Cada função que re-normaliza precisa do conserto por conta própria.

Testes: `tests/test_process_monitor.py::test_folder_matching_accepts_a_win32_process_path`,
`::test_folder_matching_survives_a_slash_separated_install_dir`,
`::test_windows_own_folder_is_unwatchable_however_it_is_spelled`.

**Por que passou despercebido:** é invisível numa leitura do código com a semântica do CPython padrão,
que é como duas passagens de revisão adversarial passaram por cima dele. A leitura estava correta sobre
a lógica e errada sobre o ambiente — é o tipo de defeito que só executar encontra.

---

### F5 — PowerShell e o namespace do shell — **REFUTADO** (era suspeita ALTA)

**Status:** hipótese refutada por medição. A blindagem aplicada é inócua e fica como defesa em
profundidade; nenhum bug existia.

**A premissa é verdadeira.** `IShellDispatch::NameSpace` de fato recusa barra normal onde
`CreateShortcut` aceita. Medido:

```
Namespace('C:\...\f5test')  → não-nulo
Namespace('C:/.../f5test')  → NULO
CreateShortcut('C:/.../Probe.lnk') → resolve o target normalmente
```

E `str(Path)` no Python do MSYS2 realmente devolve barra normal
(`'C:/Users/.../Probe.lnk'`), então a entrada do script é slash-separated.

**A conclusão era falsa.** O código não passa `$p` para `Namespace`; passa `Split-Path $p`, e
`Split-Path` normaliza:

```
entrada    : C:/Users/carpe/Library/Desktop/Jogos/Avowed.lnk
Split-Path : C:\Users\carpe\Library\Desktop\Jogos
Namespace(resultado) → não-nulo
```

**Medição decisiva:** o script **pré-correção**, rodado contra 59 atalhos reais da biblioteca do
usuário, devolveu **29 AUMIDs** — exatamente o mesmo que o corrigido. Nenhuma perda era possível.

> **Erro de método, registrado de propósito.** Eu verifiquei a propriedade do mecanismo em isolamento
> (`Namespace` com uma string crua) e concluí sobre o caminho real do código sem checar o passo
> intermediário. É o mesmo defeito que o F1 expôs, com o sinal trocado: ali a leitura estava certa sobre
> a lógica e errada sobre o ambiente; aqui a medição estava certa sobre a API e errada sobre o caminho.
> A regra que sobra: **medir a função que o código chama, com os argumentos que o código passa.**

**O que foi aplicado:** `.Replace('/','\\')` no argumento do `Namespace`. Inócuo e correto —
`Split-Path` já entrega barra invertida, então a substituição não tem o que fazer. Vale manter como
defesa em profundidade: protege se algum dia `Split-Path` for trocado por manipulação de string que
não normalize. Se ficar, `.Replace` e **não** `-replace`, que é operador de regex onde uma barra
invertida isolada é escape e a substituição silenciosamente não faz nada.

O `File=$p` ecoando o caminho exatamente como escrito **não** é opcional: é a chave por onde `lnk_data`
é consultado do lado Python, e normalizar de qualquer um dos lados dessincronizaria as duas metades.
Isso continua sendo um invariante real, independente do F5.

Testes: `tests/test_shortcuts_source.py::test_the_result_key_is_echoed_unchanged` (invariante real),
`::test_the_namespace_path_is_backslashed_with_a_literal_replace` (fixa a defesa em profundidade e o
operador correto, com a ressalva de que `Split-Path` é a proteção efetiva).
Verificação de ponta a ponta: `resolve_lnk_targets` contra 59 atalhos reais → 59/59 resolvidos,
29 AUMIDs, 0 chaves divergentes.

---

### F6 — O mesmo padrão na âncora e no `_is_derived_command` — **ALTO**

**Status:** corrigido.

**Onde falhava:** `_games_by_shortcut` é chaveado por `shortcut_path`, com um lado vindo do JSON
persistido e outro do `str(entry)` do scan. Biblioteca escrita por um build e reescaneada por outro
erra a chave — e essa é exatamente a rota de perda de dados que a âncora existe para cobrir, falhando
pela porta que ela foi construída para guardar.

`_is_derived_command` tinha o mesmo problema entre `executable` (reescrito pelo rescan) e
`shortcut_path` (não), o que reintroduzia o fallback absorvente pela porta dos separadores: um jogo no
fallback deixava de ser reconhecido como derivado e nunca mais voltava para o comando por AUMID.

**Correção aplicada:** `_path_key()` em `store.py:50` (`path.replace("/", "\\").casefold()`), usado no
ponto de comparação. O casefold entra junto porque caminho Windows é case-insensitive e Python string
não é — repicar a pasta de atalhos com outra caixa produz o mesmo miss.

Testes: `test_store_index.py::test_the_anchor_matches_across_a_separator_difference`,
`::test_the_anchor_matches_across_a_case_difference`,
`::test_one_path_in_two_conventions_is_not_two_claimants` (duas grafias de um caminho não podem
envenenar a chave),
`::test_the_fallback_is_recognised_across_a_separator_difference`,
`::test_a_command_naming_another_file_is_not_derived` (a normalização não pode virar "vale tudo").

---

### F8 — Logs de sessão gravados no cache da internet — **MÉDIO**

**Status:** corrigido e verificado em runtime. Encontrado executando o app, não lendo o código.

`shared.cache_dir` vem de `GLib.get_user_cache_dir()`, que no Windows mapeia para
`CSIDL_INTERNET_CACHE`:

```
GLib.get_user_cache_dir() → C:\Users\carpe\AppData\Local\Microsoft\Windows\INetCache
logs em                   → ...\INetCache\Cartridges\logs\  (27 KB agora)
```

Essa é a pasta que a Limpeza de Disco e o Sensor de Armazenamento apagam por padrão. O log de
diagnóstico fica disponível até o Windows resolver limpar — que na prática é justamente entre o crash
e o momento em que alguém vai procurar por ele. Também polui a pasta de cache do Internet Explorer com
dados de aplicação.

Há resquício de uma localização anterior: `AppData\Local\Cartridges\logs\` contém `.gz` (formato
antigo), enquanto o INetCache tem os `.xz` atuais — os logs mudaram de lugar em algum momento, e o
lugar novo é pior que o antigo.

**Correção aplicada.** `shared.py.in` deixou de chamar `GLib.get_user_cache_dir()`. Introduzido
`app_dir = data_dir / APP_DIR_NAME`, com todos os diretórios pendurados nele:

```python
app_dir    = data_dir / APP_DIR_NAME
games_dir  = app_dir / "games"
covers_dir = app_dir / "covers"
logos_dir  = app_dir / "logos"
cache_dir  = app_dir / "cache"
log_dir    = app_dir / "logs"
```

Consumidores atualizados: `logging/setup.py` (`shared.log_dir / "cartridges.log"`),
`utils/steam_applist.py` (`shared.cache_dir / "steam_applist.json"` — o `APP_DIR_NAME` que era
concatenado ali virou redundante).

**Cuidado que valeu a pena tomar em `preferences.py:reset_app`.** A tentação era repontar `cache_dir`
e parar. Mas aquele método faz `rmtree(shared.cache_dir / shared.APP_DIR_NAME)`, e com `cache_dir`
apontando para dentro de `data_dir` isso teria virado `rmtree` sobre a pasta que contém
`games/`, `covers/` e `logos/` — a mudança "arrumadinha" que apaga a biblioteca. Reescrito para listar
explicitamente o que apaga (`app_dir`, `config_dir/APP_DIR_NAME`, `cache_dir`, `log_dir`), o que
continua correto se qualquer um deles for movido de novo.

Teste: `tests/test_ui_logic.py::test_nothing_is_written_to_the_browser_cache`, lendo `shared.py.in` (o
template) e não o `shared` sintético do harness — asserção contra a própria fixture só provaria que ela
concorda consigo mesma.

**Verificado em runtime:** após rebuild e reinstalação, os logs aparecem em
`AppData\Local\Cartridges\logs\` e `INetCache\Cartridges\` deixou de ser criada. Os três arquivos
órfãos que restavam lá foram removidos.

---

### F7 — Regexes de caminho aceitavam só `\` — **LATENTE**

**Status:** corrigido.

**Onde falhava:** `process_monitor.py:378` e `:381` (`_QUOTED_EXE`, `_BARE_EXE`). Salvo por sorte hoje —
`Gio.File.get_path()` devolve barra invertida — mas alguém "limpando" aquilo com `Path(path)` mataria o
rastreamento por pasta em silêncio outra vez, pelo mesmo mecanismo do F1.

**Correção aplicada:** `[\\/]` no lugar de `\\`.

Teste: `tests/test_process_monitor.py::test_install_dir_is_read_from_a_slash_separated_command`.

**Por que passou despercebido:** é invisível numa leitura do código com a semântica do CPython padrão,
que é como duas passagens de revisão adversarial passaram por cima dele.

---

### F2 — 33 testes de `hltb` quebrados desde o circuit breaker — **MÉDIO**

**Status:** corrigido em `tests/test_hltb.py`.

**Onde falha:** `tests/test_hltb.py:236` (`make_helper`) constrói o helper via `HLTBHelper.__new__` e
monta os campos à mão, para não abrir uma sessão HTTP real. Quando o circuit breaker adicionou
`_breaker_lock`, `_failures` e `_blocked_until` em `cartridges/utils/hltb.py:323-325`, o helper de teste
não acompanhou. Como `search` chama `_breaker_check()` (`hltb.py:329`) como primeira instrução, todo
teste que chegava ao caminho de rede morria com
`AttributeError: 'HLTBHelper' object has no attribute '_breaker_lock'` antes de testar qualquer coisa.

**Correção aplicada:** os três campos acrescentados em `make_helper`, com comentário explicando por que
o bypass de `__init__` obriga a isso.

Consequência para o plano: a linha de abertura de `plano-de-testes-cartridges.md` ("**95 testes em 5
arquivos**, todos sobre módulos puros") descrevia 66 testes rodando e 33 falhando.

**Correção sugerida (estrutural, não aplicada):** um construtor de teste que faz bypass de `__init__` é
uma cópia do construtor real que ninguém mantém. Um teste que instancie `HLTBHelper()` de verdade uma
vez e compare `vars()` com o que `make_helper` produz fecha a classe inteira de divergência, em vez de
esperar o próximo campo novo.

---

### F3 — T6.13 pedia uma propriedade que o desenho não tem — **BAIXO (correção de plano)**

**Status:** plano ajustado na implementação.

**Onde falha:** o item do plano, não o código. A regra direcional está em
`cartridges/utils/title_match.py:291` (`if not wanted_set.issubset(candidate_set)`).

O item pedia simetria: "`compare_titles(a, b)` e `(b, a)` concordam sobre 'é o mesmo jogo'". O matcher
é deliberadamente direcional — a regra é de subconjunto, "tudo que o título procurado diz tem que estar
presente no candidato". Então:

- `compare_titles("Sid Meier's Civilization VI", "Civilization VI")` → mismatch (faltam palavras)
- `compare_titles("Civilization VI", "Sid Meier's Civilization VI")` → casa (prefixo de autoria)

Nunca aparece como inconsistência porque todo chamador passa o título local primeiro
(`rank_candidates`, `updates_checker`). Substituí a asserção de simetria por três testes que **fixam a
direcionalidade** (`TestDirectionality`), mais a simetria do portão de sequência — essa vale de fato — e
a propriedade de que, fora da regra de subconjunto, os dois lados concordam.

---

### F4 — Semântica de atribuição de tempo no grace (esclarecimento, não bug)

Ao escrever T5.6 assumi que o intervalo inteiro de ausência era descartado. Não é, e o comportamento
atual está correto: quando um poll encontra o processo sumido, o trecho desde o poll **anterior** é
creditado — o jogo morreu em algum ponto desconhecido daquele intervalo, e creditar o todo é a ponta
conservadora de uma incerteza de dois segundos. Descartada é a janela de grace inteira depois disso.
Documentado no docstring do teste.

---

### F9 — Comentário justificava uma decisão com a razão errada — **DOCUMENTAÇÃO**

**Status:** corrigido. Nenhuma mudança de comportamento.

O comentário de `_migrate_game_files` explica por que a adoção de uma lápide reescreve só o `game_id`,
deixando `executable` e `shortcut_path` obsoletos no disco. A decisão está certa; uma das três razões
dadas não estava.

O comentário afirmava que um `shortcut_path` obsoleto não pode enganar porque *"a different game
arriving at that path has a different id, so `_index_shortcut` poisons the key instead of matching"*.
Mas em `add_game` a âncora é consultada **antes** de qualquer indexação, então o primeiro jogo a chegar
no caminho da lápide a adota — não existe chave contestada ainda para envenenar.

Medido nos dois sentidos:

| `shortcut_mtime` do que chega | Resultado |
|---|---|
| igual ao da lápide (arquivo intacto) | adota a lápide, continua removido, biblioteca visível vazia |
| maior (atalho recriado) | ramo de reinstalação, jogo importa normalmente |

Ou seja: a contenção existe e é sólida, mas quem a garante é o portão de `shortcut_mtime`, não o
envenenamento do índice. Comentário reescrito para dizer isso — e para dizer explicitamente que a
resposta óbvia é a errada, já que era exatamente nela que ele apoiava a decisão.

Testes: `test_store_adoption::test_an_unchanged_shortcut_at_a_tombstones_path_stays_removed` e
`::test_a_recreated_shortcut_at_a_tombstones_path_comes_back`. A afirmação "verified both ways" no
comentário agora tem as duas direções travadas por teste em vez de por um script de rascunho.

---

## 1b. Verificação em runtime (01/08, com backup da biblioteca autorizado pelo usuário)

Suíte verde não é o mesmo que projeto sem erro: prova as afirmações que alguém escolheu escrever.
O que segue foi executado, não afirmado.

| Verificação | Resultado |
|---|---|
| `meson setup --reconfigure` + `ninja -C _build` | limpo, 0 warnings, 0 erros |
| `meson install` (staging) | limpo |
| App inicia | `v2026.08.01`, carrega 87 jogos, 0 erro real no log |
| Importação real (`auto-import` está `true`) | conclui; 0 linhas "Removing missing game" |
| **Idempotência sobre biblioteca real** | 87 → 87 jogos, 0 ids sumidos, 0 novos, **0 registros alterados**, 5 lápides antes e depois |
| `resolve_lnk_targets` sobre 59 atalhos reais | 59/59 resolvidos, 29 AUMIDs, 0 chave divergente |
| `python -m compileall cartridges tests` | 0 erros de sintaxe |
| `pylint -E` em `cartridges` + `tests` | 40 achados, **todos falsos positivos** (verificados um a um) |

Os 40 do pylint têm uma raiz só: `cartridges/shared.py` é gerado pelo meson e não existe na árvore, o
que degrada a inferência do astroid para os módulos que o importam. Verificados:

- **37 × E1101 (no-member).** `Gio.SettingsBindFlags.DEFAULT` existe (vale `0`);
  `hltb._BREAKER_FAILURE_THRESHOLD`, `game_logo.HIT_TTL_SECONDS`, `process_monitor._UNREADABLE` e
  `HLTBHelper._breaker_check/_breaker_record` existem e são exercitados por testes que passam;
  `row.add_row` em `window.py:1009` está dentro de `for child in children`, a mesma condição que
  escolheu `Adw.ExpanderRow` em vez de `Adw.ActionRow` na linha 985 — o pylint estreitou a união para
  o ramo errado.
- **2 × E0602 (undefined-variable).** `ngettext` é builtin instalado por `cartridges.in`.
- **1 × E1123 (unexpected-keyword-arg).** `never_launched` é parâmetro declarado em
  `process_session.py:275`.

Nota para quem for rodar de novo: sem `_build/cartridges/shared.py` alcançável como
`cartridges.shared`, esse ruído é o piso do pylint neste projeto. Não é sinal de nada.

O dado mais forte é a linha de idempotência: uma importação real, sobre 87 jogos, 59 atalhos e as duas
convenções de separador misturadas nos dados persistidos, não mudou um byte.

---

## 2. Desvios do plano

| Item | Plano | Executado | Motivo |
|---|---|---|---|
| T0.1 | stub de `gi` em `sys.modules` | sem stub; GTK/Adw reais do MSYS2 | decisão do autor; elimina a parte mais frágil do harness e testa a fiação real dos widgets |
| T0.3 | duck-type ou `Game` mínimo | ambos: `FakeGame` para `Store`, `Game` real na seção 3 | `Store` só lê campos e conta `save()`; a seção 3 precisa do `Game` que a source produz de fato |
| T7.1, T7.3 | extrair a lógica para função/classe pura | testados no widget real | `CartridgesWindow` e `DetailsDialog` constroem sem display; extrair custaria fidelidade sem ganho |
| T6.13 | simetria | direcionalidade | ver F3 |
| T1.16 | teste de contenção do lock | leitura do lock em outra thread | `RLock` é reentrante; só uma segunda thread distingue |

## 3. Notas de ambiente

- `pytest` instalado no MSYS2 com `pacman -S mingw-w64-ucrt-x86_64-python-pytest`.
- `tests/conftest.py` precisa de `Gtk.init()` + `Adw.init()` **antes** de instanciar qualquer
  `Gtk.Template`; sem isso os GTypes da Adwaita não estão registrados, `Gtk.Builder` falha com
  `Invalid object type 'AdwClamp'` e os filhos do template voltam `None` — o erro aparece muito depois,
  como `AttributeError`.
- O gresource (`_build/data/cartridges.gresource`) tem de estar carregado antes de importar
  `cartridges.game`. Se o `_build` não existir, o conftest falha com instrução de build.
- `cartridges.shared` é sintetizado, não lido do `_build`: o real chama `Gio.Settings.new` (que aborta
  o processo sem schema instalado) e resolve `games_dir` para a biblioteca viva.

## 4. Cobertura entregue

| Seção | Arquivo | Testes |
|---|---|---|
| 1 | `test_store_adoption.py`, `test_store_index.py` | 25 + 32 |
| 2 | `test_importer.py` | 15 |
| 3 | `test_shortcuts_source.py` | 34 |
| 4 | `test_process_monitor.py` | 41 |
| 5 | `test_process_session.py` | 22 |
| 6 | `test_relative_date.py`, `test_rate_limiter.py`, `test_game_logo.py`, `test_steamgriddb.py`, `test_run_executable.py` | 12 + 8 + 14 + 7 + 12 |
| 6 | extensões: `test_steam_applist.py` +6, `test_title_match.py` +7, `test_hltb.py` +7 | |
| 7 | `test_ui_logic.py` | 25 |

Os seis prioritários da ordem sugerida no plano estão implementados e passando: T3.1, T1.34, T1.29,
T2.2, T1.6, T1.9.
