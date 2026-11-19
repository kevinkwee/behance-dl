"""Tests for the command line interface."""

from __future__ import annotations

from pathlib import Path
from typing import Never

import pytest

from behance_dl import __version__, cli
from behance_dl.errors import GalleryError
from behance_dl.models import GalleryPlan, GalleryProject, ImageAsset, Slide
from behance_dl.video import no_reuse
from conftest import FakeClient

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24
IMAGE_URL = "https://mir-s3-cdn-cf.behance.net/project_modules/source/abc.png"


def make_plan(destination: Path) -> GalleryPlan:
    project = GalleryProject(id=42, name="Planned", slug="Planned", modules=(), payload={"id": 42})
    images = (ImageAsset(file_prefix="001", url=IMAGE_URL, width=100),)
    return GalleryPlan(
        project=project,
        slides=(Slide(position=1, images=images),),
        embeds=(),
        destination=destination,
        expected_images=1,
    )


@pytest.mark.parametrize("value", ["0", "-3"])
def test_positive_int_rejects_non_positive_values(value: str) -> None:
    with pytest.raises(Exception, match="at least 1"):
        cli.positive_int(value)


def test_positive_int_rejects_text() -> None:
    with pytest.raises(Exception, match="not a whole number"):
        cli.positive_int("abc")


@pytest.mark.parametrize("value", ["0", "-1.5"])
def test_positive_float_rejects_non_positive_values(value: str) -> None:
    with pytest.raises(Exception, match="greater than 0"):
        cli.positive_float(value)


def test_positive_float_rejects_text() -> None:
    with pytest.raises(Exception, match="is not a number"):
        cli.positive_float("abc")


def test_parse_args_defaults() -> None:
    args = cli.parse_args(["https://www.behance.net/gallery/1/slug"])

    assert args.galleries == ["https://www.behance.net/gallery/1/slug"]
    assert args.output == Path()
    assert args.max_width is None
    assert (args.workers, args.attempts, args.timeout) == (4, 3, 30.0)
    assert args.force is False
    assert args.dry_run is False


def test_parse_args_collects_options() -> None:
    args = cli.parse_args(
        ["1", "2", "-o", "out", "-W", "1400", "-j", "8", "--attempts", "5", "--force"]
    )

    assert (args.galleries, args.max_width, args.workers) == (["1", "2"], 1400, 8)
    assert (args.attempts, args.force) == (5, True)


def test_version_flag_reports_the_package_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exit_info:
        cli.parse_args(["--version"])

    assert exit_info.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_dry_run_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    plan = make_plan(tmp_path / "42_Planned")
    monkeypatch.setattr(cli, "plan_gallery", lambda *args, **kwargs: plan)

    exit_code = cli.main(["42", "--dry-run", "-o", str(tmp_path)])

    assert exit_code == 0
    assert not plan.destination.exists()
    output = capsys.readouterr().out
    assert "Planned" in output
    assert IMAGE_URL in output


def test_main_downloads_and_reports_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    plan = make_plan(tmp_path / "42_Planned")
    monkeypatch.setattr(cli, "plan_gallery", lambda *args, **kwargs: plan)
    monkeypatch.setattr(cli, "BehanceClient", lambda **kwargs: FakeClient(images={IMAGE_URL: PNG}))

    exit_code = cli.main(["42", "-o", str(tmp_path), "-j", "1"])

    assert exit_code == 0
    assert (plan.destination / "001_abc.png").read_bytes() == PNG
    assert "done:" in capsys.readouterr().out


def test_main_returns_one_when_a_gallery_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fail(*args: object, **kwargs: object) -> GalleryPlan:
        raise GalleryError("gallery 42: gone")

    monkeypatch.setattr(cli, "plan_gallery", fail)

    assert cli.main(["42", "-o", str(tmp_path)]) == 1
    assert "error: gallery 42: gone" in capsys.readouterr().err


def test_main_keeps_going_after_a_failed_gallery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = make_plan(tmp_path / "42_Planned")
    seen: list[str] = []

    def sometimes(client: object, gallery: object, *args: object, **kwargs: object) -> GalleryPlan:
        seen.append(str(gallery))
        if len(seen) == 1:
            raise GalleryError("gallery 1: gone")
        return plan

    monkeypatch.setattr(cli, "plan_gallery", sometimes)
    monkeypatch.setattr(cli, "BehanceClient", lambda **kwargs: FakeClient(images={IMAGE_URL: PNG}))

    assert cli.main(["1", "42", "-o", str(tmp_path), "-j", "1"]) == 1
    assert seen == ["1", "42"]
    assert plan.destination.exists()


def test_force_ignores_the_saved_record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    plan = make_plan(tmp_path / "42_Planned")
    monkeypatch.setattr(cli, "plan_gallery", lambda *args, **kwargs: plan)
    monkeypatch.setattr(cli, "BehanceClient", lambda **kwargs: FakeClient(images={IMAGE_URL: PNG}))

    def unexpected(destination: Path) -> Never:
        raise AssertionError("the record should not be read with --force")

    monkeypatch.setattr(cli, "load_saved", unexpected)

    assert cli.main(["42", "-o", str(tmp_path), "--force", "-j", "1"]) == 0


def test_interrupt_returns_130(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def interrupted(*args: object, **kwargs: object) -> GalleryPlan:
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "plan_gallery", interrupted)

    assert cli.main(["42", "-o", str(tmp_path)]) == 130


def test_videos_flag_downloads_videos(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    plan = make_plan(tmp_path / "42_Planned")
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(cli, "plan_gallery", lambda *args, **kwargs: plan)
    monkeypatch.setattr(cli, "BehanceClient", lambda **kwargs: FakeClient(images={IMAGE_URL: PNG}))

    def record(client: object, embeds: object, destination: object, **kwargs: object) -> int:
        calls.append(kwargs)
        return 0

    monkeypatch.setattr(cli, "download_videos", record)

    assert cli.main(["42", "-o", str(tmp_path), "--videos", "-j", "1"]) == 0
    assert calls[0]["max_height"] is None
    assert calls[0]["reuse"] is not no_reuse


def test_videos_are_not_downloaded_without_the_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = make_plan(tmp_path / "42_Planned")
    monkeypatch.setattr(cli, "plan_gallery", lambda *args, **kwargs: plan)
    monkeypatch.setattr(cli, "BehanceClient", lambda **kwargs: FakeClient(images={IMAGE_URL: PNG}))

    def unexpected(*args: object, **kwargs: object) -> int:
        raise AssertionError("videos must be opt-in")

    monkeypatch.setattr(cli, "download_videos", unexpected)

    assert cli.main(["42", "-o", str(tmp_path), "-j", "1"]) == 0


def test_video_failure_marks_the_gallery_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = make_plan(tmp_path / "42_Planned")
    monkeypatch.setattr(cli, "plan_gallery", lambda *args, **kwargs: plan)
    monkeypatch.setattr(cli, "BehanceClient", lambda **kwargs: FakeClient(images={IMAGE_URL: PNG}))
    monkeypatch.setattr(cli, "download_videos", lambda *args, **kwargs: 1)

    assert cli.main(["42", "-o", str(tmp_path), "--videos", "-j", "1"]) == 1


def test_force_passes_no_reuse_to_videos(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    plan = make_plan(tmp_path / "42_Planned")
    recorded: list[dict[str, object]] = []
    monkeypatch.setattr(cli, "plan_gallery", lambda *args, **kwargs: plan)
    monkeypatch.setattr(cli, "BehanceClient", lambda **kwargs: FakeClient(images={IMAGE_URL: PNG}))

    def record(client: object, embeds: object, destination: object, **kwargs: object) -> int:
        recorded.append(kwargs)
        return 0

    monkeypatch.setattr(cli, "download_videos", record)

    assert cli.main(["42", "-o", str(tmp_path), "--videos", "--force", "-j", "1"]) == 0
    assert recorded[0]["reuse"] is no_reuse


def test_video_height_reaches_the_video_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = make_plan(tmp_path / "42_Planned")
    recorded: list[dict[str, object]] = []
    monkeypatch.setattr(cli, "plan_gallery", lambda *args, **kwargs: plan)
    monkeypatch.setattr(cli, "BehanceClient", lambda **kwargs: FakeClient(images={IMAGE_URL: PNG}))

    def record(client: object, embeds: object, destination: object, **kwargs: object) -> int:
        recorded.append(kwargs)
        return 0

    monkeypatch.setattr(cli, "download_videos", record)

    assert (
        cli.main(["42", "-o", str(tmp_path), "--videos", "--video-height", "720", "-j", "1"]) == 0
    )
    assert recorded[0]["max_height"] == 720


def test_video_height_reaches_the_reuse_lookup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = make_plan(tmp_path / "42_Planned")
    caps: list[int | None] = []
    monkeypatch.setattr(cli, "plan_gallery", lambda *args, **kwargs: plan)
    monkeypatch.setattr(cli, "BehanceClient", lambda **kwargs: FakeClient(images={IMAGE_URL: PNG}))
    monkeypatch.setattr(cli, "download_videos", lambda *args, **kwargs: 0)

    def capture(max_height: int | None) -> object:
        caps.append(max_height)
        return no_reuse

    monkeypatch.setattr(cli, "reuse_downloaded", capture)

    assert (
        cli.main(["42", "-o", str(tmp_path), "--videos", "--video-height", "720", "-j", "1"]) == 0
    )
    assert caps == [720]
