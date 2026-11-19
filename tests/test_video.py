"""Tests for resolving and downloading video modules."""

from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any, Self

import pytest

from behance_dl.client import detected_suffix
from behance_dl.errors import DownloadError
from behance_dl.models import EmbedAsset
from behance_dl.video import (
    build_rendition_url,
    choose_height,
    download_videos,
    downloaded_path,
    is_ccv_media_url,
    is_ccv_player_url,
    is_external_video_url,
    no_reuse,
    parse_sources,
    playlist_heights,
    rendition_height,
    resolve_behance_video,
    reuse_downloaded,
    video_assets,
    video_file_name,
)
from conftest import CDN, FakeClient

ASSET_ID = "MvcfZFbza4U"
PLAYER_URL = f"https://www-ccv.adobe.io/v1/player/ccv/{ASSET_ID}/embed?api_key=behance1"
TOKEN = "hdnts=st%3D1%7Eexp%3D2%7Eacl%3D%2Fz%2F"  # noqa: S105  # fixture token, not a credential
PLAYER_MARKER = "/v1/player/ccv/"
PLAYLIST_MARKER = "master.m3u8"
MEDIA_BASE = f"https://cdn-prod-ccv.adobe.com/{ASSET_ID}/rend"
MP4_576 = f"{MEDIA_BASE}/{ASSET_ID}_576.mp4?{TOKEN}"
PLAYLIST = f"{MEDIA_BASE}/master.m3u8?{TOKEN}"
PLAYER_PAGE = f'<html><video><source src="{PLAYLIST}"><source src="{MP4_576}"></video></html>'
MASTER = (
    "#EXTM3U\n"
    "#EXT-X-STREAM-INF:PROGRAM-ID=1,BANDWIDTH=1675660,RESOLUTION=768x576\nhls_576/index.m3u8\n"
    "#EXT-X-STREAM-INF:PROGRAM-ID=1,BANDWIDTH=2255291,RESOLUTION=960x720\nhls_720/index.m3u8\n"
    "#EXT-X-STREAM-INF:PROGRAM-ID=1,BANDWIDTH=3332344,RESOLUTION=1440x1080\nhls_1080/index.m3u8\n"
)
MP4_BYTES = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 32
YOUTUBE_URL = "https://www.youtube.com/embed/abc"
FIGMA_URL = "https://embed.figma.com/proto/x/y"


def embed(source_url: str, position: int = 5) -> EmbedAsset:
    """Build an embed pointing at a source URL."""
    return EmbedAsset(
        position=position,
        module_id=1,
        caption="",
        source_url=source_url,
        width=800,
        height=450,
    )


def fake_client(media: dict[str, bytes] | None = None) -> FakeClient:
    """Return a client that serves the player page, the playlist, and the mp4 renditions."""
    return FakeClient(
        texts={PLAYER_MARKER: PLAYER_PAGE, PLAYLIST_MARKER: MASTER},
        images=media if media is not None else {f"{MEDIA_BASE}/{ASSET_ID}_1080.mp4": MP4_BYTES},
    )


def install_fake_youtube_dl(monkeypatch: pytest.MonkeyPatch, fake: type) -> None:
    """Put a fake yt_dlp module in front of the optional import."""
    module = types.ModuleType("yt_dlp")
    monkeypatch.setattr(module, "YoutubeDL", fake, raising=False)
    monkeypatch.setitem(sys.modules, "yt_dlp", module)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (PLAYER_URL, True),
        ("http://www-ccv.adobe.io/v1/player/ccv/x/embed", False),
        ("https://evil.example.com/v1/player/ccv/x/embed", False),
        ("https://www-ccv.adobe.io.evil.com/x", False),
        ("file://www-ccv.adobe.io/x", False),
        (MP4_576, False),
    ],
)
def test_is_ccv_player_url(url: str, expected: bool) -> None:
    assert is_ccv_player_url(url) is expected


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (MP4_576, True),
        (PLAYLIST, True),
        ("http://cdn-prod-ccv.adobe.com/x.mp4", False),
        ("https://cdn-prod-ccv.adobe.com.evil.com/x.mp4", False),
        (f"{CDN}/1400/a.png", False),
        ("file://cdn-prod-ccv.adobe.com/x.mp4", False),
        ("", False),
    ],
)
def test_is_ccv_media_url(url: str, expected: bool) -> None:
    assert is_ccv_media_url(url) is expected


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (YOUTUBE_URL, True),
        ("https://youtu.be/abc", True),
        ("https://player.vimeo.com/video/1", True),
        ("https://www.dailymotion.com/embed/video/x1", True),
        (FIGMA_URL, False),
        ("https://evil.example.com/youtube.com", False),
        ("https://youtube.com.evil.com/x", False),
        ("https://notyoutube.com/x", False),
        ("file://youtube.com/etc/passwd", False),
        ("http://www.youtube.com/embed/x", False),
        ("", False),
    ],
)
def test_is_external_video_url(url: str, expected: bool) -> None:
    assert is_external_video_url(url) is expected


def test_parse_sources_keeps_only_allowed_media() -> None:
    page = (
        f'<source src="{PLAYLIST}">'
        f'<source src="{MP4_576}">'
        '<source src="https://evil.example.com/x.mp4">'
        '<source src="https://cdn-prod-ccv.adobe.com/x.mp4?a=1&amp;b=2">'
    )

    assert parse_sources(page) == [
        PLAYLIST,
        MP4_576,
        "https://cdn-prod-ccv.adobe.com/x.mp4?a=1&b=2",
    ]


def test_playlist_heights_are_sorted_tallest_first() -> None:
    assert playlist_heights(MASTER) == [1080, 720, 576]
    assert playlist_heights("#EXTM3U") == []


@pytest.mark.parametrize(
    ("max_height", "expected"),
    [(None, 1080), (1080, 1080), (900, 720), (720, 720), (600, 576), (100, 576)],
)
def test_choose_height_respects_the_cap(max_height: int | None, expected: int) -> None:
    assert choose_height([576, 1080, 720], max_height) == expected


def test_choose_height_returns_none_without_renditions() -> None:
    assert choose_height([], None) is None


def test_build_rendition_url_keeps_the_token() -> None:
    assert build_rendition_url(PLAYLIST, ASSET_ID, 1080) == (
        f"{MEDIA_BASE}/{ASSET_ID}_1080.mp4?{TOKEN}"
    )


@pytest.mark.parametrize(
    ("url", "expected"),
    [(MP4_576, 576), (f"{MEDIA_BASE}/{ASSET_ID}_1080.mp4", 1080), ("", 0)],
)
def test_rendition_height(url: str, expected: int) -> None:
    assert rendition_height(url) == expected


def test_resolve_prefers_the_tallest_playlist_rendition() -> None:
    resolved = resolve_behance_video(fake_client(), embed(PLAYER_URL), None)

    assert resolved.url == f"{MEDIA_BASE}/{ASSET_ID}_1080.mp4?{TOKEN}"
    assert resolved.height == 1080
    assert resolved.fallback_url == MP4_576


def test_resolve_respects_the_height_cap() -> None:
    resolved = resolve_behance_video(fake_client(), embed(PLAYER_URL), 720)

    assert resolved.url == f"{MEDIA_BASE}/{ASSET_ID}_720.mp4?{TOKEN}"
    assert resolved.height == 720


def test_resolve_falls_back_to_the_listed_mp4() -> None:
    client = FakeClient(texts={PLAYER_MARKER: f'<source src="{MP4_576}">'})

    resolved = resolve_behance_video(client, embed(PLAYER_URL), None)

    assert resolved.url == MP4_576
    assert resolved.height == 576


def test_resolve_fails_when_the_player_offers_nothing() -> None:
    client = FakeClient(texts={PLAYER_MARKER: "<html>no sources</html>"})

    with pytest.raises(DownloadError):
        resolve_behance_video(client, embed(PLAYER_URL), None)


def test_resolve_rejects_a_non_player_url() -> None:
    with pytest.raises(DownloadError):
        resolve_behance_video(FakeClient(), embed(FIGMA_URL), None)


def test_video_assets_keeps_videos_and_drops_interactive_embeds() -> None:
    embeds = [
        embed(PLAYER_URL, 5),
        embed(FIGMA_URL, 6),
        embed(YOUTUBE_URL, 7),
        embed("", 8),
    ]

    assert [entry.position for entry in video_assets(embeds)] == [5, 7]


def test_download_videos_writes_the_best_rendition(tmp_path: Path) -> None:
    failed = download_videos(
        fake_client(), [embed(PLAYER_URL)], tmp_path, max_height=None, reuse=reuse_downloaded(None)
    )

    assert failed == 0
    assert (tmp_path / f"005_{ASSET_ID}_1080.mp4").read_bytes() == MP4_BYTES


def test_download_videos_respects_the_height_cap(tmp_path: Path) -> None:
    media = {f"{MEDIA_BASE}/{ASSET_ID}_720.mp4": MP4_BYTES}

    failed = download_videos(
        fake_client(media),
        [embed(PLAYER_URL)],
        tmp_path,
        max_height=720,
        reuse=reuse_downloaded(720),
    )

    assert failed == 0
    assert (tmp_path / f"005_{ASSET_ID}_720.mp4").exists()


def test_download_videos_reuses_an_existing_file(tmp_path: Path) -> None:
    (tmp_path / f"005_{ASSET_ID}_1080.mp4").write_bytes(MP4_BYTES)
    client = fake_client()

    assert (
        download_videos(
            client, [embed(PLAYER_URL)], tmp_path, max_height=None, reuse=reuse_downloaded(None)
        )
        == 0
    )
    assert client.requested == []


def test_download_videos_skips_interactive_embeds(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    failed = download_videos(
        FakeClient(), [embed(FIGMA_URL, 3)], tmp_path, max_height=None, reuse=reuse_downloaded(None)
    )

    assert failed == 0
    assert list(tmp_path.iterdir()) == []
    assert "not a video" in capsys.readouterr().err


def test_download_videos_counts_a_failure_and_keeps_going(tmp_path: Path) -> None:
    other_id = "OtherAsset1"
    other_player = f"https://www-ccv.adobe.io/v1/player/ccv/{other_id}/embed"
    client = fake_client()
    embeds = [embed(other_player, 5), embed(PLAYER_URL, 6)]

    failed = download_videos(
        client, embeds, tmp_path, max_height=None, reuse=reuse_downloaded(None)
    )

    assert failed == 1
    assert (tmp_path / f"006_{ASSET_ID}_1080.mp4").exists()


def test_download_videos_reports_a_missing_extra(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(sys.modules, "yt_dlp", None)

    failed = download_videos(
        FakeClient(), [embed(YOUTUBE_URL)], tmp_path, max_height=None, reuse=reuse_downloaded(None)
    )

    assert failed == 1
    assert "behance-dl[video]" in capsys.readouterr().err


def test_download_videos_reuses_a_downloaded_external_file(tmp_path: Path) -> None:
    (tmp_path / "005_abc.mp4").write_bytes(MP4_BYTES)

    assert (
        download_videos(
            FakeClient(),
            [embed(YOUTUBE_URL)],
            tmp_path,
            max_height=None,
            reuse=reuse_downloaded(None),
        )
        == 0
    )


def test_detected_suffix_recognises_video_containers(tmp_path: Path) -> None:
    mp4 = tmp_path / "sample"
    mp4.write_bytes(MP4_BYTES)
    webm = tmp_path / "sample.webm"
    webm.write_bytes(b"\x1aE\xdf\xa3" + b"\x00" * 16)

    assert detected_suffix(mp4) == ".mp4"
    assert detected_suffix(webm) == ".webm"


def test_fallback_names_the_file_after_the_rendition_it_fetched(tmp_path: Path) -> None:
    media = {f"{MEDIA_BASE}/{ASSET_ID}_576.mp4": MP4_BYTES}

    failed = download_videos(
        fake_client(media),
        [embed(PLAYER_URL)],
        tmp_path,
        max_height=None,
        reuse=reuse_downloaded(None),
    )

    assert failed == 0
    assert [path.name for path in tmp_path.iterdir()] == [f"005_{ASSET_ID}_576.mp4"]


def test_download_videos_ignores_stale_non_video_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(sys.modules, "yt_dlp", None)
    (tmp_path / "005_old.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8)
    (tmp_path / "005_abc.f137.mp4.part").write_bytes(MP4_BYTES)

    failed = download_videos(
        FakeClient(), [embed(YOUTUBE_URL)], tmp_path, max_height=None, reuse=reuse_downloaded(None)
    )

    assert failed == 1


def test_force_refetches_an_existing_video(tmp_path: Path) -> None:
    (tmp_path / f"005_{ASSET_ID}_1080.mp4").write_bytes(b"stale")
    client = fake_client()

    failed = download_videos(client, [embed(PLAYER_URL)], tmp_path, max_height=None, reuse=no_reuse)

    assert failed == 0
    assert client.requested
    assert (tmp_path / f"005_{ASSET_ID}_1080.mp4").read_bytes() == MP4_BYTES


def test_existing_video_taller_than_the_cap_is_replaced(tmp_path: Path) -> None:
    (tmp_path / f"005_{ASSET_ID}_1080.mp4").write_bytes(MP4_BYTES)
    media = {f"{MEDIA_BASE}/{ASSET_ID}_720.mp4": MP4_BYTES}
    client = fake_client(media)

    failed = download_videos(
        client, [embed(PLAYER_URL)], tmp_path, max_height=720, reuse=reuse_downloaded(720)
    )

    assert failed == 0
    assert client.requested
    assert (tmp_path / f"005_{ASSET_ID}_720.mp4").exists()
    assert not (tmp_path / f"005_{ASSET_ID}_1080.mp4").exists()


def test_external_video_runs_yt_dlp_and_keeps_the_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    saved: list[str] = []

    class FakeYoutubeDL:
        def __init__(self, options: dict[str, Any]) -> None:
            self._options = options
            self._path: Path | None = None

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *exc_info: object) -> None:
            return None

        def extract_info(self, url: str, download: bool = False) -> dict[str, object]:
            saved.append(url)
            name = self._options["outtmpl"].replace("%(id)s", "abc").replace("%(ext)s", "mp4")
            path = Path(self._options["paths"]["home"]) / name
            path.write_bytes(MP4_BYTES)
            return {"id": "abc", "ext": "mp4", "requested_downloads": [{"filepath": str(path)}]}

    install_fake_youtube_dl(monkeypatch, FakeYoutubeDL)

    failed = download_videos(
        FakeClient(), [embed(YOUTUBE_URL)], tmp_path, max_height=None, reuse=reuse_downloaded(None)
    )

    assert failed == 0
    assert saved == [YOUTUBE_URL]
    assert (tmp_path / "005_abc.mp4").exists()


def test_video_file_name_sanitizes_a_remote_stem() -> None:
    name = video_file_name(5, "", 0, "https://cdn-prod-ccv.adobe.com/x/a:b|c.mp4")

    assert name == "005_a-b-c.mp4"


def test_video_file_name_prefers_the_validated_parts() -> None:
    name = video_file_name(5, ASSET_ID, 1080, "https://cdn-prod-ccv.adobe.com/x/y.mp4")

    assert name == f"005_{ASSET_ID}_1080.mp4"


def test_downloaded_path_prefers_the_first_playlist_entry() -> None:
    info = {
        "id": "playlist-id",
        "entries": [{"id": "video-id", "requested_downloads": [{"filepath": "/saved/a.mp4"}]}],
    }

    assert downloaded_path(info) == Path("/saved/a.mp4")


def test_downloaded_path_ignores_records_without_a_file() -> None:
    assert downloaded_path({"id": "abc", "ext": "mp4"}) is None
    assert downloaded_path({"entries": []}) is None
    assert downloaded_path(None) is None


def test_playlist_embed_saves_one_entry_and_reports_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class PlaylistYoutubeDL:
        def __init__(self, options: dict[str, Any]) -> None:
            self._options = options

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *exc_info: object) -> None:
            return None

        def extract_info(self, url: str, download: bool = False) -> dict[str, object]:
            saved = Path(self._options["paths"]["home"]) / "005_videoid.mp4"
            saved.write_bytes(MP4_BYTES)
            return {
                "id": "playlistid",
                "ext": "NA",
                "entries": [
                    {
                        "id": "videoid",
                        "ext": "mp4",
                        "requested_downloads": [{"filepath": str(saved)}],
                    }
                ],
            }

    install_fake_youtube_dl(monkeypatch, PlaylistYoutubeDL)

    failed = download_videos(
        FakeClient(), [embed(YOUTUBE_URL)], tmp_path, max_height=None, reuse=no_reuse
    )

    assert failed == 0
    assert (tmp_path / "005_videoid.mp4").exists()


def test_external_options_keep_one_item_and_a_staging_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorded: list[dict[str, Any]] = []

    class RecordingYoutubeDL:
        def __init__(self, options: dict[str, Any]) -> None:
            self._options = options
            recorded.append(options)

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *exc_info: object) -> None:
            return None

        def extract_info(self, url: str, download: bool = False) -> dict[str, object]:
            saved = Path(self._options["paths"]["home"]) / "005_abc.mp4"
            saved.write_bytes(MP4_BYTES)
            return {"id": "abc", "requested_downloads": [{"filepath": str(saved)}]}

    install_fake_youtube_dl(monkeypatch, RecordingYoutubeDL)

    failed = download_videos(
        FakeClient(), [embed(YOUTUBE_URL)], tmp_path, max_height=None, reuse=no_reuse
    )

    assert failed == 0
    options = recorded[0]
    assert "format" not in options
    assert options["noplaylist"] is True
    assert options["playlist_items"] == "1"
    assert options["overwrites"] is True
    assert options["paths"]["temp"] != options["paths"]["home"]


def test_failed_external_download_leaves_no_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FailingYoutubeDL:
        def __init__(self, options: dict[str, Any]) -> None:
            self._options = options

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *exc_info: object) -> None:
            return None

        def extract_info(self, url: str, download: bool = False) -> dict[str, object]:
            paths = self._options["paths"]
            staging = Path(paths.get("temp", paths["home"]))
            (staging / "005_abc.mp4.part").write_bytes(b"partial")
            raise RuntimeError("network died")

    install_fake_youtube_dl(monkeypatch, FailingYoutubeDL)

    failed = download_videos(
        FakeClient(), [embed(YOUTUBE_URL)], tmp_path, max_height=None, reuse=no_reuse
    )

    assert failed == 1
    assert list(tmp_path.iterdir()) == []


def test_superseded_cleanup_stays_within_one_position(tmp_path: Path) -> None:
    other = tmp_path / f"006_{ASSET_ID}_1080.mp4"
    other.write_bytes(b"kept")

    failed = download_videos(
        fake_client(),
        [embed(PLAYER_URL, 5)],
        tmp_path,
        max_height=None,
        reuse=no_reuse,
    )

    assert failed == 0
    assert other.exists()


def test_empty_external_result_is_reported_without_crashing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class EmptyYoutubeDL:
        def __init__(self, options: dict[str, Any]) -> None:
            self._options = options

        def __enter__(self) -> Self:
            return self

        def __exit__(self, *exc_info: object) -> None:
            return None

        def extract_info(self, url: str, download: bool = False) -> dict[str, object]:
            return {"id": "empty", "entries": []}

    install_fake_youtube_dl(monkeypatch, EmptyYoutubeDL)

    failed = download_videos(
        FakeClient(), [embed(YOUTUBE_URL)], tmp_path, max_height=None, reuse=no_reuse
    )

    assert failed == 1
    assert list(tmp_path.iterdir()) == []
