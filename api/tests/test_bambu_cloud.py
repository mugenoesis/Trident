"""The experimental Bambu cloud sign-in: the plugin download, the sign-in link, and what Bambu's redirect carries (names, never values)."""

from __future__ import annotations

import asyncio
import io
import zipfile
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import httpx
import pytest

from app import bambu_cloud
from app.bambu_cloud import BambuCloudError

ORIGIN = "http://192.168.1.3:8002"


def _zip(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def _bambu(
    plugin_zip: bytes, *, version: str = "02.00.00.37", seen: list[httpx.Request] | None = None
) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        if request.url.host == "api.bambulab.com":
            body = {
                "resources": [
                    {"type": "slicer/plugins/cloud", "version": version, "url": "https://cdn.example/linux.zip"}
                ]
            }
            return httpx.Response(200, json=body)
        return httpx.Response(200, content=plugin_zip)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# ---- the sign-in link ----


def test_the_sign_in_link_sends_bambu_back_to_trident():
    url = urlparse(bambu_cloud.sign_in_url(ORIGIN))
    assert (url.scheme, url.netloc, url.path) == ("https", "bambulab.com", "/sign-in")
    outer = parse_qs(url.query)
    assert outer["from"] == ["studio"] and outer["source"] == ["portal"]
    callback = urlparse(unquote(outer["to"][0]))
    assert (callback.netloc, callback.path) == ("bambulab.com", "/sign-in/callback")
    assert parse_qs(callback.query)["redirect_url"] == [f"{ORIGIN}/bambu-cloud/callback"]


@pytest.mark.parametrize(
    "origin", ["ftp://x", "http://a b", "http://x/path", "javascript:alert(1)", "", "http://x@evil.test"]
)
def test_only_a_plain_web_address_is_taken_as_trident_s_own(origin):
    with pytest.raises(BambuCloudError):
        bambu_cloud.sign_in_url(origin)


# ---- what Bambu's redirect carries ----


def test_a_callback_is_remembered_by_field_name_and_length_only():
    bambu_cloud.record_callback("/bambu-cloud/callback", {"ticket": "s3cret-ticket-value", "state": "abc"})
    seen = bambu_cloud.last_callback()
    assert seen is not None
    assert seen["fields"] == [{"name": "ticket", "length": 19}, {"name": "state", "length": 3}]
    assert "s3cret" not in repr(seen)


def test_the_path_after_the_callback_is_described_by_length_not_content():
    bambu_cloud.record_callback("/bambu-cloud/callback/abcdef", {})
    seen = bambu_cloud.last_callback()
    assert seen is not None and seen["extra_path_lengths"] == [6]
    assert "abcdef" not in repr(seen)


def test_nothing_is_remembered_before_a_callback():
    bambu_cloud.forget_callback()
    assert bambu_cloud.last_callback() is None


# ---- the plugin ----


def test_a_missing_plugin_is_reported_as_not_installed(tmp_path: Path):
    assert bambu_cloud.plugin_status(tmp_path) == {"installed": False}


def test_the_plugin_is_downloaded_checked_and_unpacked(tmp_path: Path):
    async def scenario():
        archive = _zip(
            {
                "libbambu_networking.so": b"net",
                "libBambuSource.so": b"src",
                "liblive555.so": b"live",
                "readme.txt": b"x",
            }
        )
        seen: list[httpx.Request] = []
        async with _bambu(archive, seen=seen) as client:
            status = await bambu_cloud.install_plugin(tmp_path, client=client)
        assert status["installed"] is True and status["version"] == "02.00.00.37"
        assert len(status["sha256"]) == 64
        assert (tmp_path / "libbambu_networking.so").read_bytes() == b"net"
        assert not (tmp_path / "readme.txt").exists()
        assert seen[0].headers["X-BBL-OS-Type"] == "linux"
        assert bambu_cloud.plugin_status(tmp_path) == status

    asyncio.run(scenario())


def test_an_archive_without_the_network_library_is_refused(tmp_path: Path):
    async def scenario():
        async with _bambu(_zip({"other.so": b"x"})) as client:
            with pytest.raises(BambuCloudError, match="libbambu_networking"):
                await bambu_cloud.install_plugin(tmp_path, client=client)
        assert bambu_cloud.plugin_status(tmp_path) == {"installed": False}

    asyncio.run(scenario())


def test_a_path_inside_the_archive_cannot_write_outside_the_folder(tmp_path: Path):
    async def scenario():
        target = tmp_path / "plugin"
        archive = _zip({"../../evil.so": b"x", "sub/libbambu_networking.so": b"net"})
        async with _bambu(archive) as client:
            await bambu_cloud.install_plugin(target, client=client)
        assert not (tmp_path.parent / "evil.so").exists()
        assert (target / "libbambu_networking.so").read_bytes() == b"net"

    asyncio.run(scenario())


def test_a_failed_download_is_reported_in_words(tmp_path: Path):
    async def scenario():
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(BambuCloudError, match="Bambu"):
                await bambu_cloud.install_plugin(tmp_path, client=client)

    asyncio.run(scenario())


# ---- the routes ----


@pytest.fixture
def experiment(monkeypatch, tmp_path):
    from app.config import settings

    monkeypatch.setattr(settings, "experimental_bambu_cloud", True)
    monkeypatch.setattr(settings, "orcaslicer_datadir", tmp_path)
    bambu_cloud.forget_callback()


def test_the_experiment_is_off_unless_asked_for(client):
    assert client.get("/bambu-cloud").json() == {"enabled": False}
    assert client.post("/bambu-cloud/plugin").status_code == 404
    assert client.get("/bambu-cloud/sign-in-url", params={"origin": ORIGIN}).status_code == 404
    assert client.get("/bambu-cloud/callback", params={"ticket": "x"}).status_code == 404


def test_the_status_says_when_the_plugin_is_missing(client, experiment):
    assert client.get("/bambu-cloud").json() == {"enabled": True, "plugin": {"installed": False}, "callback": None}


def test_the_sign_in_link_is_made_for_the_address_the_browser_uses(client, experiment):
    body = client.get("/bambu-cloud/sign-in-url", params={"origin": ORIGIN}).json()
    assert body["url"].startswith("https://bambulab.com/sign-in?")
    assert client.get("/bambu-cloud/sign-in-url", params={"origin": "javascript:alert(1)"}).status_code == 400


def test_the_callback_shows_and_remembers_only_what_arrived_not_its_value(client, experiment):
    page = client.get("/bambu-cloud/callback", params={"ticket": "s3cret-ticket-value"})
    assert page.status_code == 200 and "ticket (19 characters)" in page.text
    assert "s3cret" not in page.text
    status = client.get("/bambu-cloud").json()
    assert status["callback"]["fields"] == [{"name": "ticket", "length": 19}]
    assert "s3cret" not in str(status)


def test_a_callback_with_a_path_after_it_is_taken_too(client, experiment):
    assert client.get("/bambu-cloud/callback/abc/def", params={"x": "1"}).status_code == 200
    assert client.get("/bambu-cloud").json()["callback"]["extra_path_lengths"] == [3, 3]


def test_a_field_name_cannot_inject_markup_into_the_callback_page(client, experiment):
    page = client.get("/bambu-cloud/callback", params={"<script>alert(1)</script>": "1"})
    assert "<script>" not in page.text


def test_installing_the_plugin_reports_a_failure_in_words(client, experiment, monkeypatch):
    async def failing(folder):
        raise BambuCloudError("Couldn't get the plug-in from Bambu: timeout")

    monkeypatch.setattr(bambu_cloud, "install_plugin", failing)
    response = client.post("/bambu-cloud/plugin")
    assert response.status_code == 502 and "Bambu" in response.json()["detail"]
