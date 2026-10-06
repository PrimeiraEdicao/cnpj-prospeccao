import io
import zipfile

import pytest

from src import receita


def zip_bytes():
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        archive.writestr("CNAECSV", '"4712100";"Comercio"\n')
    return data.getvalue()


class Response:
    def __init__(self, body, status=200, headers=None, interrupted=False):
        self.body, self.status_code = body, status
        self.headers = headers or {"Content-Length": str(len(body))}
        self.interrupted = interrupted

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size):
        yield self.body
        if self.interrupted:
            raise receita.requests.ConnectionError("transfer interrupted")


@pytest.fixture(autouse=True)
def no_retry_delay(monkeypatch):
    monkeypatch.setattr(receita.time, "sleep", lambda _: None)


def test_interrupted_zip_download_resumes_without_duplicate_bytes(tmp_path, monkeypatch):
    content = zip_bytes()
    requests = []
    responses = iter([
        Response(content[:20], headers={"Content-Length": str(len(content))}, interrupted=True),
        Response(content[20:], 206, {"Content-Range": f"bytes 20-{len(content)-1}/{len(content)}"}),
    ])
    def get(url, **kwargs):
        requests.append(kwargs["headers"])
        return next(responses)
    monkeypatch.setattr(receita._SESSION, "get", get)
    result = receita.download("https://example.test/Cnaes.zip", tmp_path / "file.zip", attempts=2)
    assert result.read_bytes() == content
    assert requests[1]["Range"] == "bytes=20-"
    assert not (tmp_path / "file.zip.part").exists()


def test_ignored_range_restarts_download(tmp_path, monkeypatch):
    content = zip_bytes()
    (tmp_path / "file.zip.part").write_bytes(b"old bytes")
    monkeypatch.setattr(receita._SESSION, "get", lambda *a, **k: Response(content))
    result = receita.download("https://example.test/Cnaes.zip", tmp_path / "file.zip")
    assert result.read_bytes() == content


def test_wrong_range_cannot_corrupt_existing_bytes(tmp_path, monkeypatch):
    (tmp_path / "file.zip.part").write_bytes(b"old bytes")
    response = Response(b"more bytes", 206, {"Content-Range": "bytes 0-9/19"})
    monkeypatch.setattr(receita._SESSION, "get", lambda *a, **k: response)
    with pytest.raises(RuntimeError):
        receita.download("https://example.test/Cnaes.zip", tmp_path / "file.zip", attempts=1)
    assert not (tmp_path / "file.zip").exists()
    assert not (tmp_path / "file.zip.part").exists()


@pytest.mark.parametrize("response", [
    Response(b"<html>server error</html>"),
    Response(zip_bytes()[:20], headers={"Content-Length": str(len(zip_bytes()))}),
])
def test_truncated_or_html_response_is_not_published_as_zip(tmp_path, monkeypatch, response):
    monkeypatch.setattr(receita._SESSION, "get", lambda *a, **k: response)
    with pytest.raises(RuntimeError):
        receita.download("https://example.test/Cnaes.zip", tmp_path / "file.zip", attempts=1)
    assert not (tmp_path / "file.zip").exists()


def test_download_fallback_uses_same_month_and_restarts_bytes(tmp_path, monkeypatch):
    url = receita.DIRECT_FILES_ROOT_URL + "/2026-09/Cnaes.zip"
    mirror = receita.Release("2026-09", receita.MIRROR_ROOT_URL + "2026-09-14/")
    mirror_url = mirror.url + "Cnaes.zip"
    (tmp_path / "file.zip.part").write_bytes(b"official partial")
    seen = []
    def get(candidate, **kwargs):
        seen.append(candidate)
        if candidate == url:
            raise receita.requests.ConnectionError("official offline")
        assert candidate == mirror_url
        assert "Range" not in kwargs["headers"]
        return Response(zip_bytes())
    monkeypatch.setattr(receita._SESSION, "get", get)
    monkeypatch.setattr(receita, "_mirror_release_for_month", lambda month: mirror if month == "2026-09" else None)
    monkeypatch.setattr(receita, "_list_mirror_zip_urls", lambda rel: [mirror_url])
    result = receita.download(url, tmp_path / "file.zip", attempts=1)
    assert result.read_bytes() == zip_bytes()
    assert seen == [url, mirror_url]


def test_failed_enter_removes_temporary_download(tmp_path, monkeypatch):
    def fail(url, destination):
        destination.with_suffix(".zip.part").write_bytes(b"partial")
        raise RuntimeError("download failed")
    monkeypatch.setattr(receita, "download", fail)
    with pytest.raises(RuntimeError):
        with receita.TempDownload("https://example.test/Cnaes.zip", tmp_path):
            pass
    assert list(tmp_path.iterdir()) == []


def test_incomplete_snapshot_is_rejected_before_mei_filter():
    urls = [f"https://example.test/{kind}{i}.zip" for kind in ("Estabelecimentos", "Empresas", "Socios") for i in range(10)]
    urls += [f"https://example.test/{name}.zip" for name in ("Simples", "Cnaes", "Qualificacoes")]
    assert receita.validate_zip_catalog(urls)["Socios"] == 10
    with pytest.raises(RuntimeError, match="Simples"):
        receita.validate_zip_catalog([url for url in urls if "Simples" not in url])
    with pytest.raises(RuntimeError, match="Estabelecimentos"):
        receita.validate_zip_catalog([url for url in urls if "Estabelecimentos9" not in url])
