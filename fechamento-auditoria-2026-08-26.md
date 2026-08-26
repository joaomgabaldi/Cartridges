# Fechamento da auditoria de 26/08/2026

Status item a item dos **29 achados** de `auditoria-cartridges-2026-08-26.md`, todos corrigidos
em 26/08/2026, na versão **2026.08.26**. Este documento encerra a lista: nenhum achado daquela
auditoria precisa ser revisitado a partir daqui.

**Resultado: 29 de 29 fechados** — 27 corrigidos no código, 1 resolvido como risco aceito e
documentado (B13), 1 resolvido por remoção (B14). Suíte após os consertos: **626 testes +
3.241 subtests passando** no runtime real (eram 594 antes; 32 testes de regressão novos), build
meson/ninja limpo.

Convenção da coluna *Verificado por*: **teste** = regressão automatizada que falha se voltar;
**leitura** = confirmado no código, sem teste dedicado; **suíte** = coberto pelos testes que já
existiam e continuam verdes por cima do conserto.

## Severidade alta

| # | Achado | Onde está o conserto | Verificado por |
|---|---|---|---|
| A1 | Fechar minimizado grava retângulo icônico | `window_geometry.py`: `IsIconic` em `read()` devolve `None`; `Geometry.usable` rejeita (-32000,-32000) para curar estado já envenenado | teste (`test_ui_logic`, 2 testes) |
| A2 | `folder_size` segue junções | `install_size.py:141`, `not entry.is_junction()` | teste (`test_install_size`, junção real + ciclo) |
| A3 | "Só o que falta" reverte edições | `steam_api_manager.py`, `_keep_user_edits` filtra os cinco campos editáveis para preencher-só-vazio; `metadata_refresh.py` passa `only_missing` no `additional_data` | teste (`test_metadata_refresh`) |

## Severidade média

| # | Achado | Onde está o conserto | Verificado por |
|---|---|---|---|
| M1 | Reset ressuscita jogos | Guard de identidade no store (`store.get(id) is game`, idioma do `_in_library`) nos `_apply` de `hltb_backfill.py` e `install_size.py`; `preferences.py:reset_app_data` reinicia os sweeps (`stop()`+`start()`) e cancela/rearma os managers assíncronos | leitura (guard) + suíte |
| M2 | Enter aplica no meio do fetch | `details_dialog.py:apply_preferences`, early-return com `_loading_ops` — o mesmo portão do botão | teste (`test_ui_logic`) |
| M3 | "Sobre" quebra com log ruim | `main.py:on_about_action`, try/except por arquivo + `errors="replace"` + `with`; log ilegível vira linha `[nome: ilegível]` | leitura |
| M4 | Avisos de vazio empilham | `window.py:set_library_child`, o aviso não-escolhido é removido sempre, não só no ramo sem aviso | teste (`test_ui_logic`, transição nos dois sentidos) |
| M5 | Tokenização apaga scripts não-latinos | `title_match.py`, `_NON_ALNUM_RE = [\W_]+` — kana/kanji/cirílico viram tokens; verificado ao vivo que "ペルソナ5" vs "ペルソナ5 スクランブル" caiu de 100 para 40 | teste (`test_title_match::TestNonLatinScripts`, 5 testes) |
| M6 | Adoção regrava sem atomicidade | `store.py`, `_dump_json_atomic` (tmp uuid + `replace`, idioma do FileManager) nos dois regravadores | teste (`test_store_index`, 2 testes) |
| M7 | TIFF órfão por capa escolhida | `save_cover.py`, ramo pixbuf embrulhado em try/finally que apaga o intermediário (mesmo conserto que o fallback já tinha) | leitura |
| M8 | Troca de capa destrói-antes-de-copiar | `save_cover.py:save_cover`, cópia para tmp no próprio diretório + `replace`; formas de outro sufixo só caem depois | teste (`test_save_cover`, novo arquivo, 3 testes) |
| M9 | Pickers pendurados no spinner | `steamgriddb.py`, `_data_list` valida shape (KeyError → `SgdbBadRequest`); `steam.py:283`, isinstance no payload; `logo_picker.py`/`sgdb_picker.py`, contador `_added` + `_finish_results` agendado depois dos adds — sem resultado materializado vira "Não foi possível carregar" | teste (`test_steamgriddb`, 2 testes de shape) + leitura (finalizador) |
| M10 | Vigília por pasta sem pré-filtro | `process_monitor.py:is_process_running_under`, `_PSEUDO_PIDS`/`_SYSTEM_PROCESS_NAMES` antes do `OpenProcess` — válido porque `_is_watchable_dir` exclui `%SystemRoot%` | teste (`test_process_monitor`) |

## Severidade baixa

| # | Achado | Onde está o conserto | Verificado por |
|---|---|---|---|
| B1 | `get_review_summary` AttributeError de shape | `steam.py`, isinstance antes do `.get` | leitura |
| B2 | Timestamp fora de faixa derruba o histórico | `session_log.py:load`, faixa além de tipo (`_MAX_END`, negativo) | teste (`test_session_log`) |
| B3 | UnicodeDecodeError escapa do load | `session_log.py`, `errors="replace"` — o byte ruim custa a linha | teste (`test_session_log`) |
| B4 | Tipo errado em campo numérico passa | `main.py`, `sanitize_numeric_fields` na carga (extraída para ser testável sem app) | teste (`test_ui_logic`) |
| B5 | Marcador AUMID case-sensitive | `run_executable.py`, `_MARKER_RE` IGNORECASE (regex, não casefold — posições no texto original) | teste (`test_run_executable`) |
| B6 | Guard anti-DOCTYPE contornável | `updates_feed.py`, `_prolog_end` anda o prólogo pulando comentários/PIs por inteiro; sem fechamento estende até o fim (erra recusando) | teste (`test_updates_feed::TestDoctypeGuard`, 4 testes) |
| B7 | HLTB sem teto de resposta | `hltb.py`, `_read_capped` (stream, 10 MiB, estouro = RequestException) nos três leitores + homepage em stream sem ler corpo | teste (`test_hltb::TestResponseCap`) |
| B8 | Logo sem teto de dimensão | `game_logo.py`, `MAX_SOURCE_DIMENSION = 4096` em três camadas: `_usable` (pula candidato), validação do fetch (descarta + sidecar), `load_logo` (recusa arquivo local) | teste (`test_game_logo`, 2 testes) |
| B9 | Busca dupla ao abrir picker | `_last_query` no debounce dos três pickers (logo, capa, Steam); Enter continua repetindo (caminho do activate) | leitura |
| B10 | Queda na rotação deixa sessão sem log | `session_file_handler.py`, guard de existência + `replace` no rename; `main.py`, fallback `basicConfig` no lugar do `pass` | teste (`test_ui_logic`) |
| B11 | Widgets removidos pinados | `display_manager.py`, ramo sem grade faz `game_covers.pop` + `release_picture`; desfazer volta pelo ramo de criação | leitura |
| B12 | CoverManager latente (temp + bloqueio) | `cover_manager.py`, temp criado depois do download; o bloqueio com sleep ficou como teto documentado (`ponytail:` no código — caminho morto neste fork, upgrade nomeado se reviver) | leitura |
| B13 | `Game` construído na worker thread | **Risco aceito e documentado** em `shortcuts_source.py:_make_game`: verificado tolerado no runtime, parenteado só na main; refazer o fluxo do importer por defeito nunca observado não compensa | leitura |
| B14 | `get_manifest_data` morto e frágil | **Removido** (`SteamFileHelper`, `SteamManifestData`, `SteamInvalidManifestError`) — sem chamadores | suíte |

## Higiene

| # | Achado | Resolução |
|---|---|---|
| H1 | HTML do Instagram no repositório | `git rm rodollfe-2023.html` |
| H2 | Spec doc descrevia o upstream | `docs/game_id.json.md` reescrito para o fork: spec 1.6, `PERSISTED_ATTRS` como fonte da verdade, todos os campos novos documentados, regras de carga e de edição à mão |

## Consertos de harness no caminho

- `tests/test_hltb.py`: `FakeResponse` ganhou `iter_content` e `get`/`post` aceitam `stream` —
  o B7 mudou o helper para stream e as 33 quebras eram o fake defasado (a mesma classe do F2
  de 01/08; a sugestão estrutural daquele relatório continua de pé).
- `main.py`: a sanitização de campos numéricos foi extraída para `sanitize_numeric_fields`
  (módulo, pura) para ser testável sem instanciar o aplicativo.

## O que não mudou de propósito

`shell=True` no launch (comando é config do usuário, validado a montante), o `cwd=home` do
launch, a arquitetura de managers herdada — nada disso era achado. A seção "Verificado e limpo"
da auditoria segue valendo como lista do que não re-flagar.
