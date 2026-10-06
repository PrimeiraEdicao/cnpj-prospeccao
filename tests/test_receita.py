from src import receita


ROOT_XML = b'''<?xml version="1.0"?>
<d:multistatus xmlns:d="DAV:">
  <d:response><d:href>/public.php/webdav/</d:href></d:response>
  <d:response><d:href>/public.php/webdav/2026-07/</d:href></d:response>
  <d:response><d:href>/public.php/webdav/2026-09/</d:href></d:response>
  <d:response><d:href>/public.php/webdav/outros/</d:href></d:response>
</d:multistatus>'''

FILES_XML = b'''<?xml version="1.0"?>
<d:multistatus xmlns:d="DAV:">
  <d:response><d:href>/public.php/webdav/2026-09/</d:href></d:response>
  <d:response><d:href>/public.php/webdav/2026-09/Estabelecimentos0.zip</d:href></d:response>
  <d:response><d:href>/public.php/webdav/2026-09/Empresas0.zip</d:href></d:response>
  <d:response><d:href>/public.php/webdav/2026-09/Simples.zip</d:href></d:response>
</d:multistatus>'''


def test_parse_release_names():
    assert receita._release_names_from_dav(ROOT_XML) == ["2026-07", "2026-09"]


def test_resolve_latest_release(monkeypatch):
    monkeypatch.setattr(receita, "_propfind", lambda url: ROOT_XML)
    release = receita.resolve_release()
    assert release.name == "2026-09"
    assert release.url.endswith("/2026-09/")


def test_list_zip_urls_uses_current_public_share(monkeypatch):
    monkeypatch.setattr(receita, "_propfind", lambda url: FILES_XML)
    release = receita.Release("2026-09", f"{receita.WEBDAV_ROOT_URL}/2026-09/")
    urls = receita.list_zip_urls(release)
    assert len(urls) == 3
    assert all("/public.php/dav/files/" in url for url in urls)
    assert any(url.endswith("Simples.zip") for url in urls)


def test_select_files_is_case_insensitive():
    urls = [
        "https://host/Estabelecimentos0.zip",
        "https://host/Empresas0.zip",
    ]
    assert receita.select_files(urls, "estabele") == [urls[0]]
