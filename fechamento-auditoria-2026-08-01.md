# Fechamento da auditoria de 01/08/2026

Status item a item dos **38 achados** de `auditoria-cartridges-2026-08-01.md`, cada um verificado
contra o código atual em 01/08/2026. Este documento existe para encerrar o assunto: nenhum achado
da auditoria original precisa ser revisitado a partir daqui.

**Resultado: 38 de 38 fechados.** 37 já estavam corrigidos quando esta verificação começou; 1 (B12)
continuava aberto e foi fechado nela.

Convenção da coluna *Verificado por*: **teste** = existe teste automatizado que falha se regredir;
**leitura** = confirmado no código, sem teste dedicado (tipicamente porque é uma escolha estrutural,
não um comportamento); **runtime** = confirmado executando o app ou medindo contra dados reais.

---

## Parte 1 — Monitoramento UWP

| # | Achado | Status | Onde está o conserto | Verificado por |
|---|---|---|---|---|
| U1 | AUMID de agrupamento gera `package_family` impossível | ✅ | `shortcuts_source.py:474` só emite `shell:AppsFolder` com `!`; sem ele lança o `.lnk`, então `aumid_from_command` devolve `""` e `package_family` fica vazio | teste (`test_shortcuts_source::test_grouping_id_falls_back_to_launching_the_shortcut`) |
| U2 | `_is_running` sem segunda opinião no caminho de pacote | ✅ | `process_session.py:143-147`, OR de três em vez de retorno antecipado | teste (`test_process_session::test_a_configured_name_is_honoured_for_a_packaged_game`) |
| U3 | `is_packaged` calculado uma vez, config letra morta | ✅ | virou método (`details_dialog.py:267`), chamado em `:287` e `:403` | leitura |
| U4 | Custo do poll de pacote na main thread | ✅ | pré-filtro por nome (`process_monitor.py:229`) + cache de PID (`:272`) | teste (`test_process_monitor`, 6 testes de cache) |
| U5 | `aumid_from_command` devolve aspas/argumentos residuais | ✅ | `run_executable.py`, regex `_AUMID_CHARS` no lugar de "tudo depois do marcador" | teste (`test_run_executable`, 10 casos) |
| U6 | Fallback manual conta tempo de jogo que nunca abriu | ✅ | `never_launched` em `process_session.py:275`, com toast e sem registro | teste (`test_process_session::test_a_packaged_game_that_never_appeared_records_nothing`) |
| U7 | `argtypes` ausentes | ✅ | `process_monitor.py:118` e `:124`, dentro de `try` para não impedir o boot | leitura |

## Parte 2 — Severidade alta

| # | Achado | Status | Onde está o conserto | Verificado por |
|---|---|---|---|---|
| A1 | `StopIteration` derruba toda busca de título | ✅ | `title_match.py:284`, early-return quando `wanted_core` é vazio | teste (fuzz de 41×41 pares + casos nomeados) |
| A2 | Falha do PowerShell apaga biblioteca de `.lnk` | ✅ | `shortcuts_source.py:297`, `SourceScanError` quando o lote não resolve nada | teste (`test_shortcuts_source`, 3 testes de guarda de lote) |
| A3 | Fonte que estourou exceção marcada como escaneada | ✅ | `importer.py`, flags separadas `scan_complete`/`scan_failed` | teste (`test_importer`, 6 testes de licença de remoção) |
| A4 | `filter_func` escolhe a caixa pela página visível | ✅ | `window.py:366`, decide pelo FlowBox pai | teste (`test_ui_logic`, 2 testes com janela real) |
| A5 | "Aplicar" fica insensível para sempre | ✅ | contador `_loading_ops` (`details_dialog.py:100/543/563`) | teste (`test_ui_logic`, 3 testes incluindo saída por erro e picker dispensado) |

## Parte 2 — Severidade média

| # | Achado | Status | Onde está o conserto | Verificado por |
|---|---|---|---|---|
| M1 | `Store.__iter__` percorre dicts mutados por workers | ✅ | `store.py`, snapshot sob `RLock` | teste (`test_store_index`, incl. stress com 3 threads) |
| M2 | Falha de download do app list não memorizada | ✅ | backoff 60/300/900 (`steam_applist.py:72`) | teste (`test_steam_applist`, 6 testes) |
| M3 | `cancellable.cancel()` não cancela nada | ✅ | `sgdb_manager.py:64`, `is_cancelled()` consultado no worker | leitura |
| M4 | Falta `break`, capa online sobrescreve a local | ✅ | `cover_manager.py:231` | leitura |
| M5 | `luminance` pode ser `None` | ✅ | `window.py:1058`, guarda explícita | leitura |
| M6 | Direção travada auto-repete após retorno de foco | ✅ | `_direction_latched` (`gamepad.py`) | teste (`test_ui_logic`, 4 testes da máquina de direção) |
| M7 | Log de sessão sem limite; rotação lê tudo em RAM | ✅ | `urllib3` em INFO (`setup.py:115`), `MAX_BYTES` + `copyfileobj` (`session_file_handler.py:47/120`) | teste (`test_ui_logic`, 4 testes de rotação e teto) |
| M8 | `get_review_summary` engole menos do que promete | ✅ | `steam.py:440`, `except (RequestException, ValueError)` | leitura |
| M9 | 403 do HLTB multiplica tráfego, sem breaker | ✅ | circuit breaker (`hltb.py:329/343`) | teste (`test_hltb`, 7 testes) |
| M10 | "Acerto" de logo cacheado sem TTL | ✅ | `HIT_TTL_SECONDS` (`game_logo.py:91`), com `locked` isento | teste (`test_game_logo`, 14 testes) |
| M11 | Histórico persistido não reduz o bucket | ✅ | `seed_history()` (`rate_limiter.py:127`) | teste (`test_rate_limiter`, 8 testes) |
| M12 | `GameCover` antigo continua dono do `Gtk.Picture` | ✅ | `details_dialog.py:496`, `pictures.discard(self.cover)` | leitura |
| M13 | Handlers em singletons nunca desconectados | ✅ | `window.py:275`, `obj.disconnect(handler_id)` no shutdown | leitura |
| M14 | Caminho cru em subtítulo de `Adw.ActionRow` | ✅ | `GLib.markup_escape_text` em `preferences.py:470` e `importer.py:397-398` | leitura |

## Parte 2 — Severidade baixa

| # | Achado | Status | Onde está o conserto | Verificado por |
|---|---|---|---|---|
| B1 | `try` cobre só `WinDLL`, `AttributeError` escapa | ✅ | `gamepad.py:159-161`, lookup dos exports dentro do `try` | leitura |
| B2 | `get_child_at_index(0)` ignora o `filter_func` | ✅ | `gamepad.py:753`, revalida com `filter_func` | leitura |
| B3 | `(today - date).days` sobre `datetime` | ✅ | `relative_date.py:63`, `.date()` nos dois lados + clamp de negativo | teste (`test_relative_date`, 12 testes) |
| B4 | `(name1 > name2) * 2 - 1` nunca devolve 0 | ✅ | `window.py:1079`, `compare_names` desempata por `game_id` | teste (`test_ui_logic`, ordem total) |
| B5 | `install_subdir` sem `exclude_directories` | ✅ | `cartridges/meson.build:17-29` | leitura |
| B6 | `SgdbAuthError` assume corpo JSON | ✅ | `steamgriddb.py`, `except (ValueError, LookupError, TypeError)` | teste (`test_steamgriddb`, 3 testes de 401) |
| B7 | Fallback `results[0]` sem verificação | ✅ | match exato case-insensitive antes do fallback | teste (`test_steamgriddb`, 3 testes) |
| B8 | `cleanup_game` chama GTK a partir da worker | ✅ | `store.py`, dispensa de toasts via `GLib.idle_add` | teste (`test_store_index::test_cleanup_game_dismisses_toasts_on_the_idle`) |
| B9 | `getattr(game, "added")` sem default | ✅ | `game.py:56` (`added: int = 0`) e `main.py:363-366` valida os quatro campos sem default antes de construir o `Game` | leitura |
| B10 | `Path(candidate).expanduser()` levanta `TypeError` | ✅ | `location.py`, candidato de string embrulhado em tupla de um segmento | leitura |
| B11 | `shared.pyi` usa atribuição em vez de anotação | ✅ | `shared.pyi:68`, `store: Optional[Store]` | leitura |
| B12 | `@VERSION@` passado a `main()`, que ignora | ✅ **fechado nesta passagem** | `main()` não recebe mais argumento; `cartridges.in` não substitui mais `@VERSION@`. A versão vem só de `shared.VERSION` | runtime (rebuild + app sobe) |

---

## Nota sobre novas fontes de metadados

A auditoria fechava com uma orientação, não um achado: uma fonte de metadados nova precisa de **duas**
peças — hook de pipeline (`additional_data`) e varredura de backfill — porque `Store.add_game` descarta
jogos existentes como duplicados e `load_games_from_disk` roda sem manager online registrado. Mais a
armadilha de nomenclatura: `game.base_source = source.split("_")[0]`, então um `source_id` com
underscore quebra a remoção de ausentes.

Continua válida e não requer ação. Vale relê-la antes de acrescentar qualquer fonte.

---

## O que este documento não cobre

Os achados **novos**, descobertos depois da auditoria original, estão em
`relatorio-testes-cartridges-2026-08-01.md`: F1 (separadores invertidos no MSYS2), F5 (refutado),
F6 (âncora e `_is_derived_command`), F7 (regexes), F8 (logs no INetCache). Aquele relatório é o
documento vivo; este aqui é o encerramento de uma lista fechada.
