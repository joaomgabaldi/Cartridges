# GTK corrigido

O Cartridges depende de uma correção no GTK4 que ainda não está upstream. Sem
ela, a janela é desenhada **pela metade** em qualquer monitor maior que o
principal — o restante fica transparente, embora continue respondendo aos
cliques. Detalhe completo em [`ISSUE.md`](ISSUE.md).

## Arquivos

| arquivo | o que é |
| --- | --- |
| `gtk-dcomp-render-window-origin.patch` | a correção, contra a tag do GTK registrada na trava |
| `patched-gtk.txt` | a trava: versão do pacote gtk4 e hash da `libgtk-4-1.dll` corrigida |
| `ISSUE.md` | relatório pronto para o upstream |

O pacote gtk4 corrigido não fica no repositório: o workflow **Compilar GTK
corrigido** (`.github/workflows/gtk-corrigido.yml`) o gera a partir da receita
oficial do MSYS2 mais este patch, e o anexa à pré-release
[`gtk-corrigido`](https://github.com/joaomgabaldi/Cartridges/releases/tag/gtk-corrigido).

## A trava

O `build-installer.ps1` (no PC e na CI) confere, antes de empacotar, que o gtk4
instalado é a versão da trava e que a `libgtk-4-1.dll` tem o hash da trava:

- **Versão diferente** → para. O MSYS2 publicou um GTK novo; ver abaixo.
- **Mesma versão, hash diferente** → para e mostra o comando que reinstala a
  corrigida. Uma reinstalação do gtk4 oficial
  (`pacman -S mingw-w64-ucrt-x86_64-gtk4`) ou uma instalação nova do MSYS2
  cai aqui.

## Quando o MSYS2 publicar um GTK novo

1. No GitHub, Actions → **Compilar GTK corrigido** → Run workflow. Se o patch
   não aplicar, o log diz o arquivo; refaça o trecho (o `ISSUE.md` explica o
   que ele faz) e rode de novo.
2. No PC, terminal UCRT64: `pacman -Syu`, depois
   `curl -fLO <link do pacote na gtk-corrigido> && pacman -U --noconfirm <pacote>`.
3. Recompilar, rodar os testes e o passeio, e conferir o segundo monitor.
4. Copiar as duas linhas do resumo do workflow para `patched-gtk.txt` e fazer commit.

## Quando isso pode ser jogado fora

Quando a correção entrar no GTK e o MSYS2 empacotar uma versão que a contenha.
Aí basta apagar este diretório, o workflow `gtk-corrigido.yml`, a checagem no
início do `build-installer.ps1`. No passo "GTK corrigido, tinytuya e meson setup"
do `instalador.yml`, remover apenas a checagem da trava e o download e a
instalação do pacote corrigido (`curl` e `pacman -U`); a instalação do tinytuya
e o `meson setup` continuam.
