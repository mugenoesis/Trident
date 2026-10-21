"""The experimental Bambu Cloud sign-in: the plug-in download, the sign-in link, reading the address the browser ends up on, and handing it
to Bambu's plug-in through the helper program. The helper is replaced by small shell scripts: what is tested is how the tokens reach it
(stdin only), that none comes back out, and that what it reports becomes a plain result the page can show."""

from __future__ import annotations

import asyncio
import io
import json
import zipfile
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import httpx
import pytest

from app import bambu_cloud
from app.bambu_cloud import BambuCloudError

PASTED = "http://localhost:41999/?access_token=AAA&refresh_token=RRR&expires_in=7776000&refresh_expires_in=7776000&redirect_url=x"

GOOD_STEPS = [
    {"step": "agent", "value": True},
    {"step": "get_my_profile", "value": {"http_code": 200, "result": 0}},
    {"step": "is_user_login", "value": True},
    {"step": "user_name", "value": "maker"},
    {
        "step": "get_user_print_info",
        "value": {
            "http_code": 200,
            "result": 0,
            "devices": [
                {"dev_product_name": "X1 Carbon", "dev_model_name": "BL-P001", "dev_name": "Shed", "dev_online": True},
                {"dev_product_name": "P1S", "dev_model_name": "C12", "dev_name": "Desk", "dev_online": False},
                {"dev_model_name": "N1", "dev_name": "string", "dev_online": "boolean"},
            ],
        },
    },
    {
        "step": "account_devices",
        "value": [
            {
                "dev_id": "00M00A000000000",
                "dev_access_code": "12345678",
                "dev_name": "Shed",
                "dev_online": True,
                "dev_product_name": "X1 Carbon",
            }
        ],
    },
]


def _zip(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def _bambu(plugin_zip: bytes, *, seen: list[httpx.Request] | None = None) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        if request.url.host == "api.bambulab.com":
            body = {
                "resources": [
                    {"type": "slicer/plugins/cloud", "version": "02.00.00.37", "url": "https://cdn.example/linux.zip"}
                ]
            }
            return httpx.Response(200, json=body)
        return httpx.Response(200, content=plugin_zip)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _helper(tmp_path: Path, body: str) -> Path:
    script = tmp_path / "helper"
    script.write_text("#!/bin/sh\ncat > /dev/null\n" + body)
    script.chmod(0o755)
    return script


def _helper_printing(tmp_path: Path, steps: list[dict]) -> Path:
    lines = "".join(f"echo '{json.dumps(s)}'\n" for s in steps)
    return _helper(tmp_path, lines)


# ---- the sign-in link ----


def test_the_sign_in_link_is_the_one_orca_builds_and_sends_the_browser_to_localhost():
    url = urlparse(bambu_cloud.sign_in_url())
    assert (url.scheme, url.netloc, url.path) == ("https", "bambulab.com", "/sign-in")
    outer = parse_qs(url.query)
    assert outer["from"] == ["studio"] and outer["source"] == ["portal"]
    back = urlparse(unquote(outer["to"][0]))
    assert (back.netloc, back.path) == ("bambulab.com", "/sign-in/callback")
    assert parse_qs(back.query)["redirect_url"] == ["http://localhost:41999"]


# ---- reading the address the browser ends up on ----


def test_the_tokens_are_read_from_the_pasted_address():
    tokens = bambu_cloud.parse_sign_in(PASTED)
    assert tokens == {
        "access_token": "AAA",
        "refresh_token": "RRR",
        "expires_in": "7776000",
        "refresh_expires_in": "7776000",
    }


def test_tokens_in_the_fragment_count_too():
    tokens = bambu_cloud.parse_sign_in("http://127.0.0.1:41999/#access_token=AAA&refresh_token=RRR")
    assert tokens["access_token"] == "AAA" and tokens["refresh_token"] == "RRR"


@pytest.mark.parametrize(
    "pasted",
    [
        "",
        "not a url",
        "ftp://localhost/?access_token=A&refresh_token=R",
        "https://evil.test/?access_token=A&refresh_token=R",
        "http://localhost:41999/?access_token=A",
        "http://localhost:41999/",
    ],
)
def test_only_a_localhost_address_that_carries_both_tokens_is_accepted(pasted):
    with pytest.raises(BambuCloudError, match="Paste"):
        bambu_cloud.parse_sign_in(pasted)


def test_an_error_about_a_bad_address_never_repeats_what_was_pasted():
    with pytest.raises(BambuCloudError) as caught:
        bambu_cloud.parse_sign_in("https://evil.test/?access_token=SECRET&refresh_token=SECRET2")
    assert "SECRET" not in str(caught.value)


# ---- what the plug-in reports, as a result ----


def test_a_good_session_becomes_the_user_and_their_printers():
    result = bambu_cloud.summarize(GOOD_STEPS)
    assert result["signed_in"] is True and result["user"] == "maker" and result["problem"] is None
    assert result["printers"] == [
        {"model": "X1 Carbon", "name": "Shed", "online": True},
        {"model": "P1S", "name": "Desk", "online": False},
        {"model": "N1", "name": None, "online": None},
    ]


def test_a_certificate_style_failure_is_explained_in_words():
    steps = [
        {"step": "get_my_profile", "value": {"http_code": 60, "result": -1}},
        {"step": "is_user_login", "value": False},
    ]
    result = bambu_cloud.summarize(steps)
    assert result["signed_in"] is False and result["printers"] == []
    assert "60" in result["problem"] and "reach" in result["problem"].lower()


def test_a_plug_in_that_does_not_accept_the_sign_in_says_so():
    steps = [
        {"step": "get_my_profile", "value": {"http_code": 200, "result": 0}},
        {"step": "is_user_login", "value": False},
    ]
    assert "sign-in" in bambu_cloud.summarize(steps)["problem"]


def test_a_helper_that_stopped_is_reported_with_its_exit_code():
    result = bambu_cloud.summarize([{"step": "agent", "value": True}, {"step": "helper_exit", "value": 139}])
    assert result["signed_in"] is False and "139" in result["problem"]


def test_a_helper_error_step_is_passed_on_in_words():
    assert "dlopen" in bambu_cloud.summarize([{"step": "error", "value": "dlopen: no such file"}])["problem"]


def test_no_steps_at_all_is_a_problem():
    assert bambu_cloud.summarize([])["problem"]


# ---- the plug-in ----


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


# ---- handing the sign-in to the plug-in (through the helper program) ----

TOKENS = {
    "access_token": "TOKEN-A",
    "refresh_token": "TOKEN-R",
    "expires_in": "7776000",
    "refresh_expires_in": "7776000",
}


def test_the_tokens_reach_the_helper_on_stdin_only_and_its_steps_come_back(tmp_path: Path):
    seen = tmp_path / "stdin.json"
    script = tmp_path / "helper"
    script.write_text(f'#!/bin/sh\ncat > {seen}\necho \'{{"step":"is_user_login","value":true}}\'\n')
    script.chmod(0o755)
    steps = asyncio.run(bambu_cloud.run_session(tmp_path, tmp_path, tmp_path, script, TOKENS))
    assert steps == [{"step": "is_user_login", "value": True}]
    sent = json.loads(seen.read_text())
    assert (
        sent["access_token"] == "TOKEN-A" and sent["refresh_token"] == "TOKEN-R" and sent["plugin_dir"] == str(tmp_path)
    )


def test_a_token_in_the_helper_output_is_never_passed_on(tmp_path: Path):
    script = _helper(tmp_path, 'echo \'{"step":"oops","value":"TOKEN-A"}\'\necho \'{"step":"fine","value":1}\'\n')
    steps = asyncio.run(bambu_cloud.run_session(tmp_path, tmp_path, tmp_path, script, TOKENS))
    assert "TOKEN" not in repr(steps) and steps[-1] == {"step": "fine", "value": 1}


def test_a_helper_that_crashes_leaves_the_steps_before_the_crash(tmp_path: Path):
    script = _helper(tmp_path, 'echo \'{"step":"start","value":0}\'\nkill -SEGV $$\n')
    steps = asyncio.run(bambu_cloud.run_session(tmp_path, tmp_path, tmp_path, script, TOKENS))
    assert steps[0] == {"step": "start", "value": 0}
    assert steps[-1]["step"] == "helper_exit" and steps[-1]["value"] != 0


def test_a_missing_helper_is_said_in_words(tmp_path: Path):
    with pytest.raises(BambuCloudError, match="helper"):
        asyncio.run(bambu_cloud.run_session(tmp_path, tmp_path, tmp_path, tmp_path / "absent", TOKENS))


# ---- the routes ----


@pytest.fixture
def experiment(monkeypatch, tmp_path):
    from app.config import settings

    monkeypatch.setattr(settings, "experimental_bambu_cloud", True)
    monkeypatch.setattr(settings, "orcaslicer_datadir", tmp_path)


def test_the_experiment_is_off_unless_asked_for(client):
    assert client.get("/bambu-cloud").json() == {"enabled": False}
    assert client.post("/bambu-cloud/plugin").status_code == 404
    assert client.get("/bambu-cloud/sign-in-url").status_code == 404
    assert client.post("/bambu-cloud/account", json={"url": PASTED}).status_code == 404


def test_the_status_says_when_the_plugin_is_missing(client, experiment):
    assert client.get("/bambu-cloud").json() == {"enabled": True, "plugin": {"installed": False}, "can_print": False}


def test_the_sign_in_link_needs_no_address_of_ours(client, experiment):
    assert client.get("/bambu-cloud/sign-in-url").json()["url"].startswith("https://bambulab.com/sign-in?")


def test_installing_the_plugin_reports_a_failure_in_words(client, experiment, monkeypatch):
    async def failing(folder):
        raise BambuCloudError("Couldn't get the plug-in from Bambu: timeout")

    monkeypatch.setattr(bambu_cloud, "install_plugin", failing)
    response = client.post("/bambu-cloud/plugin")
    assert response.status_code == 502 and "Bambu" in response.json()["detail"]


def test_connecting_hands_the_sign_in_to_the_plugin_and_returns_the_user_and_printers(
    client, experiment, monkeypatch, tmp_path
):
    from app.config import settings

    monkeypatch.setattr(settings, "bambu_helper_path", _helper_printing(tmp_path, GOOD_STEPS))
    response = client.post("/bambu-cloud/account", json={"url": PASTED})
    assert response.status_code == 200
    body = response.json()
    assert body["signed_in"] is True and body["user"] == "maker" and body["printers"][0]["model"] == "X1 Carbon"
    assert "AAA" not in response.text and "RRR" not in response.text


def test_a_failed_connection_is_a_result_with_a_reason_not_an_error_page(client, experiment, monkeypatch, tmp_path):
    from app.config import settings

    steps = [
        {"step": "get_my_profile", "value": {"http_code": 60, "result": -1}},
        {"step": "is_user_login", "value": False},
    ]
    monkeypatch.setattr(settings, "bambu_helper_path", _helper_printing(tmp_path, steps))
    response = client.post("/bambu-cloud/account", json={"url": PASTED})
    assert response.status_code == 200 and response.json()["signed_in"] is False and "60" in response.json()["problem"]


def test_connecting_with_a_bad_address_is_a_400_in_words(client, experiment):
    response = client.post(
        "/bambu-cloud/account", json={"url": "https://evil.test/?access_token=SECRET&refresh_token=S2"}
    )
    assert response.status_code == 400 and "Paste" in response.json()["detail"] and "SECRET" not in response.text


def test_nothing_is_kept_between_connections(client, experiment, monkeypatch, tmp_path):
    from app.config import settings

    monkeypatch.setattr(settings, "bambu_helper_path", _helper_printing(tmp_path, GOOD_STEPS))
    client.post("/bambu-cloud/account", json={"url": PASTED})
    assert client.post("/bambu-cloud/account", json={"url": "http://localhost:41999/"}).status_code == 400
    assert "AAA" not in client.get("/bambu-cloud").text


# ---- starting a print through the plug-in ----


def _plugin(tmp_path: Path, version: str) -> Path:
    folder = tmp_path / "plugin"
    folder.mkdir()
    (folder / bambu_cloud.NETWORK_LIBRARY).write_bytes(b"x")
    (folder / "plugin.json").write_text(json.dumps({"version": version}))
    return folder


def test_only_a_plugin_of_the_series_the_helper_knows_is_asked_to_print(tmp_path: Path):
    assert bambu_cloud.can_print(_plugin(tmp_path, "02.08.04.60"))
    other = tmp_path / "other"
    other.mkdir()
    assert not bambu_cloud.can_print(_plugin(other, "02.00.00.37"))
    assert not bambu_cloud.can_print(tmp_path / "nothing")


def test_the_filament_mapping_follows_the_ams_or_the_external_spool():
    ams = bambu_cloud.ams_mapping(2, True)
    assert json.loads(ams["ams_mapping"]) == [0, 1]
    assert json.loads(ams["ams_mapping2"]) == [{"ams_id": 0, "slot_id": 0}, {"ams_id": 0, "slot_id": 1}]
    assert [i["ams"] for i in json.loads(ams["ams_mapping_info"])] == [0, 1]
    spool = bambu_cloud.ams_mapping(1, False)
    assert json.loads(spool["ams_mapping"]) == [-1] and json.loads(spool["ams_mapping2"]) == [
        {"ams_id": 255, "slot_id": 255}
    ]


def test_the_filaments_are_counted_from_the_sliced_3mf(tmp_path: Path):
    three_mf = tmp_path / "a.gcode.3mf"
    with zipfile.ZipFile(three_mf, "w") as z:
        z.writestr("Metadata/slice_info.config", '<plate><filament id="1"/><filament id="2"/></plate>')
    assert bambu_cloud.filament_count(three_mf) == 2
    assert bambu_cloud.filament_count(tmp_path / "missing.3mf") == 1


JOB = {"dev_id": "SERIAL0001", "access_code": "ACCESS99", "file": "/x.gcode.3mf"}


def test_a_print_the_plugin_accepts_is_a_success_and_the_job_reaches_the_helper_on_stdin(tmp_path: Path):
    folder = _plugin(tmp_path, "02.08.04.60")
    seen = tmp_path / "stdin.json"
    script = tmp_path / "helper"
    script.write_text(f'#!/bin/sh\ncat > {seen}\necho \'{{"step":"print_result","value":0}}\'\n')
    script.chmod(0o755)
    asyncio.run(bambu_cloud.start_print(folder, tmp_path, tmp_path, script, JOB))
    sent = json.loads(seen.read_text())
    assert sent["action"] == "print" and sent["access_code"] == "ACCESS99" and sent["file"] == "/x.gcode.3mf"


def test_a_print_the_plugin_refuses_says_why_without_the_access_code(tmp_path: Path):
    folder = _plugin(tmp_path, "02.08.04.60")
    steps = [
        {"step": "is_user_login", "value": True},
        {"step": "progress", "value": {"stage": 7, "code": -3010, "message": "upload to ACCESS99 failed"}},
        {"step": "print_result", "value": -3010},
    ]
    with pytest.raises(BambuCloudError) as caught:
        asyncio.run(bambu_cloud.start_print(folder, tmp_path, tmp_path, _helper_printing(tmp_path, steps), JOB))
    assert "-3010" in str(caught.value) and "upload to" in str(caught.value) and "ACCESS99" not in str(caught.value)


def test_a_print_without_a_sign_in_asks_for_one(tmp_path: Path):
    folder = _plugin(tmp_path, "02.08.04.60")
    steps = [{"step": "is_user_login", "value": False}, {"step": "print_result", "value": -1}]
    with pytest.raises(BambuCloudError, match="sign in again"):
        asyncio.run(bambu_cloud.start_print(folder, tmp_path, tmp_path, _helper_printing(tmp_path, steps), JOB))


def test_an_old_plugin_is_never_asked_to_print(tmp_path: Path):
    folder = _plugin(tmp_path, "02.00.00.37")
    with pytest.raises(BambuCloudError, match="cannot start prints"):
        asyncio.run(bambu_cloud.start_print(folder, tmp_path, tmp_path, _helper_printing(tmp_path, []), JOB))
