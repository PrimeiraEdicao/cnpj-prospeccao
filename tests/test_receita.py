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


MIRROR_HTML = '''
<html><body>
<a href="2026-08-09/">2026-08-09/</a>
<a href="2026-09-14/">2026-09-14/</a>
</body></html>
'''

MIRROR_FILES_HTML = '''
<html><body>
<a href="Empresas0.zip">Empresas0.zip</a>
<a href="Estabelecimentos0.zip">Estabelecimentos0.zip</a>
<a href="Simples.zip">Simples.zip</a>
</body></html>
'''


class _FakeResponse:
    def __init__(self, text):
        self.text = text
    def raise_for_status(self):
        return None


def test_discover_releases_falls_back_to_mirror(monkeypatch):
    def fail_propfind(url):
        raise receita.requests.ConnectionError("blocked")

    monkeypatch.setattr(receita, "_propfind", fail_propfind)
    monkeypatch.setattr(receita._SESSION, "get", lambda *args, **kwargs: _FakeResponse(MIRROR_HTML))
    releases = receita.discover_releases()
    assert [r.name for r in releases] == ["2026-08", "2026-09"]
    assert releases[-1].url.endswith("/2026-09-14/")


def test_list_zip_urls_from_mirror(monkeypatch):
    monkeypatch.setattr(receita._SESSION, "get", lambda *args, **kwargs: _FakeResponse(MIRROR_FILES_HTML))
    release = receita.Release("2026-09", receita.MIRROR_ROOT_URL + "2026-09-14/")
    urls = receita.list_zip_urls(release)
    assert len(urls) == 3
    assert urls[-1].endswith("Simples.zip")
