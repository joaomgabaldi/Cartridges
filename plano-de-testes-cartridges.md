# Cartridges — plano de testes

Estado atual: **95 testes em 5 arquivos**, todos sobre módulos puros
(`hltb` 46, `updates_feed` 18, `title_match` 20, `name_cleaner` 9, `steam_applist` 6).

O que eles cobrem é parsing e comparação de texto. O que não cobrem é **toda a lógica que
pode apagar a biblioteca do usuário** — identidade de jogo, adoção, remoção de ausentes,
sessão de jogo. As três rodadas de revisão desta auditoria acharam dez bugs nessa região, dois
deles introduzidos consertando os outros, e o que segurou foi leitura adversarial. É o
argumento mais forte possível a favor destes testes.

Prioridade: **P0** = protege contra perda de dados. **P1** = protege contra funcionalidade
morta em silêncio. **P2** = correção de comportamento visível. **P3** = higiene.

---

## 0. Pré-requisito: o harness (P0)

14 dos 60 módulos importam sem GTK. Todo o resto morre em `gi.repository` ou em
`cartridges.shared` (que o meson gera a partir de `shared.py.in` e não existe na árvore).

Sem resolver isso, nada da seção 1 à 5 é escrevível.

**T0.1** `tests/conftest.py` que instala um stub de `gi`/`gi.repository` em `sys.modules`
antes de qualquer import de `cartridges`. Precisa de `GObject.Object` com `connect`/`emit`
funcionais (os managers dependem de sinais), `GLib.idle_add`/`timeout_add_seconds` que
executam na hora ou enfileiram para um "loop" manual, e `Gtk.Template` como no-op.

**T0.2** `shared` de teste: `tmp_path` para `games_dir`, `covers_dir`, `logos_dir`, e um
`schema` falso com `get_boolean`/`get_int`/`get_string` alimentado por dict. Fixture que
devolve as três pastas já criadas.

**T0.3** Fábrica `make_game(**overrides)` devolvendo um `Game` mínimo sem widget — ou um
duck-type com os atributos que `Store` toca (`game_id`, `base_source`, `source`, `name`,
`executable`, `shortcut_path`, `shortcut_mtime`, `removed`, `version`, `save`, `update`).
Um duck-type é provavelmente melhor: testa `Store` sem arrastar `Gtk.Template`.

**T0.4** Fixture `store` que devolve um `Store` limpo com managers falsos, e helper para
gravar um JSON de jogo em `games_dir` (para testar o que a adoção faz com arquivos).

**T0.5** `GLib.idle_add` do stub tem que ser drenável explicitamente — vários testes de
`Store` dependem do `rekey_cover` diferido. Um `flush_idle()` no conftest.

> Decisão que ainda é sua: stub de `gi` vs. rodar a suíte dentro do MSYS2 com GTK de verdade.
> O stub roda em CI Linux e é rápido; o GTK real testa integração mas amarra a suíte ao MSYS2.
> Recomendo o stub para tudo abaixo, e nada de teste de widget.

---

## 1. `Store` — identidade, adoção e índice de âncora (P0)

A área mais perigosa do projeto e a que tem zero cobertura.

### 1.1 Adoção — casamento

**T1.1** Adota por `legacy_game_ids`: jogo em disco sob id antigo, scan produz id novo com o
antigo em `legacy_game_ids` → o registro é adotado, `playtime` preservado, nenhum jogo novo
criado, id novo entra em `duplicate_game_ids`.
**T1.2** Adota pela âncora quando nenhum `legacy_game_ids` é oferecido, com
`identity_anchor` presente.
**T1.3** **Não** adota pela âncora sem `identity_anchor` — este é o teste que impede a fusão
no boot. Dois JSONs com o mesmo `shortcut_path` e ids diferentes carregados por
`load_games_from_disk` continuam sendo dois jogos.
**T1.4** Não adota quando `legacy_id == game.game_id` (nada mudou).
**T1.5** Não adota registro de outra `base_source` com o mesmo `shortcut_path`.
**T1.6** **Recusa entrada obsoleta do índice**: índice aponta para objeto que
`games_by_id` não contém mais → `adopt_legacy_game` devolve `None` e não migra arquivo nenhum.
Regressão direta do bug "adoção órfã rouba arquivo de jogo vivo".
**T1.7** `legacy_game_ids` tem prioridade sobre a âncora quando os dois casam em registros
diferentes.

### 1.2 Adoção — efeitos

**T1.8** Migra `<old>.json` → `<new>.json`, capa (`.tiff`/`.gif`/`.webp`) e logo
(`.png`/`.webp`/`.jpg`/`.jpeg` + sidecar).
**T1.9** Reescreve `"game_id"` **dentro** do JSON movido. Regressão do bug "adoção de lápide
não persiste".
**T1.10** Corrige o campo `"file"` do sidecar do logo (`<old>.png` → `<new>.png`).
**T1.11** Sidecar `locked` (logo escolhido à mão) sobrevive à migração.
**T1.12** Arquivo que não existe não quebra a migração; arquivo que falha ao mover apenas loga.
**T1.13** Re-chaveia `games_by_id`, `source_games` e `_games_by_shortcut`; nenhuma chave antiga
sobra em nenhum dos três.
**T1.14** `shared.win.game_covers` é re-chaveado **no idle**, não na hora (drenar com
`flush_idle`).
**T1.15** `executable` e `shortcut_path` do registro adotado recebem os valores do scan.
**T1.16** Adoção não roda `_migrate_game_files` segurando o lock (teste de contenção: uma
thread adotando não bloqueia `len(store)` por mais que um instante). Difícil de fazer sem
flakiness — alternativa honesta: teste de leitura, não de tempo.

### 1.3 Adoção de lápide (o caso que **tem** que continuar funcionando)

**T1.17** Lápide adotada segue para o id novo e o jogo **continua removido** (`mtime` empata →
ramo `stored_game.removed` → `duplicate_game_ids`).
**T1.18** Lápide adotada **não** é ressuscitada por `remove_games` nem aparece na biblioteca.
**T1.19** Lápide adotada com `mtime` maior no scan → ramo de reinstalação, `cleanup_game`
roda, jogo volta.
**T1.20** Adoção de lápide não toca `shortcut_mtime` (o portão de ressurreição).

### 1.4 Índice de âncora

**T1.21** Jogo novo com `shortcut_path` é indexado.
**T1.22** `shortcut_path` vazio nunca é indexado.
**T1.23** Segundo registro, id diferente, mesmo caminho → chave envenenada (`None`).
**T1.24** Chave envenenada não produz adoção.
**T1.25** Terceiro reclamante numa chave envenenada não a "resolve" — continua `None`.
**T1.26** Mesmo `game_id` reindexando → reassume (é o caminho de reinstalação trocando a
lápide pelo jogo que voltou).
**T1.27** `_reindex_shortcut` aposenta a chave antiga e reivindica a nova.
**T1.28** `_reindex_shortcut` para um caminho já reclamado por outro id → envenena, não rouba.
**T1.29** **Reivindicação da chave liberada**: caminho contestado → envenenado; um dos dois sai
por rename/adoção (`pop`); o que ficou reindexa pelo ramo de duplicata e a âncora volta a
funcionar para aquele caminho **sem esperar o próximo boot**.
**T1.30** O mesmo ramo de duplicata **não** desenvenena uma chave ainda contestada.

### 1.5 Ramo de duplicata

**T1.31** `shortcut_mtime` avança quando o arquivo é mais novo; não retrocede.
**T1.32** `executable` refrescado empacotado → empacotado (AUMID resolvido mudou).
**T1.33** `executable` refrescado empacotado → fallback `start "" "<lnk>"`.
**T1.34** `executable` refrescado fallback → empacotado. **Este é o teste que impede o
fallback absorvente**; sem ele o bug volta e ninguém percebe.
**T1.35** `executable` **não** refrescado para jogo clássico.
**T1.36** `executable` **não** refrescado para `.url`.
**T1.37** Comando idêntico → nenhuma escrita (guarda de igualdade, a trava mais forte).
**T1.38** `.lnk` clássico com `shell:AppsFolder\…` nos argumentos: passa em
`_is_derived_command` mas é barrado pela igualdade, porque a identidade é `target|arguments` e
o rescan reconstrói o mesmo comando. Testa as duas travas em série.
**T1.39** Rename seguido **só** quando o caminho armazenado sumiu do disco.
**T1.40** Dois `.lnk` para o mesmo jogo (ambos existindo) → **um** `save()` por scan, não dois,
e `shortcut_path` estável entre execuções. Regressão do churn.
**T1.41** `save()` chamado uma vez quando `mtime` e `executable` mudam juntos.
**T1.42** Nada muda → nenhum `save()`.

### 1.6 Concorrência

**T1.43** `__iter__` devolve snapshot: mutar o store durante o laço não levanta
`RuntimeError` nem altera o que o laço vê.
**T1.44** Stress: N threads em `add_game` enquanto a main itera — sem exceção, contagem final
correta.
**T1.45** `clear()` zera os três índices.
**T1.46** `cleanup_game` dispensa toasts pelo idle, não na thread chamadora.

---

## 2. `Importer` — quando é seguro remover jogos (P0)

**T2.1** Scan limpo → `source_id` entra em `scanned_source_ids`.
**T2.2** Gerador levanta exceção genérica → **não** entra. Regressão do bug em que
`continue` → `StopIteration` marcava varredura falha como bem-sucedida.
**T2.3** `SourceScanError` → não entra **e** `report_error` é chamado (o usuário vê).
**T2.4** Fonte indisponível / `UnresolvableLocationError` → não entra.
**T2.5** Exceção depois de N jogos já produzidos: os N são importados, a fonte não é marcada.
**T2.6** `remove_games` pula fonte fora de `scanned_source_ids`.
**T2.7** `remove_games` pula jogos em `duplicate_game_ids` e `new_game_ids`.
**T2.8** `remove_games` pula `source == "imported"` e fonte desligada no schema.
**T2.9** `remove-missing` desligado → não remove nada.
**T2.10** Fonte que produziu zero jogos **mas escaneou com sucesso** → remove mesmo (é o
comportamento correto: pasta esvaziada de verdade).

---

## 3. `ShortcutsSource` — derivação de identidade e guardas de lote (P0)

**T3.1** Identidade UWP vem do AUMID **cru**: o mesmo `.lnk` produz o mesmo `game_id` com
`resolve_start_apps()` funcionando e falhando. **O teste central de todo o desenho.**
**T3.2** `legacy_game_ids` oferecido só quando `launch_aumid != aumid`.
**T3.3** `identity_anchor` setado para todo jogo empacotado, inclusive sem legacy id.
**T3.4** AUMID com `!` → comando `explorer.exe shell:AppsFolder\<aumid>`.
**T3.5** AUMID sem `!` (grouping id) → comando `start "" "<caminho do .lnk>"`, e a string bate
**caractere a caractere** com o que `Store._is_derived_command` reconstrói. Um teste que
compara as duas expressões literalmente, senão o fallback volta a ser absorvente.
**T3.6** AUMID com caractere fora de `[\w.!+\-]` → jogo ignorado.
**T3.7** Caminho de `.lnk` que reprova em `cmd_safe` → ignorado.
**T3.8** `resolve_lnk_targets` devolvendo `{}` com `lnk_files` não vazio → `SourceScanError`.
**T3.9** `resolve_lnk_targets` devolvendo `{}` com `lnk_files` **vazio** → sem erro.
**T3.10** `.url` são produzidos **antes** da guarda: um lote de `.lnk` que falha ainda deixa os
`.url` importados (progresso parcial).
**T3.11** `resolve_start_apps()` vazia com `needs_start_apps` → `SourceScanError`.
**T3.12** `needs_start_apps` falso (nenhum atalho com AUMID) → não chama `Get-StartApps` e não
levanta.
**T3.13** Injeção: `Arguments = & calc.exe` → atalho ignorado (`args_safe`).
**T3.14** Injeção: aspas/control chars em `Target`/`WorkingDirectory` → ignorado.
**T3.15** Identidade clássica = `target|arguments`; renomear o `.lnk` não muda o `game_id`.
**T3.16** Identidade `.url` = a URL.
**T3.17** `_game_id` é estável e no formato `shortcuts_<16 hex>`.
**T3.18** `_real_aumid`: casa por nome de exibição; casa por `pkgkey`; devolve o cru quando
nada casa.
**T3.19** `_SKIP_NAME_RE` filtra desinstaladores/leia-me.
**T3.20** `steam_appid_from_url` extrai o appid de `.url` da Steam.

---

## 4. `process_monitor` — parsing e cache (P1)

Roda só em Windows (`ctypes.windll` no import). Ou marca a suíte com
`@pytest.mark.skipif(os.name != "nt")`, ou stuba `ctypes.windll` no conftest — o segundo
libera os testes de parsing, que são a maioria.

**T4.1** `install_dir_from_command`: caminho entre aspas; caminho nu sem espaços; caminho nu
**com** espaços (deve devolver `""`); nenhum `.exe`; URI de launcher.
**T4.2** Escolhe o **último** `.exe` do comando, não o primeiro.
**T4.3** `_game_root` sobe até a pasta cujo pai é container conhecido
(`SteamLibrary`, `XboxGames`, `Program Files`…), incluindo o caso Unreal
`Binaries\Win64` e o launcher em subpasta irmã.
**T4.4** `_game_root` devolve `""` quando chega na raiz do drive sem achar container.
**T4.5** `_game_root` respeita `_MAX_ROOT_WALK`.
**T4.6** `_is_watchable_dir`: raiz de drive → falso; container puro → falso; dentro de
`%SystemRoot%` → falso.
**T4.7** `_as_path_prefix` termina em separador — `.../Battlefield 1` não casa
`.../Battlefield 11/game.exe`.
**T4.8** `_name_variants`: `"game"` casa `"game.exe"` e vice-versa; case-insensitive.
**T4.9** Cache: resposta "sem pacote" é reaproveitada no poll seguinte para o mesmo
`(pid, nome)`.
**T4.10** Cache: `_UNREADABLE` (OpenProcess recusado) **não** é cacheado — a próxima
varredura pergunta de novo. Regressão do "recusa vira veredito permanente".
**T4.11** Cache: pid ausente do snapshot atual é evictado.
**T4.12** Cache: mesmo pid com nome de executável diferente invalida a entrada.
**T4.13** Pré-filtro pula pids 0/4 e os nomes de `_SYSTEM_PROCESS_NAMES` sem abrir handle.
**T4.14** `aumid_from_command`: comando limpo; com aspa final (`.url`); com argumento depois;
sem marcador → `""`; caractere inválido corta no ponto certo.

---

## 5. `ProcessSession` — ciclo de vida da sessão (P1)

**T5.1** `_is_running` é OR de três: casa por pacote; casa por nome quando o pacote não
responde; casa por pasta. Regressão do "caminho de pacote sem segunda opinião".
**T5.2** `_accumulate` usa relógio monotônico e carrega o resto sub-segundo: 100 polls de 2,5 s
somam 250 s, não 200.
**T5.3** Relógio da parede andando para trás/frente não altera o acumulado.
**T5.4** Processo nunca aparece, jogo **empacotado** → `never_launched`, nada gravado, toast.
**T5.5** Processo nunca aparece, jogo **clássico** → `SessionWindow` manual.
**T5.6** Janela de grace: processo some e volta dentro do grace → sessão continua, tempo do
intervalo **não** é contado.
**T5.7** Processo some além do grace → sessão encerra e grava.
**T5.8** Fonte GLib removida exatamente uma vez nos dois caminhos de `SOURCE_REMOVE`.
**T5.9** `flush()` no shutdown grava o trecho corrente e nada mais.
**T5.10** Lançar um segundo jogo encerra a sessão anterior gravando.
**T5.11** Toast com `&`/`<` no título do jogo não quebra (`set_use_markup(False)`).

---

## 6. Módulos puros — completar o que já existe (P2)

Estes rodam hoje, sem harness nenhum.

### `relative_date` (nenhum teste existe)
**T6.1** 23:50 de ontem visto às 00:10 → "Ontem", não "Hoje".
**T6.2** 00:30 de hoje visto às 23:00 → "Hoje".
**T6.3** Timestamp no futuro → "Hoje", nunca nome de dia da semana.
**T6.4** Fronteiras de semana/mês/ano.

### `steam_applist` (6 testes; o backoff é novo)
**T6.5** Falha de download não é repetida dentro da janela de backoff.
**T6.6** Backoff escala 60 → 300 → 900 e para no teto.
**T6.7** Sucesso zera o contador.
**T6.8** Cache em disco velho é usado quando o download falha, e isso **não** registra falha.
**T6.9** Nome sem *core words* devolve `[]` **sem** disparar o download.
**T6.10** Escrita de cache é atômica (`.tmp` + `replace`).

### `title_match` (20 testes)
**T6.11** Título só-dígitos / só-stopword → `SCORE_MISMATCH`, sem exceção (já feito, manter).
**T6.12** Fuzz: 10k pares aleatórios de títulos reais nunca levantam exceção. É o teste que
teria pego o `StopIteration` original.
**T6.13** Simetria: `compare_titles(a, b)` e `(b, a)` concordam sobre "é o mesmo jogo".

### `rate_limiter`
**T6.14** `seed_history` consome tokens do burst proporcionalmente ao histórico dentro da
janela.
**T6.15** Histórico só com timestamps expirados não consome nada.
**T6.16** Histórico maior que o burst não estoura (clamp).
**T6.17** Espaçamento observado respeita o limite (o teste empírico que já existia, formalizado).

### `hltb` (46 testes; circuit breaker é novo)
**T6.18** N falhas consecutivas abrem o breaker e a chamada seguinte não toca a rede.
**T6.19** Cooldown expira → volta a tentar.
**T6.20** Qualquer sucesso zera o contador.

### `game_logo`
**T6.21** Hit não-locked expira pelo TTL.
**T6.22** Hit `locked` **nunca** expira, por mais velho que seja.
**T6.23** Falha transitória de fetch não sobrescreve um hit bom com miss.

### `steamgriddb`
**T6.24** 401 com corpo HTML → `SgdbAuthError` (não `JSONDecodeError`).
**T6.25** 401 com JSON sem `errors` → `SgdbAuthError`.
**T6.26** Match exato de título tem prioridade sobre `results[0]`.

### `run_executable`
**T6.27** `aumid_from_command` — os mesmos casos de T4.14, aqui como unidade.

---

## 7. UI e o resto (P3)

Teste de widget não vale o custo. O que vale é extrair a lógica e testá-la:

**T7.1** `window.filter_func` decidindo pelo FlowBox pai — extrair a decisão para uma função
pura `(child_parent, hidden_flag, search_text) -> bool` e testar. Cobre o bug do grid errado.
**T7.2** `window.compare_names` — ordem total: reflexiva, antissimétrica, transitiva; empate de
nome desempata por `game_id`.
**T7.3** Contador `_loading_ops` do `details_dialog` — extrair para uma classinha e testar que
todo caminho (sucesso, erro, picker dispensado, thread morrendo) fecha em zero. Cobre o
"Aplicar travado".
**T7.4** `gamepad`: máquina de estados de direção — direção segurada atravessando `_resync`
não gera movimento; soltar e repressionar gera; trocar de direção sem soltar gera. Testável
com stub de `GLib.get_monotonic_time`.
**T7.5** `session_file_handler`: rotação por streaming preserva bytes inválidos; teto de
tamanho dispara e escreve o aviso; `emit` nunca levanta com stream fechada.
**T7.6** `window_geometry`: salvar/restaurar retângulo; não salva enquanto maximizado.

---

## 8. O que **não** testar

- Widgets, layout, tema. Custo alto, valor baixo, e o GTK muda debaixo.
- `subprojects/blueprint-compiler` — ferramenta de terceiros vendorizada.
- As chamadas Win32 em si (`CreateToolhelp32Snapshot`, `GetPackageFamilyName`). Auditadas e
  corretas; um teste delas testaria o stub, não o Windows.
- Rede de verdade. Tudo mockado.

---

## Ordem sugerida

1. **T0.\*** (harness) — sem isso, 60% desta lista é inescrevível.
2. **T3.1, T1.34, T1.29, T2.2, T1.6, T1.9** — os seis que travam os bugs que já morderam e
   voltariam sem serem notados.
3. Resto da seção 1 e 2 (perda de dados).
4. Seção 6 (barata, roda hoje, sem harness).
5. Seções 4 e 5.
6. Seção 7 conforme a lógica for sendo extraída.

Total: ~150 testes, dos quais ~35 rodam sem nenhuma infraestrutura nova.
