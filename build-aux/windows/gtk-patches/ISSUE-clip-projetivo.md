# GPU renderers cull with a wrong clip under a perspective transform (stale pixels for one frame)

Report drafted for <https://gitlab.gnome.org/GNOME/gtk/-/issues>.
The patch in this directory (`gtk-gpu-clip-projetivo.patch`) fixes it and has
been verified against 4.24.1. The code involved is unchanged in `main`.

---

## Environment

- GTK 4.24.1, libadwaita 1.9.1 (MSYS2 UCRT64)
- Windows 11, NVIDIA RTX 4060
- `GDK_DEBUG=dcomp` (DirectComposition is opt-in upstream since 4.24.0; the GL
  and Vulkan renderers need it on Windows)

## Symptom

A widget draws a texture under a 3D transform with perspective
(`gsk_transform_perspective()` plus `gsk_transform_rotate_3d()` around the Y
axis) and animates the angle. When only part of the window is redrawn, the
visible part of the texture that lies inside the redrawn area is clipped too
small, and the pixels from the previous frame are left behind. It lasts for
one frame, which is enough to be seen as a glitch: on the last frame of the
animation, the texture leaves stale content where the new frame should have
drawn it.

## Steps to reproduce

1. A widget whose `snapshot()` pushes `perspective` + `rotate_3d` (Y axis) and
   appends a texture (`gtk_snapshot_append_texture()`).
2. Animate the rotation angle from one tick callback.
3. Make the damage partial: the changed area of the window must not cover the
   whole transformed node. Window size does not matter, full screen or not.
4. On the last frame the texture leaves garbage behind.

Checks done in the real application (a cover flow whose side covers rotate in
perspective):

- `GSK_DEBUG=full-redraw` makes the glitch disappear (the clip is then the
  whole surface, and the code below is skipped);
- `GDK_VULKAN_DISABLE=incremental-present` does not change anything, so the
  presentation damage is not the cause;
- a GTK built with the patch below has no glitch, without any debug option.

## Affected renderers

| `GSK_RENDERER` | Result                                             |
| -------------- | -------------------------------------------------- |
| `vulkan`       | reproduces                                         |
| `gl` / `ngl`   | reproduces (same `gsk/gpu/gskgpurenderpass.c`)     |
| `cairo`        | does **not** reproduce                             |

## Cause

`gsk_gpu_render_pass_push_transform()` in `gsk/gpu/gskgpurenderpass.c`, in the
`2D` / `3D` / `ANY` / `UNKNOWN` branch. When the current clip does not contain
the node, the clip rectangle is brought into the child's coordinate space with
the inverse of the transform, applied to points `(x, y, 0)`:

```c
inverse = gsk_transform_invert (gsk_transform_ref (clip_transform));
gsk_transform_transform_bounds (inverse, &storage->clip.clip.rect.bounds, &new_bounds);
gsk_transform_unref (inverse);
gsk_gpu_clip_init_empty (&self->clip, graphene_point_zero (), &new_bounds);
```

That is only correct when the transform is affine. With a perspective, a point
of the screen is not a point at `z = 0` of the child but a ray, and the child is
drawn flat on its own `z = 0` plane. The inverse of the full 4x4 matrix applied
to `(x, y, 0)` does not give where that ray meets the plane, so `new_bounds`
comes out too small. Whatever is visible inside the redrawn area but outside
`new_bounds` is culled, and the old pixels stay.

The numbers of the last frame of the animation, with the clip covering about
half of the texture (texture space is 396 px wide):

|         | x range of the child that must be drawn |
| ------- | --------------------------------------- |
| correct | [0, 166]                                |
| GTK     | [-24, 34]                               |

## Fix

`gtk-gpu-clip-projetivo.patch` (1 file, +118 lines, 3 deletions) adds
`unproject_bounds()` and calls it instead of the plain inverse:

- since the child is flat at `z = 0`, only the homography from the child's
  `(x, y, 1)` to the parent's `(x, y, w)` matters: the 4x4 matrix without its
  z row and z column. It is inverted as a 3x3 matrix, and the four corners of
  the clip rectangle are mapped back onto the child's plane exactly (with the
  perspective divide);
- if a corner does not land on the plane in front of the viewer (the clip
  rectangle crosses the plane's horizon, which is the common case for a card
  rotated in perspective), the function fails and the caller does no culling
  at all (`child_bounds`, or the old code when those are not known). That is
  always correct, since the scissor still limits the pixels drawn;
- otherwise, `w` is linear in `x` and `y`, so with all four corners in front the
  whole rectangle is, and the result is the bounds of the convex quad formed by
  the corners;
- after a successful `unproject_bounds()`, `new_bounds` is intersected with
  `child_bounds` (an empty result means the child is not visible there). Near
  the plane's horizon the unprojected clip grows far past the child, and the
  clip bounds also feed the offscreen scale heuristics, so they are kept to the
  child, as the case where the clip contains the node already does.

Verified against 4.24.1 in the real application: the glitch is gone, and the
rest of the application behaves as before.
