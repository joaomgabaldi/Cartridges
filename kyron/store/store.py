# store.py
#
# Copyright 2023 Geoffrey Coulaud
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# SPDX-License-Identifier: GPL-3.0-or-later

import json
import logging
import re
import weakref
from pathlib import Path
from threading import RLock
from typing import Any, Generator, MutableMapping, Optional

from PySide6.QtCore import QObject, Qt, Signal

from kyron import shared
from kyron.conquistas import historico
from kyron.jogo import ANIMATED_SUFFIXES, Jogo
from kyron.store.managers.manager import Manager
from kyron.store.pipeline import Pipeline
from kyron.utils import copias_animadas, session_log
from kyron.utils.gravar_atomico import gravar_atomico
from kyron.utils.logo_arquivos import IMAGE_SUFFIXES, remove_logo
from kyron.utils.run_executable import aumid_from_command
from kyron.utils.wallhaven import IMAGE_SUFFIXES as WALLPAPER_SUFFIXES


def _path_key(path: str) -> str:
    """Caminho de atalho na forma única para comparar.

    Separadores: o interpretador da versão anterior (GTK, MSYS2) tinha `os.sep`/`os.altsep` invertidos, e o índice de âncora usa este valor como chave (divergir reimporta o jogo e apaga o registro antigo). Caixa: caminhos do Windows a ignoram.
    """
    return path.replace("/", "\\").casefold()


# O `start ""` (e o `/D "pasta"`) que a varredura de atalhos põe na frente do alvo.
_PREFIXO_START = re.compile(r'^start ""(?:\s+/D "[^"]*")?\s*', re.IGNORECASE)


def alvo_do_comando(comando: str) -> Optional[str]:
    """O caminho ou URI que um comando de abrir executa, sem argumentos; ``None`` sem alvo legível (o jogo nunca liga a atalho).

    Reconhece o jogo adicionado à mão no atalho que aponta para o mesmo executável.
    """
    return _partes_do_comando(comando)[0]


def argumentos_do_comando(comando: str) -> str:
    """O que vem depois do alvo, com os espaços normalizados ("" sem nada)."""
    return _partes_do_comando(comando)[1]


def _partes_do_comando(comando: str) -> tuple[Optional[str], str]:
    resto = _PREFIXO_START.sub("", comando.strip(), count=1)
    if resto.startswith('"'):
        fim = resto.find('"', 1)
        if fim <= 0:
            return None, ""
        return resto[1:fim] or None, " ".join(resto[fim + 1 :].split())
    return resto or None, ""


def _is_derived_command(game: Jogo) -> bool:
    """O comando de lançamento parece ter sido montado pelo importador?

    Vale para as duas formas de jogo empacotado (Store/Game Pass): o ``shell:AppsFolder`` do AUMID resolvido e o fallback que lança o próprio atalho. Só elas envelhecem sem a identidade mudar junto.
    """
    if aumid_from_command(game.executable):
        return True
    # Via `_path_key`: a varredura reescreve o comando mas não o caminho guardado, então uma biblioteca que trocou de interpretador tem um de cada convenção.
    return bool(game.shortcut_path) and _path_key(game.executable) == _path_key(
        f'start "" "{game.shortcut_path}"'
    )


def _dump_json_atomic(path: Path, data: dict, **dump_kwargs: Any) -> None:
    """Escreve via `gravar_atomico`, como o FileManager: uma queda no meio deixa só um ``.tmp`` órfão (o loader o ignora), não um JSON truncado."""
    gravar_atomico(path, json.dumps(data, **dump_kwargs))


def _migrate_game_files(old_id: str, new_id: str) -> None:
    """Move tudo o que está arquivado sob ``old_id`` para ``new_id``: JSON, capa, logo, papel de parede (imagem + registro da escolha) e cor da fita de LED.

    Melhor esforço: um arquivo que não move fica onde está, para não derrubar a adoção.
    """
    record = shared.games_dir / f"{new_id}.json"
    moves = [(shared.games_dir / f"{old_id}.json", record)]
    for suffix in (*ANIMATED_SUFFIXES, ".tiff"):
        moves.append(
            (shared.covers_dir / f"{old_id}{suffix}", shared.covers_dir / f"{new_id}{suffix}")
        )
    for suffix in (".json", *IMAGE_SUFFIXES):
        moves.append(
            (shared.logos_dir / f"{old_id}{suffix}", shared.logos_dir / f"{new_id}{suffix}")
        )
    for suffix in (".json", *WALLPAPER_SUFFIXES):
        moves.append(
            (
                shared.wallpapers_dir / f"{old_id}{suffix}",
                shared.wallpapers_dir / f"{new_id}{suffix}",
            )
        )

    moves.append(
        (shared.fitas_dir / f"{old_id}.json", shared.fitas_dir / f"{new_id}.json")
    )
    moves.extend(copias_animadas.pares_de_migracao(old_id, new_id))

    for source, dest in moves:
        try:
            if source.exists():
                source.replace(dest)
        except OSError as error:
            logging.warning("Could not move %s to %s: %s", source, dest, error)

    # O histórico de conquistas não está em `moves`: o `historico` é dono do arquivo e do lock.
    historico.mover(old_id, new_id)

    # O registro guarda o próprio id, e mover o arquivo não o muda. Feito aqui e não no `save()` do chamador porque isto roda antes de `legacy.game_id` ser trocado: um `save()` agora gravaria o id velho no arquivo já renomeado e a adoção se desfaria a cada abertura.
    # Só o id: `executable` e `shortcut_path` ficam velhos no disco numa tumba comum (nunca lançada), mas não num zerado, em que o ramo de reinstalação do `add_game` os mantém atuais (desmarcar "Zerado" decide a volta à biblioteca por eles).
    # O caminho velho pode casar, e o que evita problema é o `shortcut_mtime`, que a adoção não toca: atalho inalterado é o mesmo que a pessoa apagou (herda a tumba); um recriado tem mtime novo e volta pelo ramo de reinstalação.
    try:
        if record.exists():
            with record.open(encoding="utf-8") as file:
                data = json.load(file)
            if isinstance(data, dict) and data.get("game_id") != new_id:
                data["game_id"] = new_id
                _dump_json_atomic(record, data, indent=4, sort_keys=True)
    except (OSError, ValueError) as error:
        logging.warning("Could not restamp the record for %s: %s", new_id, error)

    # Os dois registros de como a imagem foi escolhida nomeiam o arquivo, então o rename acima tem de ser refletido neles; senão a imagem é baixada de novo (ou perdida, se escolhida à mão).
    for kind, sidecar in (
        ("logo", shared.logos_dir / f"{new_id}.json"),
        ("wallpaper", shared.wallpapers_dir / f"{new_id}.json"),
    ):
        try:
            if not sidecar.exists():
                continue
            with sidecar.open(encoding="utf-8") as file:
                data = json.load(file)
            if not isinstance(data, dict) or not data.get("file"):
                continue
            data["file"] = str(data["file"]).replace(old_id, new_id, 1)
            _dump_json_atomic(sidecar, data)
        except (OSError, ValueError) as error:
            logging.warning("Could not update the %s record for %s: %s", kind, new_id, error)

    # As sessões também são arquivadas pelo id: sem isto o histórico ficava preso ao id antigo.
    session_log.mover_jogo(old_id, new_id)


class Store(QObject):

    # Emitidos também das threads do importador: quem mexe na tela conecta com a conexão automática (enfileirada na principal).
    # Um jogo saiu da store e dos arquivos: a janela fecha o aviso de desfazer a remoção dele.
    jogo_excluido = Signal(str)
    # (id antigo, id novo) de um jogo adotado: a grade troca a chave da capa
    # dele e a recarrega do arquivo, que mudou de nome junto.
    capa_trocou_de_id = Signal(str, str)

    managers: dict[type[Manager], Manager]
    pipeline_managers: set[Manager]
    source_games: MutableMapping[str, MutableMapping[str, Jogo]]
    # game_id -> Jogo, em sincronia com source_games: busca por id em O(1).
    games_by_id: dict[str, Jogo]
    # None marks a path more than one record claims: see `_index_shortcut`
    _games_by_shortcut: dict[tuple[str, str], Optional[Jogo]]
    new_game_ids: set[str]
    duplicate_game_ids: set[str]

    def __init__(self) -> None:
        super().__init__()
        self.managers = {}
        self.pipeline_managers = set()
        self.source_games = {}
        self.games_by_id = {}
        self.new_game_ids = set()
        self.duplicate_game_ids = set()
        # (fonte base, caminho do atalho) -> Jogo: a âncora de `adopt_legacy_game`, indexada para não varrer a biblioteca a cada jogo importado.
        self._games_by_shortcut = {}
        # O `add_game` roda nas threads da importação enquanto a principal percorre a store; um `for game in store` direto levantava "dictionary changed size during iteration" e matava a varredura de atualizações.
        self._lock = RLock()

    def __contains__(self, obj: object) -> bool:
        if not isinstance(obj, Jogo):
            return False
        with self._lock:
            if not (source_mapping := self.source_games.get(obj.base_source)):
                return False
            return obj.game_id in source_mapping

    def __iter__(self) -> Generator[Jogo, None, None]:
        """Itera sobre um instantâneo: segurar o lock no laço travaria quem abandona o gerador ou chama a store de dentro dele, e o trabalho por jogo é a janela em que uma importação invalidaria um iterador vivo."""
        with self._lock:
            games = [
                game
                for games_mapping in self.source_games.values()
                for game in games_mapping.values()
            ]
        yield from games

    def __len__(self) -> int:
        with self._lock:
            return sum(
                len(source_mapping) for source_mapping in self.source_games.values()
            )

    def __getitem__(self, game_id: str) -> Jogo:
        try:
            return self.games_by_id[game_id]
        except KeyError:
            raise KeyError("Game not found in store") from None

    def clear(self) -> None:
        with self._lock:
            self.source_games = {}
            self.games_by_id = {}
            self._games_by_shortcut = {}

    def get(self, game_id: str, default: Any = None) -> Jogo | Any:
        try:
            game = self[game_id]
            return game
        except KeyError:
            return default

    def proximo_id_importado(self) -> str:
        """O próximo ``imported_N`` livre: o id de um jogo que não veio de
        fonte nenhuma (adicionado à mão, ou um zerado recriado pelo backup)."""
        with self._lock:
            ids = list(self.source_games.get("imported", {}))
        numbers = [0]
        for game_id in ids:
            if not game_id.startswith("imported_"):
                continue
            # Ignora ids de sufixo não numérico (JSON corrompido) em vez de quebrar.
            try:
                numbers.append(int(game_id.replace("imported_", "", 1)))
            except ValueError:
                continue
        return f"imported_{max(numbers) + 1}"

    def add_manager(self, manager: Manager, in_pipeline: bool = True) -> None:
        manager_type = type(manager)
        self.managers[manager_type] = manager
        self.toggle_manager_in_pipelines(manager_type, in_pipeline)

    def toggle_manager_in_pipelines(
        self, manager_type: type[Manager], enable: bool
    ) -> None:
        if enable:
            self.pipeline_managers.add(self.managers[manager_type])
        else:
            self.pipeline_managers.discard(self.managers[manager_type])

    def excluir(self, game: Jogo, apagar_sessoes: bool = True) -> None:
        """Apaga um zerado: arquivos, sessões e o lugar dele na store.

        Sem tumba (ao contrário do "Remover"): um zerado reinstalado tem atalho na pasta, e o próximo import o traz de volta como jogo vivo novo. ``apagar_sessoes=False`` é a ligação por appID (`ligacao_zerado`), em que as sessões já mudaram de dono.
        """
        with self._lock:
            self.source_games.get(game.base_source, {}).pop(game.game_id, None)
            self.games_by_id.pop(game.game_id, None)
            if game.shortcut_path:
                key = (game.base_source, _path_key(game.shortcut_path))
                if self._games_by_shortcut.get(key) is game:
                    del self._games_by_shortcut[key]
        self.cleanup_game(game, apagar_sessoes=apagar_sessoes)
        # Aqui e não em `cleanup_game`, que também roda na reinstalação (`add_game`); o histórico de conquistas só some com o Excluir.
        historico.apagar(game.game_id)

    def cleanup_game(self, game: Jogo, apagar_sessoes: bool = True) -> None:
        # A capa pode ser .tiff parado ou animada (.gif/.webp/.apng). O papel de parede da sessão e a cor da fita também são por id: deixados, um jogo reinstalado herdaria as escolhas fixas do removido.
        for path in (
            shared.games_dir / f"{game.game_id}.json",
            *(
                shared.covers_dir / f"{game.game_id}{suffix}"
                for suffix in (*ANIMATED_SUFFIXES, ".tiff")
            ),
            shared.wallpapers_dir / f"{game.game_id}.json",
            *(
                shared.wallpapers_dir / f"{game.game_id}{suffix}"
                for suffix in WALLPAPER_SUFFIXES
            ),
            shared.fitas_dir / f"{game.game_id}.json",
        ):
            path.unlink(missing_ok=True)

        remove_logo(game.game_id)

        copias_animadas.apagar(game.game_id)

        # Um jogo reinstalado com o mesmo id não pode herdar as sessões do apagado (exceto na ligação por appID, em que elas já mudaram de dono).
        if apagar_sessoes:
            session_log.apagar_jogo(game.game_id)

        # Roda numa thread do importador: a janela recebe isto enfileirado.
        self.jogo_excluido.emit(game.game_id)

    @staticmethod
    def _refresh_derived_executable(stored_game: Jogo, game: Jogo) -> bool:
        """Adota o comando de lançamento relido quando o guardado foi gerado pelo importador.

        Um duplicado normalmente é ignorado: o comando é a identidade (o atalho clássico faz hash de ``alvo|argumentos``). Jogos empacotados (Store/Game Pass) são a exceção: a identidade é o AUMID do atalho, mas o comando vem do AUMID que o Menu Iniciar resolve, e pode envelhecer sozinho; nada mais o corrigiria.

        Só um comando com cara de gerado é trocado (um escrito à mão com a mesma forma também é revertido). As duas formas valem: o fallback que lança o .lnk não tem AUMID, e testar só o AUMID tornava o fallback permanente após um `Get-StartApps` incompleto.

        O teste de igualdade abaixo é a guarda mais forte: não o "simplifique".
        """
        if stored_game.executable == game.executable:
            return False
        if not _is_derived_command(stored_game):
            return False
        logging.info(
            "Updating the launch command for %s (%s)", game.name, game.game_id
        )
        stored_game.executable = game.executable
        stored_game.inis = None  # os .ini da pasta antiga não valem: o próximo play procura de novo
        return True

    def _index_shortcut(self, game: Jogo) -> None:
        """Registra o jogo sob o atalho de origem (chamador segura o lock).

        Uma chave reclamada por dois registros é envenenada (None) em vez de resolvida: a âncora autoriza mover o save de um jogo para outro id, então uma resposta ambígua tem de ser nenhuma. Trocar o registro do mesmo id não é colisão (reinstalação trocando a tumba). Envenenar não é permanente: `_reindex_shortcut` limpa a chave quando um registro sai.

        Um jogo vivo ao lado de uma tumba no mesmo atalho não é ambíguo (resto de um jogo reimportado com outro id): o vivo fica com a chave em qualquer ordem de chegada. Dois vivos ainda envenenam. Uma tumba sozinha continua indexada, para o jogo removido de propósito não ressuscitar sob novo id. `removed` é lido do objeto guardado, pois `remove_games` o altera no lugar.
        """
        if not game.shortcut_path:
            return
        key = (game.base_source, _path_key(game.shortcut_path))
        if key in self._games_by_shortcut:
            existing = self._games_by_shortcut[key]
            if existing is None:
                return  # contested; a second claimant does not settle it
            if existing.game_id != game.game_id:
                if existing.removed == game.removed:
                    self._games_by_shortcut[key] = None
                    return
                if game.removed:
                    return  # the live record already there keeps the key
        self._games_by_shortcut[key] = game

    def _reindex_shortcut(self, game: Jogo, shortcut_path: str) -> None:
        """Move ``game`` para um novo caminho de atalho, índice incluído (chamador segura o lock).

        A chave nova passa por `_index_shortcut`, que envenena um caminho já reclamado.
        """
        self._games_by_shortcut.pop(
            (game.base_source, _path_key(game.shortcut_path)), None
        )
        game.shortcut_path = shortcut_path
        self._index_shortcut(game)

    def apontar_atalho(self, game: Jogo, shortcut_path: str) -> None:
        """Faz ``game`` reclamar o atalho em ``shortcut_path`` (escolha manual na janela de pendências da restauração).

        A próxima varredura o acha por esse caminho (a âncora) e o adota sob o id do atalho."""
        with self._lock:
            self._reindex_shortcut(game, shortcut_path)
        game.save()

    def adopt_legacy_game(self, game: Jogo) -> Optional[Jogo]:
        """Reaproveita um jogo guardado sob o id de ``game``, mantendo tudo o que ele tem; devolve o adotado ou None.

        O id é um hash da identidade, então mudar a identidade renomeia o jogo, que o app vê como um novo mais um sumido (o sumido é removido com tempo de jogo, capa, logo e acompanhamento). O atalho reconhece o mesmo jogo: mesma fonte, mesmo caminho. Atalho só renomeado mantém o id (o ramo de duplicado pega o caminho novo); renomeado *e* reapontado na mesma janela perde o registro.

        A âncora é opt-in (``identity_anchor`` nos dados adicionais, lido pelo `add_game`) e só uma fonte que varre a define: carregar do disco poderia ler dois registros do mesmo atalho (um velho e o substituto) como "o mesmo jogo" e fundir os saves na abertura.
        """
        if not game.shortcut_path:
            return None
        with self._lock:
            legacy = self._games_by_shortcut.get(
                (game.base_source, _path_key(game.shortcut_path))
            )
            if legacy is None or legacy.game_id == game.game_id:
                return None
            legacy_id = legacy.game_id
            # O índice pode nomear um registro que a store já largou (uma tumba trocada por reinstalação sob outro caminho): o `game_id` dele é o do registro *vivo*, e migrá-lo moveria o save de um jogo vivo para este. Só adota o que a store ainda guarda.
            if self.games_by_id.get(legacy_id) is not legacy:
                logging.debug("Ignoring a stale anchor for %s", legacy_id)
                return None

        return self._adotar(legacy, game)

    def adotar_manual(self, game: Jogo, alvo: str) -> Optional[Jogo]:
        """Faz o atalho achado pela varredura assumir o jogo adicionado à mão que abre o mesmo alvo, em vez de importar um segundo.

        Só um jogo da biblioteca (não removido nem na lista negra) e único com esse alvo: dois candidatos é chute, e a adoção move histórico entre ids.
        """
        candidato = self._candidato_manual(game, alvo)
        return self._adotar(candidato, game) if candidato is not None else None

    def _candidato_manual(self, game: Jogo, alvo: str) -> Optional[Jogo]:
        chave = _path_key(alvo)
        # Argumentos no atalho escolhem o que o alvo abre: o atalho de um jogo
        # de RetroArch não é o RetroArch que a pessoa adicionou à mão.
        argumentos = argumentos_do_comando(game.executable)
        with self._lock:
            candidatos = [
                jogo
                for jogo in self.games_by_id.values()
                if jogo.source == "imported"
                and not jogo.removed
                and not jogo.blacklisted
                and (alvo_do_jogo := alvo_do_comando(jogo.executable))
                and _path_key(alvo_do_jogo) == chave
                and argumentos in ("", argumentos_do_comando(jogo.executable))
            ]
        return candidatos[0] if len(candidatos) == 1 else None

    def _adotar(self, legacy: Jogo, game: Jogo) -> Jogo:
        legacy_id = legacy.game_id

        # Fora do lock de propósito: são uns doze arquivos, e a thread principal espera por esse lock; uma fonte é varrida por um só worker.
        logging.info("Adopting %s as %s (was %s)", legacy.name, game.game_id, legacy_id)
        _migrate_game_files(legacy_id, game.game_id)

        with self._lock:
            if (mapping := self.source_games.get(legacy.base_source)) is not None:
                mapping.pop(legacy_id, None)
            self.source_games.setdefault(game.base_source, {})[game.game_id] = legacy
            self.games_by_id.pop(legacy_id, None)
            self.games_by_id[game.game_id] = legacy

            # O comando é a razão de a identidade ter mudado: o resolvido agora é mais atual que o do disco. Antes do id, para ninguém ver o id novo com o comando velho.
            legacy.executable = game.executable
            # Um jogo adicionado à mão passa a ser do atalho. A adoção pela
            # âncora nunca chega aqui (a fonte é a mesma) e não toca no mtime.
            if legacy.source != game.source:
                legacy.source = game.source
                legacy.base_source = game.base_source
                legacy.shortcut_mtime = game.shortcut_mtime
            legacy.game_id = game.game_id
            # Retira a chave antiga: a âncora autoriza migrar arquivos, e outro jogo que importasse do nome liberado acharia este e levaria seu save, capa e logo.
            self._reindex_shortcut(legacy, game.shortcut_path)

        # O widget da capa também é guardado por id e a grade faz read-modify-write nesse mapa na thread principal, então a troca de chave acontece lá.
        # O arquivo da capa mudou junto: com o nome velho, o blur caía no placeholder e a animação sumia até reiniciar.
        self.capa_trocou_de_id.emit(legacy_id, game.game_id)

        legacy.save()
        return legacy

    def _conectar_managers(self, game: Jogo) -> None:
        """Liga cada sinal que um manager escuta (`salvar`, `atualizado`) ao `run` dele.

        Conexão direta: o manager roda na thread que emitiu (pode ser um worker sem laço de eventos). A referência fraca evita o ciclo jogo → conexão → lambda → jogo, invisível ao coletor do lado C++, que prenderia todo jogo excluído.
        """
        ref = weakref.ref(game)
        for manager in self.managers.values():
            for signal in manager.signals:
                getattr(game, signal).connect(
                    lambda m=manager: (g := ref()) is not None and m.run(g, {}),
                    Qt.ConnectionType.DirectConnection,
                )

    def add_game(
        self, game: Jogo, additional_data: dict, run_pipeline: bool = True
    ) -> Optional[Pipeline]:

        if game.version > shared.SPEC_VERSION:
            return None

        stored_game = self.get(game.game_id)

        # Nada sob este id, mas o atalho pode já estar arquivado sob outro: adota em vez de importar um duplicado que `remove_games` apagaria.
        if stored_game is None and additional_data.get("identity_anchor"):
            stored_game = self.adopt_legacy_game(game)
        # Nem pelo id nem pela âncora: pode ser o atalho de um jogo que a
        # pessoa adicionou à mão antes.
        if (
            stored_game is None
            and additional_data.get("identity_anchor")
            and additional_data.get("alvo")
        ):
            stored_game = self.adotar_manual(game, additional_data["alvo"])
        # O id cai num jogo excluído do mesmo atalho (o arquivo, com a mesma
        # data, volta a ser só ignorado). Se a pessoa já o adicionou à mão de
        # novo, é esse que vale: o excluído sai, como na reinstalação.
        elif (
            stored_game is not None
            and stored_game.removed
            and not stored_game.blacklisted
            and not stored_game.zerado
            and additional_data.get("identity_anchor")
            and additional_data.get("alvo")
            and (candidato := self._candidato_manual(game, additional_data["alvo"]))
        ):
            self.cleanup_game(stored_game)
            stored_game = self._adotar(candidato, game)

        # Jogo removido lido do disco fica como tumba: continua na store (as varreduras sabem que foi removido), mas não passa pelo pipeline, o que impede o atalho ainda presente de recriar um jogo excluído.
        # Fica conectada aos managers como um jogo vivo: o save() e o update() de um zerado precisam chegar ao disco e à tela.
        if game.removed:
            if not stored_game:
                with self._lock:
                    self.source_games.setdefault(game.base_source, {})[
                        game.game_id
                    ] = game
                    self.games_by_id[game.game_id] = game
                    self._index_shortcut(game)
                self._conectar_managers(game)
                if game.zerado:
                    game.update()
            return None

        if not stored_game:
            logging.debug("New store game %s (%s)", game.name, game.game_id)
            self.new_game_ids.add(game.game_id)
        elif stored_game.removed:
            with self._lock:
                # A thread principal pode ter excluído, ligado ou marcado esta tumba
                # desde que ela foi lida. Age só sobre o que ainda está na store.
                ainda_la = self.games_by_id.get(game.game_id) is stored_game
                era_zerado = stored_game.zerado
            if not ainda_la:
                self.duplicate_game_ids.add(game.game_id)
                return None
            # Um zerado reinstalado continua zerado até a pessoa desmarcar; o atalho novo só é anotado (desmarcar decide a volta à biblioteca por ele). `era_zerado` e não `stored_game.zerado` de novo, porque o seletor pode ter marcado a tumba nesse meio-tempo.
            if era_zerado:
                caminho_sumiu = bool(stored_game.shortcut_path) and not Path(
                    stored_game.shortcut_path
                ).is_file()
                if game.shortcut_mtime > stored_game.shortcut_mtime or (
                    caminho_sumiu and game.shortcut_path
                ):
                    stored_game.executable = game.executable
                    stored_game.shortcut_mtime = game.shortcut_mtime
                    if (
                        game.shortcut_path
                        and game.shortcut_path != stored_game.shortcut_path
                    ):
                        with self._lock:
                            self._reindex_shortcut(stored_game, game.shortcut_path)
                    stored_game.save()
                self.duplicate_game_ids.add(game.game_id)
                return None
            # Casa com uma tumba: o jogo só volta se este atalho for mais novo que o removido (reinstalação); senão é o mesmo atalho ainda na pasta e a importação é ignorada.
            if game.shortcut_mtime <= stored_game.shortcut_mtime:
                logging.debug("Ignoring removed game %s (%s)", game.name, game.game_id)
                self.duplicate_game_ids.add(game.game_id)
                return None
            logging.debug(
                "Reinstall detected, restoring %s (%s)", game.name, game.game_id
            )
            self.cleanup_game(stored_game)
            self.new_game_ids.add(game.game_id)
        else:
            # Duplicado, ignorado; mantém o mtime do atalho atual para a tumba refletir o arquivo real (só mudança futura conta como reinstalação).
            changed = False
            if game.shortcut_mtime > stored_game.shortcut_mtime:
                stored_game.shortcut_mtime = game.shortcut_mtime
                changed = True
            # Antes do renome abaixo, e a ordem importa: `_is_derived_command` compara o comando de fallback com o caminho do atalho; renomear antes tiraria o chão da comparação e deixaria o jogo preso num arquivo inexistente.
            if self._refresh_derived_executable(stored_game, game):
                changed = True
            # Acompanha um atalho renomeado: não muda a identidade nesta fonte, então o renome cai neste ramo; sem isso o registro nomeava um arquivo inexistente e o índice da âncora um nome liberado.
            # Só se o caminho guardado sumiu: dois atalhos para o mesmo jogo (Menu Iniciar varrido recursivamente) são duplicados, não renome, e disputariam o registro a cada varredura.
            if (
                game.shortcut_path
                and game.shortcut_path != stored_game.shortcut_path
                and not (
                    stored_game.shortcut_path
                    and Path(stored_game.shortcut_path).exists()
                )
            ):
                with self._lock:
                    self._reindex_shortcut(stored_game, game.shortcut_path)
                changed = True
            # Retoma a chave se estiver livre: uma chave disputada fica envenenada, mas quando um dos dois sai `_reindex_shortcut` apaga o que ela guardava, e o registro que ficou seria só duplicado dali em diante (nunca indexa), deixando a âncora indisponível até a próxima abertura.
            # Seguro porque `_index_shortcut` decide: chave ausente é reclamada, envenenada continua, o mesmo id é reafirmado.
            with self._lock:
                self._index_shortcut(stored_game)
            if changed:
                stored_game.save()
            logging.debug("Duplicate store game %s (%s)", game.name, game.game_id)
            self.duplicate_game_ids.add(game.game_id)
            return None

        self._conectar_managers(game)

        with self._lock:
            if not game.base_source in self.source_games:
                self.source_games[game.base_source] = {}
            self.source_games[game.base_source][game.game_id] = game
            self.games_by_id[game.game_id] = game
            self._index_shortcut(game)

        # O pipeline não é retido pela Store: quem o mantém vivo são o `game_pipelines` do Importer e, na carga inicial, a tarefa em andamento; guardá-los prenderia todo jogo na memória (removidos e resetados inclusive).
        if not run_pipeline:
            return None
        pipeline = Pipeline(game, additional_data, self.pipeline_managers)
        # Conectado antes de `advance()`: um pipeline sem manager que espere pode terminar dentro dele.
        # Direta (a conexão automática enfileiraria na thread de um worker sem laço de eventos) e com referência fraca (a lambda presa ao lado C++ seguraria o pipeline e o jogo).
        ref = weakref.ref(pipeline)
        pipeline.advanced.connect(
            lambda: (p := ref()) is not None and self._ao_avancar_pipeline(p),
            Qt.ConnectionType.DirectConnection,
        )
        pipeline.advance()
        return pipeline

    @staticmethod
    def _ao_avancar_pipeline(pipeline: Pipeline) -> None:
        """Liga um zerado pendente só quando o pipeline inteiro termina.

        O `SteamAPIManager.main` só marca `additional_data["ligar_zerado"]`; a ligação espera o SGDB (depois do Steam, `run_after`), cujo download sobrescreveria a capa copiada do zerado. Roda em qualquer thread, como o `Importer`.
        """
        if not pipeline.is_done or not pipeline.additional_data.get("ligar_zerado"):
            return
        from kyron.utils import ligacao_zerado  # noqa: PLC0415

        ligacao_zerado.agendar(pipeline.game)
