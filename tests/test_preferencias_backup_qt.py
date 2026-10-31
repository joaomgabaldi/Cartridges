# test_preferencias_backup_qt.py
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Backup da biblioteca e Zona de perigo nas Preferências (Task 7 do plano 8a, D80).

Os que tinham par no GTK vieram de `test_saves_ui.py` e de `test_redefinir.py` (mesmos nomes). Nada de verdade: o
Ludusavi é falso (`disponivel` trocado), o `exportar`/`validar` são falsos, o reinício só anota e o `FileDialog`
nunca abre (os slots recebem a URL).
"""

import gc
import threading
import time
import weakref
from pathlib import Path

import pytest
from PySide6.QtCore import QEventLoop, QTimer, QUrl
from PySide6.QtQml import QQmlComponent, QQmlEngine, QQmlExpression
from PySide6.QtQuick import QQuickItem

from cartridges import shared
from cartridges.modelos import backup_da_biblioteca as modulo
from cartridges.modelos.backup_da_biblioteca import BackupDasPreferencias
from cartridges.modelos.preferencias import Preferencias
from cartridges.saves import backup_de_saves, pasta
from cartridges.utils import backup, redefinir
from tests import apoio_aplicativo

QML = Path(__file__).resolve().parent.parent / "cartridges" / "qml"
AGUARDE = "Aguarde o fim do backup ou da restauração dos saves e tente novamente."
URL = QUrl.fromLocalFile("X:/backup.zip")


@pytest.fixture
def aplicativo(monkeypatch):
    return apoio_aplicativo.instalar(monkeypatch)


def _com_ludusavi(monkeypatch, disponivel=True):
    monkeypatch.setattr(backup_de_saves, "disponivel", lambda: disponivel)


@pytest.fixture
def modelo(app_qt, aplicativo, monkeypatch):  # noqa: ARG001
    _com_ludusavi(monkeypatch)
    m = BackupDasPreferencias(aplicativo.avisos)
    m.reler()
    return m


def _drenar(flush_idle, pronto, limite=5):
    fim = time.monotonic() + limite
    while time.monotonic() < fim:
        flush_idle()
        if pronto():
            return True
        time.sleep(0.01)
    return pronto()


def _sequencia(*valores):
    """Uma função que devolve cada valor na sua vez e repete o último."""
    restantes = list(valores)
    return lambda: restantes.pop(0) if len(restantes) > 1 else restantes[0]


# region A página (QML offscreen, só o `preferencias` no contexto)


def _achar(raiz, nome):
    pilha, vistos = [raiz], {}
    while pilha:
        atual = pilha.pop()
        if id(atual) in vistos:
            continue
        vistos[id(atual)] = atual  # guardar o objeto impede o reuso do id
        if atual.objectName() == nome:
            return atual
        pilha.extend(atual.children())
        if isinstance(atual, QQuickItem):
            pilha.extend(atual.childItems())
    return None


class _Pagina:
    def __init__(self, preferencias):
        self.motor = QQmlEngine()
        self.motor.rootContext().setContextProperty("preferencias", preferencias)
        componente = QQmlComponent(self.motor, QUrl.fromLocalFile(str(QML / "PaginaGeral.qml")))
        self.item = componente.create()
        assert self.item is not None, componente.errorString()
        self.componente = componente

    def achar(self, nome):
        objeto = _achar(self.item, nome)
        assert objeto is not None, f"sem objeto {nome!r}"
        return objeto

    def avaliar(self, objeto, expressao):
        return QQmlExpression(QQmlEngine.contextForObject(objeto), objeto, expressao).evaluate()[0]

    def visivel(self, nome):
        """Uma linha aparece pela regra e pelo filtro (o `visible` efetivo pede o polimento do layout, que sem janela não roda)."""
        objeto = self.achar(nome)
        if objeto.property("buscavel") is True:
            return objeto.property("aparece") is True and objeto.property("passaNoFiltro") is True
        return objeto.property("visible") is True


@pytest.fixture
def montar(app_qt, aplicativo, monkeypatch):  # noqa: ARG001
    """`montar(disponivel)` abre as Preferências e monta a página Geral sobre elas."""
    abertas, paginas = [], []

    def fazer(disponivel=True):
        _com_ludusavi(monkeypatch, disponivel)
        p = Preferencias(aplicativo.avisos, lambda: True)
        assert p.abrir()
        abertas.append(p)
        pagina = _Pagina(p)
        paginas.append(pagina)
        return p, pagina

    yield fazer
    for pagina in paginas:
        pagina.item.deleteLater()
        pagina.item = None
    for p in abertas:
        p.fechar()


def test_preferencias_sem_ludusavi_escondem_as_linhas(montar):
    p, pagina = montar(disponivel=False)
    assert p.backup.savesDisponiveis is False
    assert p.estado["savesDisponiveis"] is False
    assert not pagina.visivel("linhaPastaDosSaves")
    assert not pagina.visivel("linhaRestaurarSaves")
    # O resto do grupo continua.
    assert pagina.visivel("linhaExportarBackup") and pagina.visivel("linhaImportarBackup")


def test_preferencias_com_ludusavi_mostram_as_linhas(montar):
    p, pagina = montar()
    assert p.backup.savesDisponiveis is True
    assert p.estado["savesDisponiveis"] is True
    assert pagina.visivel("linhaPastaDosSaves")
    assert pagina.visivel("linhaRestaurarSaves")
    assert pagina.achar("linhaPastaDosSaves").property("subtitulo") == str(pasta.atual()).replace("/", "\\")


def test_subtitulo_da_pasta_dos_saves_no_formato_do_windows_e_com_e_comercial(montar):
    """O `&` e o `/` do caminho aparecem como o Windows os mostra, em texto puro (Review Focus 3)."""
    shared.schema.set_string("pasta-dos-saves", "D:/Saves & Cia")
    _p, pagina = montar()
    linha = pagina.achar("linhaPastaDosSaves")
    assert linha.property("subtitulo") == r"D:\Saves & Cia"
    assert pagina.avaliar(pagina.achar("linhaPastaDosSavesSubtitulo"), "textFormat === Text.PlainText") is True


def test_descricao_do_backup_menciona_os_saves_so_com_ludusavi(montar):
    _p, pagina = montar()
    assert pagina.achar("grupoBackupDaBiblioteca").property("descricao") == (
        "Salve em um arquivo .zip a biblioteca completa, as cópias dos saves dos jogos e "
        "todas as configurações. A restauração substitui a biblioteca, as configurações e as "
        "cópias dos saves pelas do backup. Para devolver os saves aos jogos, use "
        "“Restaurar saves de todos os jogos”."
    )
    _p, pagina = montar(disponivel=False)
    assert pagina.achar("grupoBackupDaBiblioteca").property("descricao") == (
        "Salve em um arquivo .zip a biblioteca completa e todas as configurações. "
        "A restauração substitui a biblioteca e as configurações atuais pelas do backup."
    )


def test_subtitulo_de_contar_horas_com_ludusavi(montar):
    """O backup dos saves só acontece ao fim de uma sessão, e sessão só existe com a contagem."""
    _p, pagina = montar()
    assert pagina.achar("interruptor-playtime-tracking").property("subtitulo") == (
        "Registra o tempo de cada sessão e faz o backup dos saves ao fim dela; quando o jogo "
        "não pode ser acompanhado automaticamente, abre uma janela compacta para encerrar a sessão"
    )


def test_subtitulo_de_contar_horas_sem_ludusavi(montar):
    _p, pagina = montar(disponivel=False)
    assert pagina.achar("interruptor-playtime-tracking").property("subtitulo") == (
        "Registra o tempo de cada sessão; quando o jogo não pode ser acompanhado "
        "automaticamente, abre uma janela compacta para encerrar a sessão"
    )


def test_grupos_na_ordem_da_main(montar):
    _p, pagina = montar()
    titulos = [i.property("titulo") for i in pagina.item.childItems() if i.property("titulo")]
    assert titulos == ["Comportamento", "Backup da sua biblioteca", "Zona de perigo"]
    assert pagina.achar("linhaRedefinir").property("titulo") == "Redefinir Cartridges"
    assert pagina.achar("linhaRedefinir").property("destrutivo") is True
    for nome, titulo in (
        ("linhaExportarBackup", "Exportar para arquivo"),
        ("linhaImportarBackup", "Importar de arquivo"),
        ("linhaPastaDosSaves", "Pasta dos saves"),
        ("linhaRestaurarSaves", "Restaurar saves de todos os jogos"),
    ):
        assert pagina.achar(nome).property("titulo") == titulo
        assert pagina.achar(nome).property("buscavel") is True


def test_busca_acha_restaurar_saves(montar):
    """Só "Restaurar saves de todos os jogos" tem "restaurar saves" (o texto da `main`): as outras linhas e os outros grupos somem."""
    _p, pagina = montar()
    pagina.avaliar(pagina.item, "BuscaDasPreferencias.texto = 'restaurar saves'")
    assert pagina.visivel("linhaRestaurarSaves")
    for nome in ("linhaExportarBackup", "linhaImportarBackup", "linhaPastaDosSaves", "linhaRedefinir"):
        assert not pagina.visivel(nome), nome
    assert pagina.visivel("grupoBackupDaBiblioteca")
    assert not pagina.visivel("grupoZonaDePerigo") and not pagina.visivel("grupoComportamentoGeral")
    # Sem o Ludusavi a linha some e o grupo inteiro com ela.
    _p, pagina = montar(disponivel=False)
    pagina.avaliar(pagina.item, "BuscaDasPreferencias.texto = 'restaurar saves'")
    assert not pagina.visivel("grupoBackupDaBiblioteca")


def test_pasta_padrao_apaga_usar_a_padrao(montar, monkeypatch, flush_idle):
    p, pagina = montar()
    linha = pagina.achar("linhaPastaDosSaves")
    assert p.backup.pastaPadrao is True
    assert linha.property("rotuloSecundario") == "Usar a padrão" and linha.property("rotulo") == "Escolher"
    assert linha.property("secundarioAtivo") is False
    # Fora da padrão o botão acende (a tela relê ao abrir) e "Usar a padrão" troca para a padrão.
    shared.schema.set_string("pasta-dos-saves", "X:/nova")
    p.backup.reler()
    assert p.backup.pastaPadrao is False and linha.property("secundarioAtivo") is True
    trocas, gate = [], threading.Event()

    def falsa(nova):
        trocas.append(nova)
        gate.wait(5)

    monkeypatch.setattr(backup_de_saves, "trocar_pasta", falsa)
    p.backup.usarPastaPadrao()
    assert _drenar(flush_idle, lambda: trocas)
    assert trocas == [pasta.padrao()]
    # A linha inteira fica apagada enquanto a troca roda.
    assert p.backup.trocandoPasta is True and linha.property("enabled") is False
    shared.schema.set_string("pasta-dos-saves", "")
    gate.set()
    assert _drenar(flush_idle, lambda: not p.backup.trocandoPasta)
    assert linha.property("enabled") is True and linha.property("secundarioAtivo") is False


def test_nome_do_arquivo_sugerido(modelo):
    from datetime import date  # noqa: PLC0415

    assert modelo.nomeDoArquivo == f"cartridges-backup-{date.today().isoformat()}.zip"


# endregion
# region Exportar


def _exportar_com(monkeypatch, modelo, aplicativo, flush_idle, resultado):
    """O caminho inteiro de "Exportar" com `exportar` devolvendo `resultado` (ou levantando, se for uma exceção)."""

    def exportar(_destino, _configuracoes):
        if isinstance(resultado, Exception):
            raise resultado
        return resultado

    monkeypatch.setattr(backup, "exportar", exportar)
    monkeypatch.setattr(backup, "ler_configuracoes", lambda: {"settings": {}, "state": {}})
    modelo.exportar(URL)
    assert _drenar(flush_idle, lambda: aplicativo.avisos.dispensados)
    flush_idle()
    return aplicativo.dialogos, aplicativo.avisos.textos


def test_exportar_com_saves_inacessiveis_mostra_o_texto(monkeypatch, modelo, aplicativo, flush_idle):
    dialogos, textos = _exportar_com(monkeypatch, modelo, aplicativo, flush_idle, backup.SavesInacessiveis("Acesso negado"))
    assert dialogos == [
        (
            "Não foi possível exportar",
            "Não foi possível ler as cópias dos saves. Verifique se a pasta dos saves está "
            "acessível e tente novamente.",
        )
    ]
    assert "Backup exportado" not in textos


def test_exportar_com_outro_erro_mantem_o_texto_do_destino(monkeypatch, modelo, aplicativo, flush_idle):
    dialogos, textos = _exportar_com(monkeypatch, modelo, aplicativo, flush_idle, OSError("disco cheio"))
    assert dialogos == [
        (
            "Não foi possível exportar",
            "Não foi possível gravar o arquivo. Verifique se a pasta de destino está "
            "acessível e se há espaço livre em disco.",
        )
    ]
    assert "Backup exportado" not in textos


def test_exportar_sem_os_saves_mostra_o_aviso(monkeypatch, modelo, aplicativo, flush_idle):
    dialogos, textos = _exportar_com(monkeypatch, modelo, aplicativo, flush_idle, "ausente")
    assert dialogos == [
        (
            "Backup exportado sem os saves",
            "A pasta dos saves não foi encontrada, então as cópias dos saves não foram "
            "incluídas no backup. Verifique se a pasta está acessível e exporte novamente.",
        )
    ]
    assert "Backup exportado" not in textos


def test_exportar_com_pasta_sem_saves_mostra_o_aviso(monkeypatch, modelo, aplicativo, flush_idle):
    dialogos, textos = _exportar_com(monkeypatch, modelo, aplicativo, flush_idle, "vazia")
    assert dialogos == [
        (
            "Backup exportado sem os saves",
            "A pasta dos saves escolhida não tem nenhuma cópia de save, então nenhuma foi "
            "incluída no backup. Verifique se a pasta escolhida em Preferências é a correta.",
        )
    ]
    assert "Backup exportado" not in textos


def test_exportar_com_os_saves_mostra_o_toast(monkeypatch, modelo, aplicativo, flush_idle):
    dialogos, textos = _exportar_com(monkeypatch, modelo, aplicativo, flush_idle, None)
    assert dialogos == []
    assert "Backup exportado" in textos


def test_exportar_sem_url_nao_faz_nada(monkeypatch, modelo, aplicativo, flush_idle):
    monkeypatch.setattr(backup, "ler_configuracoes", lambda: pytest.fail("leu as configurações"))
    monkeypatch.setattr(backup, "exportar", lambda *_a: pytest.fail("exportou"))
    modelo.exportar(QUrl())
    flush_idle()
    assert aplicativo.avisos.textos == [] and aplicativo.dialogos == []


def test_aviso_de_exportando_some_no_fim(monkeypatch, modelo, aplicativo, flush_idle):
    """"Exportando backup…" não tem tempo: fica até o fim e sai pelo id."""
    gate = threading.Event()
    monkeypatch.setattr(backup, "ler_configuracoes", lambda: {})
    monkeypatch.setattr(backup, "exportar", lambda *_a: gate.wait(5) and None)
    modelo.exportar(URL)
    assert aplicativo.avisos.textos == ["Exportando backup…"]
    assert aplicativo.avisos.ultima["segundos"] == 0
    assert aplicativo.avisos.dispensados == []
    gate.set()
    assert _drenar(flush_idle, lambda: aplicativo.avisos.dispensados)
    assert aplicativo.avisos.dispensados == [1]
    assert aplicativo.avisos.textos[-1] == "Backup exportado"


def test_resultado_da_exportacao_depois_de_fechar_as_preferencias_nao_levanta(monkeypatch, aplicativo):
    """O objeto já foi coletado quando o resultado chega: o aviso sai e o resto é descartado, sem levantar."""
    _com_ludusavi(monkeypatch)
    entregas, gate = [], threading.Event()
    monkeypatch.setattr(modulo, "na_thread_principal", lambda f, *a: entregas.append((f, a)))
    monkeypatch.setattr(backup, "ler_configuracoes", lambda: {})

    def exportar(*_a):
        gate.wait(5)
        raise OSError("disco cheio")

    monkeypatch.setattr(backup, "exportar", exportar)
    m = BackupDasPreferencias(aplicativo.avisos)
    fraco = weakref.ref(m)
    m.exportar(URL)
    del m
    gc.collect()
    assert fraco() is None  # a thread não prende o modelo
    gate.set()
    fim = time.monotonic() + 5
    while not entregas and time.monotonic() < fim:
        time.sleep(0.01)
    assert entregas
    for funcao, args in entregas:
        funcao(*args)  # não levanta
    assert aplicativo.dialogos == []
    assert aplicativo.avisos.dispensados == [1]
    assert aplicativo.avisos.textos == ["Exportando backup…"]


# endregion
# region Pasta dos saves


def _esperar_troca(modelo, monkeypatch, resultado):
    """Troca a pasta com `trocar_pasta` simulada e devolve a thread que a chamou."""
    chamada = threading.Event()
    thread = []

    def falsa(_nova):
        thread.append(threading.current_thread())
        chamada.set()
        if resultado is not None:
            raise resultado

    monkeypatch.setattr(backup_de_saves, "trocar_pasta", falsa)
    modelo.escolherPastaDosSaves(QUrl.fromLocalFile("X:/nova"))
    assert chamada.wait(5)
    return thread[0]


def test_troca_da_pasta_roda_fora_da_tela_e_atualiza_o_subtitulo(monkeypatch, modelo, aplicativo, flush_idle):
    shared.schema.set_string("pasta-dos-saves", "X:/nova")  # o que o `trocar_pasta` de verdade faria
    thread = _esperar_troca(modelo, monkeypatch, None)
    assert _drenar(flush_idle, lambda: modelo.pastaDosSaves == r"X:\nova")
    assert thread is not threading.main_thread()
    assert modelo.trocandoPasta is False
    assert aplicativo.avisos.textos == []
    assert modelo.pastaPadrao is False


def test_escolher_pasta_sem_url_nao_troca(monkeypatch, modelo, flush_idle):
    monkeypatch.setattr(backup_de_saves, "trocar_pasta", lambda _nova: pytest.fail("trocou a pasta"))
    modelo.escolherPastaDosSaves(QUrl())
    flush_idle()
    assert modelo.trocandoPasta is False


@pytest.mark.parametrize(
    "mensagem",
    [
        "Escolha uma pasta fora da pasta atual dos saves.",
        "Escolha uma pasta que não contenha a pasta atual dos saves.",
        "A pasta escolhida já tem arquivos com os mesmos nomes dos saves. Escolha outra pasta.",
        "Escolha uma pasta fora da pasta de dados do Cartridges.",
    ],
)
def test_troca_recusada_mostra_a_mensagem_de_cada_motivo(monkeypatch, modelo, aplicativo, flush_idle, mensagem):
    _esperar_troca(modelo, monkeypatch, pasta.TrocaRecusada(mensagem))
    assert _drenar(flush_idle, lambda: aplicativo.avisos.textos)
    assert aplicativo.avisos.textos == [mensagem]
    assert modelo.trocandoPasta is False


def test_troca_que_falha_avisa(monkeypatch, modelo, aplicativo, flush_idle):
    _esperar_troca(modelo, monkeypatch, OSError("disco cheio"))
    assert _drenar(flush_idle, lambda: aplicativo.avisos.textos)
    assert aplicativo.avisos.textos == ["Não foi possível trocar a pasta dos saves."]
    assert modelo.trocandoPasta is False


# endregion
# region Restaurar todos os saves, importar um backup e Redefinir


def test_restaurar_todos_pede_confirmacao_com_o_texto_da_spec(monkeypatch, modelo, aplicativo):
    restaurados = []
    monkeypatch.setattr(backup_de_saves, "restaurar_todos", lambda: restaurados.append(1))
    modelo.restaurarTodos()
    (pedido,) = aplicativo.confirmacoes
    assert pedido["titulo"] == "Restaurar os saves de todos os jogos?"
    assert pedido["corpo"] == (
        "Tem certeza que deseja restaurar os saves de todos os jogos? "
        "Os saves atuais de cada jogo serão guardados como uma nova versão antes da restauração."
    )
    assert pedido["rotulo"] == "Restaurar" and pedido["destrutivo"] is True
    aplicativo.responder(0, False)
    assert restaurados == []
    aplicativo.responder(0, True)
    assert restaurados == [1]


def test_restaurar_backup_com_saves_em_andamento_avisa(monkeypatch, modelo, aplicativo):
    monkeypatch.setattr(backup_de_saves, "em_andamento", lambda: True)
    modelo.importar(URL)
    assert aplicativo.confirmacoes == []  # nunca confirma a restauração com os saves em andamento
    assert aplicativo.avisos.textos == [AGUARDE]


def test_importar_sem_url_nao_faz_nada(modelo, aplicativo):
    modelo.importar(QUrl())
    assert aplicativo.confirmacoes == [] and aplicativo.avisos.textos == []


def _importar(monkeypatch, modelo, aplicativo, tmp_path, em_andamento, validar=None):
    """"Importar de arquivo" confirmado, com um .zip de mentira, o `validar` falso e o `agendar` de verdade (na pasta temporária)."""
    origem = tmp_path / "origem.zip"
    origem.write_bytes(b"zip")
    monkeypatch.setattr(backup, "validar", validar or (lambda _caminho: None))
    monkeypatch.setattr(backup_de_saves, "em_andamento", em_andamento)
    modelo.importar(QUrl.fromLocalFile(str(origem)))
    return shared.app_dir / "restaurar.zip"


def test_importar_pede_a_confirmacao_e_cancelar_nao_prepara_nada(monkeypatch, modelo, aplicativo, tmp_path, flush_idle):
    agendado = _importar(monkeypatch, modelo, aplicativo, tmp_path, lambda: False)
    (pedido,) = aplicativo.confirmacoes
    assert pedido["titulo"] == "Restaurar este backup?"
    assert pedido["corpo"] == "Tem certeza que deseja restaurar este backup? Esta ação é irreversível."
    assert pedido["rotulo"] == "Restaurar" and pedido["destrutivo"] is True
    aplicativo.responder(0, False)
    flush_idle()
    assert aplicativo.avisos.textos == [] and aplicativo.reinicios == 0 and not agendado.exists()


def test_reiniciar_para_restaurar_sem_saves_em_andamento_sai_e_mantem_o_agendado(
    monkeypatch, modelo, aplicativo, tmp_path, flush_idle
):
    agendado = _importar(monkeypatch, modelo, aplicativo, tmp_path, lambda: False)
    aplicativo.responder(0, True)
    assert aplicativo.avisos.textos == ["Preparando a restauração…"] and aplicativo.avisos.ultima["segundos"] == 0
    assert _drenar(flush_idle, lambda: aplicativo.reinicios)
    assert aplicativo.reinicios == 1
    assert aplicativo.avisos.dispensados == [1]
    assert aplicativo.avisos.textos == ["Preparando a restauração…"]
    assert agendado.is_file()


def test_reiniciar_para_restaurar_com_saves_em_andamento_desiste_e_desagenda(
    monkeypatch, modelo, aplicativo, tmp_path, flush_idle
):
    """O aviso do pedido vale só naquele instante: o backup já copiado é desfeito, para não ser aplicado por surpresa."""
    estado = {"agendou": False}
    real = backup.agendar

    def agendar(origem):
        real(origem)
        estado["agendou"] = True  # os saves começam logo depois de copiar

    monkeypatch.setattr(backup, "agendar", agendar)
    agendado = _importar(monkeypatch, modelo, aplicativo, tmp_path, lambda: estado["agendou"])
    aplicativo.responder(0, True)
    assert _drenar(flush_idle, lambda: AGUARDE in aplicativo.avisos.textos)
    assert estado["agendou"] is True
    assert aplicativo.reinicios == 0
    assert aplicativo.avisos.dispensados == [1]
    assert aplicativo.avisos.textos == ["Preparando a restauração…", AGUARDE]
    assert not agendado.exists()


def test_restaurar_backup_que_ganha_saves_em_andamento_na_preparacao_nao_sai(
    monkeypatch, modelo, aplicativo, tmp_path, flush_idle
):
    """O caminho inteiro: a verificação do começo passou, os saves começaram no meio da preparação."""
    ligado = []
    agendado = _importar(
        monkeypatch, modelo, aplicativo, tmp_path, lambda: bool(ligado), validar=lambda _caminho: ligado.append(1)
    )
    aplicativo.responder(0, True)
    assert _drenar(flush_idle, lambda: len(aplicativo.avisos.textos) == 2)
    assert aplicativo.avisos.textos == ["Preparando a restauração…", AGUARDE]
    assert aplicativo.reinicios == 0
    assert not agendado.exists()


@pytest.mark.parametrize(
    ("erro", "titulo", "corpo"),
    [
        (backup.BackupInvalido("x"), "Backup inválido", "O arquivo não é um backup válido do Cartridges."),
        (OSError("disco cheio"), "Não foi possível restaurar", "Não foi possível restaurar o backup. Tente novamente."),
    ],
)
def test_backup_invalido_ou_que_falha_ao_agendar_mostra_o_dialogo(
    monkeypatch, modelo, aplicativo, tmp_path, flush_idle, erro, titulo, corpo
):
    def validar(_caminho):
        raise erro

    _importar(monkeypatch, modelo, aplicativo, tmp_path, lambda: False, validar=validar)
    aplicativo.responder(0, True)
    assert _drenar(flush_idle, lambda: aplicativo.dialogos)
    assert aplicativo.dialogos == [(titulo, corpo)]
    assert aplicativo.avisos.dispensados == [1]
    assert aplicativo.reinicios == 0


def _confirmar(monkeypatch, modelo, aplicativo, em_andamento):
    monkeypatch.setattr(backup_de_saves, "em_andamento", lambda: em_andamento)
    modelo.redefinir()
    aplicativo.responder(0, True)
    return aplicativo.avisos.textos


def test_redefinir_pede_a_confirmacao_com_o_texto_da_main(modelo, aplicativo, monkeypatch):
    monkeypatch.setattr(redefinir, "agendar", lambda: pytest.fail("agendou sem confirmar"))
    modelo.redefinir()
    (pedido,) = aplicativo.confirmacoes
    assert pedido["titulo"] == "Redefinir o Cartridges?"
    assert pedido["corpo"] == (
        "Tem certeza que deseja redefinir o Cartridges? Todos os jogos, configurações, contas conectadas e "
        "cópias dos saves armazenadas na pasta do aplicativo serão excluídos, e o aplicativo será "
        "reiniciado. Esta ação é irreversível."
    )
    assert pedido["rotulo"] == "Redefinir" and pedido["destrutivo"] is True
    aplicativo.responder(0, False)
    assert aplicativo.reinicios == 0 and aplicativo.avisos.textos == []


def test_confirmar_agenda_e_reinicia(monkeypatch, modelo, aplicativo):
    textos = _confirmar(monkeypatch, modelo, aplicativo, em_andamento=False)
    assert redefinir.ha_pendente()
    assert aplicativo.reinicios == 1
    assert textos == []


def test_confirmar_com_saves_em_andamento_nao_agenda(monkeypatch, modelo, aplicativo):
    textos = _confirmar(monkeypatch, modelo, aplicativo, em_andamento=True)
    assert not redefinir.ha_pendente()
    assert aplicativo.reinicios == 0
    assert textos == [AGUARDE]


def test_redefinir_que_nao_consegue_agendar_avisa(monkeypatch, modelo, aplicativo):
    def recusa():
        raise OSError("disco cheio")

    monkeypatch.setattr(redefinir, "agendar", recusa)
    textos = _confirmar(monkeypatch, modelo, aplicativo, em_andamento=False)
    assert textos == ["Não foi possível redefinir o Cartridges"]
    assert aplicativo.reinicios == 0


# endregion
