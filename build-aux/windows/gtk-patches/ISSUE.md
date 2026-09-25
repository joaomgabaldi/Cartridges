# GL/Vulkan renderers are clipped to the primary monitor's bounds (Windows)

Report drafted for <https://gitlab.gnome.org/GNOME/gtk/-/issues>.
The patch in this directory (`gtk-dcomp-render-window-origin.patch`) fixes it
and has been verified against 4.22.4.

---

## Environment

- GTK 4.22.4, libadwaita 1.9.1 (MSYS2 UCRT64, `mingw-w64-ucrt-x86_64-gtk4 4.22.4-1`)
- Windows 11, NVIDIA RTX 4060
- Two monitors: 2560x1080 (landscape) and 1080x1920 (portrait)
- `GDK_WIN32_FORCE_DCOMP=1` — MSYS2 ships `003-default-dcomp-off.patch`, and the
  GL and Vulkan renderers refuse to realize without DirectComposition
  ("OpenGL requires Direct Composition"), so this is required to use them at all

## Symptom

A window is only painted within the primary monitor's bounds. Past that the
window is transparent — the desktop shows through — while remaining fully
interactive: clicks in the unpainted region reach the correct widgets and the
application responds normally. Only presentation is affected.

The clipping applies per axis and follows the primary monitor:

| Primary monitor    | Window on the other monitor         |
| ------------------ | ----------------------------------- |
| 2560x1080 landscape | painting stops at 1080px of height  |
| 1080x1920 portrait  | painting stops at 1080px of width   |

Changing the primary display in Windows settings fixes or breaks it
**instantly, with the window already open** — no restart, no resize, no
re-creation of anything. So the limit is not captured when the context is
created; it tracks the primary monitor live.

Note that with these two monitors no choice of primary display avoids the bug:
whichever one is primary, a window maximized on the other is clipped.

## Steps to reproduce

1. Two monitors where the secondary is larger than the primary in some axis.
2. Move a GTK4 window to the secondary monitor.
3. Drag the bottom (or right) edge outward, or maximize.
4. Painting stops at the primary monitor's height (or width).

## Affected renderers

| `GSK_RENDERER` | Result                          |
| -------------- | ------------------------------- |
| `gl`           | reproduces                      |
| `ngl`          | reproduces (aliased to `gl`)    |
| `vulkan`       | reproduces                      |
| `cairo`        | does **not** reproduce          |

## Cause

The correlation matches how each context presents.

`gdkcairocontext-win32.c` (works) creates an explicitly sized swapchain, which
has no position and therefore no relationship to any monitor:

```c
IDXGIFactory4_CreateSwapChainForComposition (..., (&(DXGI_SWAP_CHAIN_DESC1) {
                                                      .Width = width,
                                                      .Height = height, ... }), ...);
gdk_win32_surface_set_dcomp_content (GDK_WIN32_SURFACE (surface),
                                     (IUnknown *) self->swap_chain);
```

`gdkglcontext-win32.c` and `gdkvulkancontext-win32.c` (both broken) render into
a cloaked child window and hand that window to DirectComposition:

```c
self->handle = CreateWindowExW (0, ..., WS_POPUP | ..., 0, 0, width, height,
                                GDK_SURFACE_HWND (surface), ...);
DwmSetWindowAttribute (self->handle, DWMWA_CLOAK, (BOOL[1]) { true }, sizeof (BOOL));
IDCompositionDevice_CreateSurfaceFromHwnd (dcomp_device, self->handle, &dcomp_surface);
```

That window is a `WS_POPUP`, so the position passed to `CreateWindowEx()` and
`SetWindowPos()` is in **screen** coordinates, not relative to the toplevel that
owns it. Passing `(0, 0)` parks it at the virtual desktop origin, which is by
definition the top left corner of the primary monitor — and the DWM redirection
surface that DirectComposition reads it through only covers the part of the
window that overlaps a display. Everything past the primary monitor's bounds is
never composed.

This also explains the observations that a size-based or creation-time
explanation does not:

- changing the primary display moves the virtual desktop origin, so the clipping
  changes immediately, with no window re-creation;
- minimizing and restoring does not help, because the window never moves;
- `gdk_draw_context_get_buffer_size()` returns the correct size and
  `surface_resized()` does resize the child window, so the geometry GTK computes
  is right — only where the window sits is wrong.

## Fix

`gtk-dcomp-render-window-origin.patch` (attached, 5 files, +82 lines, no
deletions) keeps the rendering window on a monitor that can hold it:

- `GdkWin32Surface` gains a `dcomp_hwnd` field so the rendering window can be
  reached from outside the draw context;
- a new `gdk_win32_surface_anchor_dcomp_hwnd()` moves that window to the
  toplevel's monitor, but only when it no longer fits entirely on the monitor
  it is currently on. The window is cloaked, so it does not need to follow the
  toplevel — it only needs to fit somewhere. Re-anchoring unconditionally makes
  it flicker mid-drag, while the toplevel briefly straddles two monitors;
- it is called on attach, on resize, and from `WM_WINDOWPOSCHANGED` so that
  moving a window across monitors without resizing it is handled too.

Verified with both `GSK_RENDERER=gl` and `GSK_RENDERER=vulkan`, dragging and
maximizing in both directions between the two monitors, and with either monitor
set as primary.

## A better fix

The patch makes `CreateSurfaceFromHwnd()` workable, but the mechanism stays
fragile: it depends on a hidden window being parked somewhere the DWM will
compose it. The Cairo backend already shows the robust approach —
`CreateSwapChainForComposition()` is sized explicitly, has no position, and no
monitor can clip it. Porting the GL and Vulkan backends to a composition
swapchain would remove this class of bug entirely, at the cost of needing
GL/D3D and Vulkan/D3D interop to get the rendered frames into it.
