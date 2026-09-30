conf = configuration_data()
conf.set('PYTHON', python.find_installation('python3').full_path())
conf.set('VERSION', meson.project_version())
conf.set('APP_ID', app_id)
conf.set('DEVELOPER_NAME', developer_name)
conf.set('REPO_URL', repo_url)
conf.set('localedir', get_option('prefix') / get_option('localedir'))
conf.set('pkgdatadir', pkgdatadir)

configure_file(
  input: 'photoscanner.in',
  output: 'photoscanner',
  configuration: conf,
  install: true,
  install_dir: get_option('bindir'),
  install_mode: 'rwxr-xr-x',
)

install_data(
  'photoscanner/__init__.py',
  'photoscanner/editor.py',
  'photoscanner/export.py',
  'photoscanner/imageio.py',
  'photoscanner/main.py',
  'photoscanner/pdf.py',
  'photoscanner/processing.py',
  'photoscanner/settings.py',
  'photoscanner/window.py',
  install_dir: pkgdatadir / 'photoscanner',
)
