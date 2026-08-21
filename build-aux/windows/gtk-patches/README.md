# GTK corrigido

O Cartridges depende de uma correção no GTK4 que ainda não está upstream. Sem
ela, a janela é desenhada **pela metade** em qualquer monitor maior que o
principal — o restante fica transparente, embora continue respondendo aos
cliques. Detalhe completo em [`ISSUE.md`](ISSUE.md).

## Arquivos

| arquivo | o que é |
| --- | --- |
| `gtk-dcomp-render-window-origin.patch` | a correção, contra a tag `4.22.4` do GTK |
| `libgtk-4-1.dll` | a DLL já compilada com o patch |
| `patched-gtk.txt` | versão do pacote gtk4 e hash da DLL acima |
| `ISSUE.md` | relatório pronto para o upstream |

## Por que isso é frágil

O instalador empacota `C:\msys64\ucrt64\bin\*.dll`, ou seja, **a libgtk que
estiver instalada no MSYS2 na hora do build**. Um `pacman -Syu` sobrescreve a
nossa build corrigida sem avisar, e o instalador seguinte sai com o bug de volta
— tudo compila, tudo empacota, e ninguém percebe até um usuário reclamar.

Por isso o `build-installer.bat` confere antes de empacotar, usando o
`patched-gtk.txt`:

- **DLL diferente, mesma versão de pacote** → o pacman reinstalou por cima.
  Restaura a `libgtk-4-1.dll` daqui sozinho e segue. É seguro: a ABI é a mesma.
- **Versão de pacote diferente** → para e avisa. Restaurar aqui seria pior que o
  bug: uma libgtk de outra versão junto do resto do GTK atualizado quebra de
  formas bem menos óbvias que um recorte de desenho.

## Refazer o patch depois de um upgrade do GTK

```bash
cd ~/gtk-build
git fetch --depth 1 origin <tag da versao nova> && git checkout FETCH_HEAD
git apply <este diretorio>/gtk-dcomp-render-window-origin.patch
ninja -C _build gtk/libgtk-4-1.dll && cp _build/gtk/libgtk-4-1.dll /ucrt64/bin/
```

Se o patch não aplicar limpo, o `ISSUE.md` explica o que ele faz e por quê —
dá para refazer à mão em poucos minutos.

Depois, atualize a trava (a DLL guardada aqui e o `patched-gtk.txt`) para a
versão nova, senão o build continuará parando.

## Quando isso pode ser jogado fora

Quando a correção entrar no GTK e o MSYS2 empacotar uma versão que a contenha.
Aí basta apagar este diretório e a checagem no início do
`build-aux/windows/build-installer.ps1`.
