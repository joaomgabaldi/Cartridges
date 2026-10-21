# GTK corrigido

O Cartridges depende de duas correções no GTK4 que ainda não estão upstream.

- Sem a primeira, a janela é desenhada **pela metade** em qualquer monitor maior
  que o principal — o restante fica transparente, embora continue respondendo
  aos cliques. Detalhe completo em [`ISSUE.md`](ISSUE.md).
- Sem a segunda, elementos desenhados com perspectiva 3D (as capas do Big
  Picture) deixam um quadro com defeito quando só parte da janela é redesenhada.
  Detalhe em [`ISSUE-clip-projetivo.md`](ISSUE-clip-projetivo.md).

A libadwaita também sai corrigida, mas por escolha visual, não por defeito: o
toast entra com fade em vez de subir da borda de baixo. A saída continua a da
libadwaita (fade com um leve encolhimento). Vale para todos os toasts do app,
que são desenhados pela libadwaita.

## Arquivos

| arquivo | o que é |
| --- | --- |
| `gtk-dcomp-render-window-origin.patch` | a primeira correção (janela cortada no monitor maior), contra a tag do GTK registrada na trava |
| `gtk-gpu-clip-projetivo.patch` | a segunda correção (recorte com perspectiva 3D), contra a mesma tag do GTK |
| `libadwaita-toast-fade.patch` | o fade do toast, contra a tag da libadwaita registrada na trava |
| `patched-gtk.txt` | a trava: versão de cada pacote e hash da `libgtk-4-1.dll` e da `libadwaita-1-0.dll` corrigidas |
| `ISSUE.md` | relatório pronto para o upstream da primeira correção |
| `ISSUE-clip-projetivo.md` | relatório pronto para o upstream da segunda correção |

Os pacotes corrigidos não ficam no repositório: o workflow **Compilar GTK
corrigido** (`.github/workflows/gtk-corrigido.yml`) gera o gtk4 e a libadwaita a
partir das receitas oficiais do MSYS2 mais os patches de cada um (dois no gtk4,
um na libadwaita), e os anexa à
pré-release
[`gtk-corrigido`](https://github.com/joaomgabaldi/Cartridges/releases/tag/gtk-corrigido).

## A trava

O `build-installer.ps1` (no PC e na CI) confere, antes de empacotar, que o gtk4
e a libadwaita instalados são as versões da trava e que as DLLs têm os hashes da
trava:

- **Versão diferente** → para. O MSYS2 publicou um GTK novo; ver abaixo.
- **Mesma versão, hash diferente** → para e mostra o comando que reinstala a
  corrigida. Uma reinstalação do pacote oficial
  (`pacman -S mingw-w64-ucrt-x86_64-gtk4`, ou `…-libadwaita`) ou uma
  instalação nova do MSYS2 cai aqui.

## Quando o MSYS2 publicar um GTK ou uma libadwaita novos

1. No GitHub, Actions → **Compilar GTK corrigido** → Run workflow. Se o patch
   não aplicar, o log diz o arquivo; refaça o trecho (o `ISSUE.md` explica o
   que ele faz) e rode de novo.
2. No PC, terminal UCRT64: `pacman -Syu`, depois
   `curl -fLO <link do pacote na gtk-corrigido> && pacman -U --noconfirm <pacote>`.
3. Recompilar, rodar os testes e o passeio, e conferir o segundo monitor.
4. Copiar as linhas do resumo do workflow para `patched-gtk.txt` e fazer commit.
   O pacote cuja versão já está na pré-release é pulado: a compilação não sai
   byte a byte igual, e refazê-lo mudaria o hash da trava. Para republicar a
   mesma versão (o patch mudou), apague antes o anexo dela na pré-release.

## Quando isso pode ser jogado fora

Cada patch do gtk4 sai quando a sua correção entrar no GTK e o MSYS2 empacotar
uma versão que a contenha:

- `gtk-dcomp-render-window-origin.patch` (e o `ISSUE.md`): apagar o arquivo e tirá-lo
  da lista `patches` do gtk4 na matriz do `gtk-corrigido.yml`.
- `gtk-gpu-clip-projetivo.patch` (e o `ISSUE-clip-projetivo.md`): idem.

Quando os dois tiverem saído, o gtk4 deixa de ser corrigido: apagar também a
entrada `gtk4` da matriz, a do `build-installer.ps1` (`$corrigidas`), o `gtk4`
do laço no passo "GTK corrigido, tinytuya e meson setup" do `instalador.yml` e
as linhas do gtk4 em `patched-gtk.txt`.

A libadwaita corrigida fica enquanto o toast com fade for desejado. Para voltar
ao toast original, o mesmo vale para ela: o patch, a entrada da matriz, a de
`$corrigidas`, o `libadwaita` do laço e as linhas dela na trava. Sem nenhum dos
dois, sai o diretório inteiro, o workflow e a checagem.
