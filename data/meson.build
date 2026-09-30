conf = configuration_data()
conf.set('APP_ID', app_id)
conf.set('DEVELOPER_ID', developer_id)
conf.set('DEVELOPER_NAME', developer_name)
conf.set('REPO_URL', repo_url)
conf.set('RAW_URL', raw_url)

desktop_in = configure_file(input: 'app.desktop.in.in', output: app_id + '.desktop.in', configuration: conf)
desktop_file = i18n.merge_file(
  input: desktop_in,
  output: app_id + '.desktop',
  type: 'desktop',
  po_dir: '../po',
  install: true,
  install_dir: get_option('datadir') / 'applications',
)

metainfo_in = configure_file(input: 'app.metainfo.xml.in.in', output: app_id + '.metainfo.xml.in', configuration: conf)
metainfo_file = i18n.merge_file(
  input: metainfo_in,
  output: app_id + '.metainfo.xml',
  po_dir: '../po',
  install: true,
  install_dir: get_option('datadir') / 'metainfo',
)

desktop_validate = find_program('desktop-file-validate', required: false)
if desktop_validate.found()
  test('validate-desktop', desktop_validate, args: [desktop_file])
endif
appstreamcli = find_program('appstreamcli', required: false)
if appstreamcli.found()
  test('validate-metainfo', appstreamcli, args: ['validate', '--no-net', '--explain', metainfo_file])
endif

install_data('icons/hicolor/scalable/apps/app.svg',
  rename: app_id + '.svg',
  install_dir: get_option('datadir') / 'icons/hicolor/scalable/apps')
install_data('icons/hicolor/symbolic/apps/app-symbolic.svg',
  rename: app_id + '-symbolic.svg',
  install_dir: get_option('datadir') / 'icons/hicolor/symbolic/apps')
