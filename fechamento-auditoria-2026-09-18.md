# Cartridges — fechamento da auditoria de 18/09/2026

Fecha os 55 achados de `auditoria-cartridges-2026-09-18.md`. Versão **2026.09.19**.

## Resultado

- **Suíte:** **921 testes + 3.241 subtests** verdes no runtime real (MSYS2 ucrt64), com 1 skip
  ambiental (symlink exige privilégio). Antes eram 830.
- **Testes novos:** vão em `tests/test_auditoria_0918_{ui,fitas,store,importadores}.py`, um ou mais
  por achado de comportamento.
  - Para cada grupo, os arquivos de código foram revertidos ao HEAD e os testes novos falharam.
  - A exceção são os casos de controle, que devem passar nos dois estados.
- **Rede de verdade:** a suíte não faz mais nenhuma chamada (H1).
- **`tests/_unset`:** a pasta de segurança não é mais criada. O fixture `app_dirs` agora reaponta
  `fitas_dir` e `fitas_arquivo`.
- **Build:** reconfigurado; `shared.py`, `.iss` e metainfo saem em 2026.09.19, e o XML do metainfo é
  válido.

**Método:** quatro grupos em paralelo, cada um dono de um conjunto de arquivos sem sobreposição:

- sessão e janela;
- fitas e preferências;
- store, capas e detalhes;
- importadores e rede.

Build, instalador, conftest, versão e este documento ficaram com o coordenador.

**Pedem revisão com atenção:**

- **M11:** mexe numa fronteira de segurança.
- **A3 e B2:** mudam o fluxo das fitas.
- **M12:** remove um módulo.

## Altos

| ID | Conserto | Teste |
|---|---|---|
| A1 | `shortcuts_source.py`: alvo com cara de caminho absoluto (`X:\`, `\\srv`) que não existe no disco mantém a identidade `target\|args` e o comando clássico. Só alvo com esquema é URI. Atalho com AUMID continua no ramo dele. | `test_a1_alvo_ausente_mantem_identidade_e_comando`, `test_a1_alvo_com_esquema_continua_uri` |
| A2 | `steamgriddb.py`: "já tem capa" olha `(*ANIMATED_SUFFIXES, ".tiff")`. | `test_a2_webp_existente_nao_e_sobrescrita` |
| A3 | `session_fita.py` (ver detalhes abaixo). | `test_a3_*` (4) |

**Detalhes do A3:**

- `abrir()` passou a ser só do arranque do app.
- O novo `reacender()` é o que as Preferências chamam no interruptor e ao fechar o assistente. Ele
  não desfaz órfão e só lê as fitas que faltam na chave.
- O fechamento chama `retomar()` antes de devolver e pega a `_TRAVA_ARRANQUE` com o prazo do
  fechamento.
- O arranque pinta só as fitas cujo estado ficou na chave e nunca grava `"{}"`.
- `devolver_removidas` também pega a trava.

## Médios

| ID | Conserto | Teste |
|---|---|---|
| M1 | O bloqueador deixa o `navigation_view` insensível e põe o foco em "Já terminei"; o `hide` desfaz. Delete fica desligado durante a sessão. Provado com teclas simuladas. | `test_m1_o_bloqueador_barra_o_teclado` |
| M2 | `remove_game_details_view` fica habilitada só com os detalhes visíveis e sem sessão. Ctrl+Z com o foco num campo de texto usa o desfazer do campo. | `test_m2_delete_so_vale_com_os_detalhes_a_vista`, `test_m2_ctrl_z_num_campo_desfaz_a_digitacao` |
| M3 | `importer.forget_undo` zera importados e removidos quando o aviso de resumo some. | `test_m3_o_desfazer_da_importacao_morre_com_o_aviso` |
| M4 | O `fall_back` não chama mais `hide_session_blocker`. `show_session_blocker` sai cedo quando é o mesmo jogo com o bloqueador visível. | `test_m4_*` (2) |
| M5 | `do_shutdown` grava a sessão no histórico depois do `flush` (a `ProcessSession` só se `started`). | `test_m5_fechar_o_app_grava_a_sessao_no_historico` |
| M6 | Intervalo maior que `MAX_GAP` (um intervalo + 30 s) credita só um intervalo, em `ProcessSession` e `SessionWindow`. | `test_m6_*` (2) |
| M7 | Abaixo de `Program Files` / `Program Files (x86)`, a raiz do jogo é o segundo nível. | `test_m7_pasta_de_editora_nao_e_pasta_de_jogo` |
| M8 | `update()` do lote SGDB só roda se `store.get(id) is game`. `SgdbManager` captura o cancellable ao enfileirar. | `test_m8_*` (2) |
| M9 | O reset apaga os arquivos de `wallpapers\` (menos `cache`) e de `fitas\` (menos `fitas.json`). `cleanup_game` apaga os sidecars de parede e de fita do jogo. | `test_m9_reset_apaga_…`, `test_m9_cleanup_game_apaga_parede_e_fita` |
| M10 | `sanitize_numeric_fields` virou `sanitize_game_fields` e valida número, texto, booleano e lista; `null` só vale onde o padrão é `None`. A carga tem um try por arquivo. | `test_m10_tipo_errado_custa_o_campo_e_nao_a_janela` |
| M11 | `args_safe` acompanha as aspas (ver detalhes abaixo). | `test_m11_*` (4) |
| M12 | **Removido:** `steam_applist.py` e os testes dele saíram. `find_candidates` só usa a busca da loja. Não havia chave de gschema ligada. | `test_m12_busca_sem_confianca_faz_so_a_busca_da_loja` |
| M13 | `_migrate_game_files` move também `fitas\<id>.json`. | `test_m13_adocao_leva_a_cor_da_fita` |
| M14 | O `sensitive` saiu da página. O grupo de papel de parede ganhou o bind no `.blp`, e o de monitor em Python, só quando há segundo monitor, para não brigar com o bloqueio de monitor. | `test_m14_sem_contar_horas_as_fitas_seguem_configuraveis` |

**Detalhes do M11:**

- `&|<>^()` só são aceitos dentro de aspas, e as aspas precisam estar balanceadas.
- `%`, `!` e caracteres de controle são recusados sempre.
- 16 cargas de injeção são recusadas.
- Um teste com o cmd.exe real prova duas coisas:
  - as cargas aceitas não executam nada;
  - as recusadas executariam, o que mostra que o teste detecta uma injeção de verdade.

## Baixos

| ID | Conserto | Teste |
|---|---|---|
| B1 | Com uma sessão aberta, `_ask` reagenda a pergunta a cada 60 s. | `test_b1_…` |
| B2 | `_reservar()` tira a geração na thread de UI dentro de `comecar`/`voltar`. | `test_b2_ja_terminei_rapido_vence_a_cor_do_jogo` |
| B3 | `_descartar(fita, modulo)` roda com a trava e só remove a conexão que ainda for a guardada. O batimento reconfere a conexão com a trava. | `test_b3_…` |
| B4 | A versão da varredura é gravada, e a consulta aceita resposta cmd 10 e 16. IP continua fixo. | `test_b4_…` |
| B5 | `_spotlight_ligado()`: `DesktopSpotlight\Settings\EnabledState == 1` ou `Wallpapers\BackgroundType == 3`; com o Spotlight ligado, o papel de parede não é tocado. **Falta:** ligar o Spotlight uma vez e reler as chaves (não liguei para não trocar o papel de parede sem pedir). | `test_b5_*` (3) |
| B6 | Só um comentário registrando o risco em `INSTALLER_ARGUMENTS`. Continua pendente: um teste de ponta a ponta do atualizador com as fitas ligadas. | — |
| B7 | tmp+replace no sidecar do papel de parede (com `mkdir` dentro do `try`), no sidecar do logo e no backup exportado. | `test_b7_*` (4) |
| B8 | `restore_into` trata `OverflowError`, e `import_backup` pula as lápides. | `test_b8_backup_com_infinito_e_lapide` |
| B9 | `convert_cover` devolve `None` em `DecompressionBombError`, sem recursão. O seletor de papel de parede trata a exceção e sai do spinner. | `test_b9_*` (2) |
| B10 | `_logo_tmp`/`_cover_tmp` com `_discard_tmp`; o `logo_picker` fecha o fluxo do `new_tmp`. | `test_b10_*` (2) |
| B11 | Contador `_generation` em `HLTBBackfill` e `InstallSizeSweep`. | `test_b11_*` (2) |
| B12 | `_apply` volta sem gravar se o jogo já tem tempos. | `test_b12_…` |
| B13 | `_frames_decoded` compara a geração, não o caminho. Um `OSError` do `save_cover` é logado e o Aplicar salva o resto. | `test_b13_*` (2) |
| B14 | `rekey_cover` aponta o `GameCover` para o arquivo do id novo. | `test_b14_…` |
| B15 | Sidecar de cor com tipo errado vale a cor automática. | `test_b15_…` |
| B16 | Pasta ausente ou vazia zera o tamanho sem carimbar, e remede na próxima execução. | `test_b16_…` |
| B17 | `session_log.delete` lê e grava com `surrogateescape`. | `test_b17_…` |
| B18 | Caminho elevado: `/c "<comando>"`. | `test_b18_…` |
| B19 | `os.walk` podando junções no lugar de `rglob`. Testado com `mklink /J` de verdade. | `test_b19_…` |
| B20 | Resolvido pela remoção do M12. | — |
| B21 | `search_store` só deixa passar itens com `id` inteiro. | `test_b21_…` |
| B22 | `get_game_id` do SGDB ordena por `rank_candidates`; sequência ou título sem relação vira não encontrado. | `test_b22_…` |
| B23 | `.url` que não é UTF-8 é lido em `mbcs`. | `test_b23_…` |
| B24 | "manual", "support" e "benchmark" só derrubam o atalho quando são a última palavra do nome. | `test_b24_…` |
| B25 | `read_capped`/`get_capped` em `utils/download.py`, com teto de 10 MiB. Usados por Steam (4 pedidos), SGDB (5), wallhaven e HLTB. O instalador tem teto de `release.size`, ou 512 MB quando o tamanho vem zerado. | `test_b25_*` (4) |
| B26 | Uma busca que falhou emite `poll-finished(False)`. | `test_b26_…` |
| B27 | Mês e ano comparados pelo calendário. | `test_b27_…` (3 casos) |
| B28 | `_closed` e saída cedo em `_fetch_metadata_choose`/`_fetch_metadata_done`. | `test_b28_…` |
| B29 | O spinner volta em `_on_steam_picked`. | `test_b29_…` |
| B30 | A mensagem do `build-installer.ps1` manda atualizar a trava à mão (DLL + `patched-gtk.txt`), como diz o README. | — |
| B31 | Comentário no `.iss` registrando o limite do desinstalador para todos os usuários. | — |

## Higiene

| ID | Conserto |
|---|---|
| H1 | Fixture `no_hltb_lookup` nos três testes que chamam `_fetch_metadata_done`. |
| H2 | O `build-installer.ps1` apaga `site-packages\cartridges` do prefixo antes do `meson install`, e o `.iss` ganhou `[InstallDelete]` desse diretório. |
| H3 | `data/gtk/style-dark.css` apagado. |
| H4 | O `meson.build` exige libadwaita ≥ 1.8. |
| H5 | O `Location` saiu. Fica só `UnresolvableLocationError`, que é o contrato de "fonte sem arquivos" que o importador captura. |
| H6 | Spec do atualizador; `game_id.json.md` (`wallpapers\`, `fitas\`, regra de tipos); `shared.pyi`; comentários das fitas e do assistente; "roxo" virou "cor do app"; `process_session.py`; ADR 0001 (o fechamento tenta as suspensas); spec das fitas (nota de revisão); comentário do debounce do `steam_picker`. |
| H7 | "Tente outra busca ou outro filtro"; apagar sessão com "Cancelar" e "Apagar" destrutivo (`create_dialog(destructive=)`); título de falha de leitura no seletor de papel de parede. |

## O que ficou de fora de propósito

- **M1, atalhos com Ctrl:** Ctrl+N, Ctrl+I, Ctrl+vírgula e Ctrl+H ainda funcionam por trás do
  bloqueador. Nenhum é destrutivo. Desligá-los brigaria com o importador, que liga e desliga as
  mesmas ações.
- **B28, `update_cover_callback`:** fica sem a saída cedo. Ele sempre roda depois do Aplicar, e sair
  cedo deixaria o spinner do jogo eterno. O alerta dele abre sobre a janela principal, então não
  cria janela solta.
- **A1, segunda parte** (não sobrescrever `executable` na adoção quando há edição do usuário): o
  conserto de identidade elimina a adoção espúria que causava a perda. Não há marcador de "editado
  à mão" no registro para distinguir os casos.
- **"Testar" e prévia das fitas:** ainda pintam todas as fitas, inclusive uma sem estado guardado. É
  ação explícita do usuário. Pelo mesmo motivo do A3.3, uma fita nessa situação não é devolvida no
  fechamento.
- **Limite marcado com `ponytail:`:**
  - M7: um jogo instalado direto em `Program Files` com o exe dois níveis abaixo passa a vigiar só a
    subpasta.
  - B25: `get_capped` escreve em `response._content`, um atributo privado do requests.
