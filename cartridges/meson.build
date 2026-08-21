moduledir = python_dir / 'cartridges'

configure_file(
  input: 'cartridges.in',
  output: 'cartridges',
  configuration: conf,
  install: true,
  install_dir: get_option('bindir'),
)

# __pycache__ is excluded because install_subdir copies the source tree as it
# stands: whatever the build machine happened to import last ships inside the
# package. Those .pyc files carry the build machine's absolute paths, and
# CPython will load a stale one over the installed .py whenever the recorded
# mtime and size still match — so a file fixed between builds can keep running
# its old bytecode on the user's install.
install_subdir('importer', install_dir: moduledir, exclude_directories: '__pycache__')
install_subdir('utils', install_dir: moduledir, exclude_directories: '__pycache__')
# Meson reads these names as paths relative to the subdir, not as basenames to
# match anywhere in the tree, and it does not accept wildcards — so the nested
# package needs spelling out or its bytecode ships regardless. `store` is the
# only one of the five with a subpackage.
install_subdir(
  'store',
  install_dir: moduledir,
  exclude_directories: ['__pycache__', 'managers/__pycache__'],
)
install_subdir('logging', install_dir: moduledir, exclude_directories: '__pycache__')
install_subdir('errors', install_dir: moduledir, exclude_directories: '__pycache__')
install_data(
  [
    'main.py',
    'window.py',
    'preferences.py',
    'details_dialog.py',
    'sgdb_picker.py',
    'logo_picker.py',
    'steam_picker.py',
    'session_window.py',
    'session_history.py',
    'process_session.py',
    'metadata_refresh.py',
    'game.py',
    'game_cover.py',
    'gamepad.py',
    configure_file(input: 'shared.py.in', output: 'shared.py', configuration: conf),
  ],
  install_dir: moduledir,
)
