project(
  'cartridges',
  # Versionamento por data da build: AAAA.MM.DD
  # Atualize esta linha (e a <release> em data/io.github.joaomgabaldi.Cartridges.metainfo.xml.in)
  # sempre que fizer uma alteracao que exija rebuildar o projeto.
  version: '2026.10.01',
  meson_version: '>= 0.59.0',
  default_options: [
    'warning_level=2',
    'werror=false',
  ],
)

# 4.24 is the patched GTK the app ships (build-aux/windows/gtk-patches) and
# the first with GDK_DEBUG=dcomp, which the launcher relies on
dependency('gtk4', version: '>= 4.24.0')
# 1.10 is what the app ships and is tested on
dependency('libadwaita-1', version: '>= 1.10')

# The UI is hardcoded in pt-BR; gettext/po translations were removed
gnome = import('gnome')
python = import('python')

py_installation = python.find_installation('python3')

python_dir = join_paths(get_option('prefix'), py_installation.get_install_dir())
pkgdatadir = join_paths(get_option('prefix'), get_option('datadir'), meson.project_name())
libexecdir = join_paths(get_option('prefix'), get_option('libexecdir'))

app_id = 'io.github.joaomgabaldi.Cartridges'
prefix = '/io/github/joaomgabaldi/Cartridges'

conf = configuration_data()
conf.set('PYTHON', py_installation.full_path())
conf.set('PYTHON_VERSION', py_installation.language_version())
conf.set('APP_ID', app_id)
conf.set('PREFIX', prefix)
conf.set('VERSION', meson.project_version())
conf.set('pkgdatadir', pkgdatadir)
conf.set('libexecdir', libexecdir)

subdir('data')
subdir('cartridges')

subdir('build-aux/windows')

gnome.post_install(
  glib_compile_schemas: true,
  gtk_update_icon_cache: true,
)
