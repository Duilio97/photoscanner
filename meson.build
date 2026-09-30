project('photoscanner',
  version: '1.0.0',
  meson_version: '>= 1.0.0',
  license: 'GPL-3.0-or-later',
)

# Publisher: change these (and the Flatpak manifest name/"id") before publishing,
# or run build-aux/set-publisher.sh.
github_user = 'Duilio97'
developer_name = 'Duilio'
app_id = 'io.github.duilio97.PhotoScanner'
developer_id = 'io.github.duilio97'
repo_url = 'https://github.com/' + github_user + '/photoscanner'
raw_url = 'https://raw.githubusercontent.com/' + github_user + '/photoscanner/main'

i18n = import('i18n')
gnome = import('gnome')
python = import('python')

pkgdatadir = get_option('prefix') / get_option('datadir') / meson.project_name()

subdir('src')
subdir('data')
subdir('po')

gnome.post_install(
  gtk_update_icon_cache: true,
  update_desktop_database: true,
)
