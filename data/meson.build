blueprints = custom_target(
  'blueprints',
  input: files(
    'gtk/details-dialog.blp',
    'gtk/fita-wizard.blp',
    'gtk/game.blp',
    'gtk/logo-picker.blp',
    'gtk/preferences.blp',
    'gtk/sgdb-picker.blp',
    'gtk/steam-picker.blp',
    'gtk/shortcuts-dialog.blp',
    'gtk/wallpaper-picker.blp',
    'gtk/window.blp',
  ),
  output: '.',
  # The output is a directory, which Ninja can't track for freshness, so .blp
  # edits would otherwise leave stale .ui files. Always recompile (it's fast).
  build_always_stale: true,
  build_by_default: true,
  command: [
    find_program('blueprint-compiler'),
    'batch-compile',
    '@OUTPUT@',
    '@CURRENT_SOURCE_DIR@',
    '@INPUT@',
  ],
)

# Start-menu integration comes from the Inno Setup installer
# (build-aux/windows), so no launcher entry is generated here.

appstream_file = configure_file(
  input: 'page.kramo.Cartridges.metainfo.xml.in',
  output: app_id + '.metainfo.xml',
  configuration: conf,
  install: true,
  install_dir: join_paths(get_option('datadir'), 'metainfo'),
)

gnome.compile_resources(
  'cartridges',
  configure_file(
    input: 'cartridges.gresource.xml.in',
    output: 'cartridges.gresource.xml',
    configuration: conf,
  ),
  gresource_bundle: true,
  install: true,
  install_dir: pkgdatadir,
  dependencies: [blueprints, appstream_file],
)

install_data(
  configure_file(
    input: 'page.kramo.Cartridges.gschema.xml.in',
    output: app_id + '.gschema.xml',
    configuration: conf,
  ),
  install_dir: join_paths(get_option('datadir'), 'glib-2.0/schemas'),
)

compile_schemas = find_program('glib-compile-schemas', required: false)
if compile_schemas.found()
  test(
    'Validate schema file',
    compile_schemas,
    args: ['--strict', '--dry-run', meson.current_source_dir()],
  )
endif

subdir('icons')
