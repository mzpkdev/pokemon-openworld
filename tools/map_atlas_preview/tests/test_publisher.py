"""Focused safety and current-SHA tests for the Map Atlas Pages publisher."""

from __future__ import annotations

import io
import json
import stat
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any, Mapping
from unittest.mock import patch

from tools.map_atlas_preview.publisher import (
    ArtifactSource,
    CurrentMainUnavailable,
    GitHubActionsClient,
    IDENTITY_FILE,
    MARKER,
    MarkerComment,
    PullRequest,
    PreviewError,
    _prepare_output_path,
    _write_manifest,
    _latest_matching_run,
    compose_preview_site,
    main,
    safe_extract_static_site,
    update_preview_comments,
)


MAIN_SHA = "a" * 40
OLD_PR_SHA = "b" * 40
CURRENT_PR_SHA = "c" * 40


def site_archive(
    *,
    source_sha: str = MAIN_SHA,
    event: str = "push",
    unsafe_path: str | None = None,
    symlink: bool = False,
    directories: int = 0,
    extra_static_bytes: int = 0,
) -> bytes:
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as package:
        package.writestr("index.html", "<!doctype html><title>Map atlas</title>")
        package.writestr("assets/app.js", "console.log('static');")
        package.writestr(
            IDENTITY_FILE, json.dumps({"event": event, "sourceSha": source_sha})
        )
        for index in range(directories):
            package.writestr(f"directory-{index}/", "")
        if extra_static_bytes:
            package.writestr("assets/extra-static-data.bin", b"x" * extra_static_bytes)
        if unsafe_path is not None:
            package.writestr(unsafe_path, "unsafe")
        if symlink:
            link = zipfile.ZipInfo("assets/link")
            link.create_system = 3
            link.external_attr = (stat.S_IFLNK | 0o777) << 16
            package.writestr(link, "index.html")
    return archive.getvalue()


def run(
    run_id: int,
    sha: str,
    *,
    branch: str = "main",
    event: str = "push",
    repository: str = "owner/repo",
) -> dict[str, Any]:
    return {
        "conclusion": "success",
        "event": event,
        "head_branch": branch,
        "head_repository": {"full_name": repository},
        "head_sha": sha,
        "id": run_id,
        "updated_at": f"2026-08-21T00:00:0{run_id}Z",
    }


def temporary_build_directory() -> tempfile.TemporaryDirectory[str]:
    build = Path.cwd() / "build"
    build.mkdir(exist_ok=True)
    return tempfile.TemporaryDirectory(dir=build)


class FakeClient:
    """In-memory client that exercises composition without a network request."""

    repository = "owner/repo"

    def __init__(
        self,
        archives: Mapping[int, bytes],
        pull_runs: Mapping[str, list[Mapping[str, Any]]],
    ):
        self.archives = dict(archives)
        self.pull_runs = {branch: list(runs) for branch, runs in pull_runs.items()}
        self.main_runs = [run(1, MAIN_SHA)]
        self.pull_requests = [PullRequest(17, "feature/maps", CURRENT_PR_SHA)]
        self.comments: dict[int, str] = {}
        self.marker_comments: list[MarkerComment] = []
        self.marker_comments_requests = 0
        self.updated_marker_comments: dict[int, str] = {}

    def workflow_runs(
        self, workflow_file: str, event: str, branch: str | None = None
    ) -> list[Mapping[str, Any]]:
        self.last_workflow = workflow_file
        if event in {"push", "schedule"}:
            return self.main_runs
        return self.pull_runs.get(branch or "", [])

    def open_same_repository_pull_requests(self) -> list[PullRequest]:
        return self.pull_requests

    def artifact_for_run(
        self,
        workflow_run: Mapping[str, Any],
        source_sha: str,
        pull_request: PullRequest | None,
    ) -> ArtifactSource | None:
        artifact_id = int(workflow_run["id"])
        if artifact_id not in self.archives:
            return None
        event = str(workflow_run["event"])
        return ArtifactSource(artifact_id, artifact_id, source_sha, event, pull_request)

    def download_artifact(self, artifact: ArtifactSource, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(self.archives[artifact.artifact_id])

    def upsert_comment(self, pull_request_number: int, body: str) -> None:
        self.comments[pull_request_number] = body

    def create_comment(self, pull_request_number: int, body: str) -> None:
        self.comments[pull_request_number] = body

    def update_existing_marker_comment(
        self, pull_request_number: int, body: str
    ) -> bool:
        if pull_request_number not in self.comments:
            return False
        self.comments[pull_request_number] = body
        return True

    def repository_marker_comments(self) -> list[MarkerComment]:
        self.marker_comments_requests += 1
        return self.marker_comments

    def update_comment_by_id(self, comment_id: int, body: str) -> None:
        self.updated_marker_comments[comment_id] = body


class MapAtlasPreviewPublisherTests(unittest.TestCase):
    def test_pages_workflow_publisher_contract(self) -> None:
        workflow = Path(".github/workflows/map-atlas-pages.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("  pull-requests: write\n", workflow)
        self.assertNotIn("  issues: write\n", workflow)
        invocation = workflow.split(
            'result="$(python3 -m tools.map_atlas_preview', maxsplit=1
        )[1].split('--defer-current-main)"', maxsplit=1)[0]
        self.assertLess(invocation.index("--repo"), invocation.index("compose"))
        self.assertLess(invocation.index("--token"), invocation.index("compose"))

    def test_static_extraction_rejects_path_traversal(self) -> None:
        with temporary_build_directory() as temporary:
            root = Path(temporary)
            archive = root / "site.zip"
            archive.write_bytes(site_archive(unsafe_path="../outside.txt"))
            with self.assertRaisesRegex(PreviewError, "unsafe path"):
                safe_extract_static_site(archive, root / "site")

    def test_static_extraction_rejects_symlinks(self) -> None:
        with temporary_build_directory() as temporary:
            root = Path(temporary)
            archive = root / "site.zip"
            archive.write_bytes(site_archive(symlink=True))
            with self.assertRaisesRegex(PreviewError, "non-regular file"):
                safe_extract_static_site(archive, root / "site")

    def test_static_extraction_bounds_member_count_and_path_depth_before_writing(
        self,
    ) -> None:
        with temporary_build_directory() as temporary:
            root = Path(temporary)
            members = root / "members.zip"
            members.write_bytes(site_archive(directories=3))
            with patch("tools.map_atlas_preview.publisher.MAX_SITE_MEMBERS", 3):
                with self.assertRaisesRegex(PreviewError, "too many ZIP members"):
                    safe_extract_static_site(members, root / "members")

            deep = root / "deep.zip"
            deep_path = "/".join(["nested"] * 33) + "/asset.js"
            deep.write_bytes(site_archive(unsafe_path=deep_path))
            with self.assertRaisesRegex(PreviewError, "excessive depth"):
                safe_extract_static_site(deep, root / "deep")

    def test_exact_current_sha_prevents_stale_preview(self) -> None:
        client = FakeClient(
            {1: site_archive(), 2: site_archive()},
            {
                "feature/maps": [
                    run(2, OLD_PR_SHA, branch="feature/maps", event="pull_request")
                ]
            },
        )
        with temporary_build_directory() as temporary:
            root = Path(temporary)
            manifest = compose_preview_site(
                client,
                "map-atlas.yml",
                MAIN_SHA,
                root / "pages",
                root / "manifest.json",
            )
            self.assertEqual(manifest["previews"], [])
            self.assertEqual(manifest["omitted"][0]["sourceSha"], CURRENT_PR_SHA)
            self.assertFalse((root / "pages" / "previews" / "pr-17").exists())
            self.assertTrue((root / "pages" / "index.html").is_file())

    def test_current_pr_preview_requires_matching_source_identity(self) -> None:
        client = FakeClient(
            {
                1: site_archive(),
                2: site_archive(source_sha=CURRENT_PR_SHA, event="pull_request"),
            },
            {
                "feature/maps": [
                    run(
                        2,
                        CURRENT_PR_SHA,
                        branch="feature/maps",
                        event="pull_request",
                    )
                ]
            },
        )
        with temporary_build_directory() as temporary:
            root = Path(temporary)
            manifest = compose_preview_site(
                client,
                "map-atlas.yml",
                MAIN_SHA,
                root / "pages",
                root / "manifest.json",
            )
            self.assertEqual(manifest["previews"][0]["event"], "pull_request")
            self.assertTrue(
                (root / "pages" / "previews" / "pr-17" / "index.html").is_file()
            )

    def test_composition_bounds_cumulative_tree_before_moving_a_preview(self) -> None:
        client = FakeClient(
            {
                1: site_archive(),
                2: site_archive(source_sha=CURRENT_PR_SHA, event="pull_request"),
            },
            {
                "feature/maps": [
                    run(
                        2,
                        CURRENT_PR_SHA,
                        branch="feature/maps",
                        event="pull_request",
                    )
                ]
            },
        )
        with temporary_build_directory() as temporary:
            root = Path(temporary)
            with patch("tools.map_atlas_preview.publisher.MAX_COMPOSED_FILES", 5):
                manifest = compose_preview_site(
                    client,
                    "map-atlas.yml",
                    MAIN_SHA,
                    root / "pages",
                    root / "manifest.json",
                )
            self.assertEqual(manifest["previews"], [])
            self.assertIn("composed static tree", manifest["omitted"][0]["reason"])
            self.assertFalse((root / "pages" / "previews" / "pr-17").exists())

    def test_composition_bounds_cumulative_bytes_before_moving_a_preview(self) -> None:
        client = FakeClient(
            {
                1: site_archive(extra_static_bytes=1_000),
                2: site_archive(
                    source_sha=CURRENT_PR_SHA,
                    event="pull_request",
                    extra_static_bytes=1_000,
                ),
            },
            {
                "feature/maps": [
                    run(
                        2,
                        CURRENT_PR_SHA,
                        branch="feature/maps",
                        event="pull_request",
                    )
                ]
            },
        )
        with temporary_build_directory() as temporary:
            root = Path(temporary)
            with patch("tools.map_atlas_preview.publisher.MAX_COMPOSED_BYTES", 1_500):
                manifest = compose_preview_site(
                    client,
                    "map-atlas.yml",
                    MAIN_SHA,
                    root / "pages",
                    root / "manifest.json",
                )
            self.assertEqual(manifest["previews"], [])
            self.assertIn("composed static tree", manifest["omitted"][0]["reason"])
            self.assertFalse((root / "pages" / "previews" / "pr-17").exists())

    def test_composition_bounds_cumulative_directories_before_moving_a_preview(
        self,
    ) -> None:
        client = FakeClient(
            {
                1: site_archive(),
                2: site_archive(source_sha=CURRENT_PR_SHA, event="pull_request"),
            },
            {
                "feature/maps": [
                    run(
                        2,
                        CURRENT_PR_SHA,
                        branch="feature/maps",
                        event="pull_request",
                    )
                ]
            },
        )
        with temporary_build_directory() as temporary:
            root = Path(temporary)
            with patch("tools.map_atlas_preview.publisher.MAX_COMPOSED_DIRECTORIES", 3):
                manifest = compose_preview_site(
                    client,
                    "map-atlas.yml",
                    MAIN_SHA,
                    root / "pages",
                    root / "manifest.json",
                )
            self.assertEqual(manifest["previews"], [])
            self.assertIn("composed static tree", manifest["omitted"][0]["reason"])
            self.assertFalse((root / "pages" / "previews" / "pr-17").exists())

    def test_composition_bounds_cumulative_members_before_moving_a_preview(
        self,
    ) -> None:
        client = FakeClient(
            {
                1: site_archive(),
                2: site_archive(source_sha=CURRENT_PR_SHA, event="pull_request"),
            },
            {
                "feature/maps": [
                    run(
                        2,
                        CURRENT_PR_SHA,
                        branch="feature/maps",
                        event="pull_request",
                    )
                ]
            },
        )
        with temporary_build_directory() as temporary:
            root = Path(temporary)
            with patch("tools.map_atlas_preview.publisher.MAX_COMPOSED_MEMBERS", 9):
                manifest = compose_preview_site(
                    client,
                    "map-atlas.yml",
                    MAIN_SHA,
                    root / "pages",
                    root / "manifest.json",
                )
            self.assertEqual(manifest["previews"], [])
            self.assertIn("composed static tree", manifest["omitted"][0]["reason"])
            self.assertFalse((root / "pages" / "previews" / "pr-17").exists())

    def test_unsafe_pr_artifact_is_omitted_without_leaking_partial_files(self) -> None:
        client = FakeClient(
            {1: site_archive(), 3: site_archive(unsafe_path="../../outside.txt")},
            {
                "feature/maps": [
                    run(
                        3,
                        CURRENT_PR_SHA,
                        branch="feature/maps",
                        event="pull_request",
                    )
                ]
            },
        )
        with temporary_build_directory() as temporary:
            root = Path(temporary)
            manifest = compose_preview_site(
                client,
                "map-atlas.yml",
                MAIN_SHA,
                root / "pages",
                root / "manifest.json",
            )
            self.assertEqual(manifest["previews"], [])
            self.assertIn(
                "unsafe-or-unavailable-artifact", manifest["omitted"][0]["reason"]
            )
            self.assertFalse((root / "pages" / "previews" / "pr-17").exists())
            self.assertFalse((root / "outside.txt").exists())

    def test_latest_run_requires_repository_head_sha_and_branch(self) -> None:
        matching = run(5, CURRENT_PR_SHA, branch="feature/maps")
        selected = _latest_matching_run(
            [
                run(2, CURRENT_PR_SHA, branch="wrong-branch"),
                run(3, CURRENT_PR_SHA, branch="feature/maps", repository="fork/repo"),
                run(4, OLD_PR_SHA, branch="feature/maps"),
                matching,
            ],
            "owner/repo",
            CURRENT_PR_SHA,
            "feature/maps",
        )
        self.assertEqual(selected, matching)

    def test_current_main_requires_an_exact_artifact_before_cleanup_can_publish(
        self,
    ) -> None:
        client = FakeClient(
            {1: site_archive()},
            {},
        )
        client.main_runs = [run(1, OLD_PR_SHA)]
        with temporary_build_directory() as temporary:
            root = Path(temporary)
            with self.assertRaises(CurrentMainUnavailable):
                compose_preview_site(
                    client,
                    "map-atlas.yml",
                    MAIN_SHA,
                    root / "pages",
                    root / "manifest.json",
                )

    def test_close_cleanup_can_defer_until_an_exact_main_artifact_exists(self) -> None:
        client = FakeClient({1: site_archive()}, {})
        client.main_runs = [run(1, OLD_PR_SHA)]
        with temporary_build_directory() as temporary:
            root = Path(temporary)
            with (
                patch(
                    "tools.map_atlas_preview.publisher.GitHubActionsClient",
                    return_value=client,
                ),
                redirect_stdout(io.StringIO()) as output,
            ):
                exit_code = main(
                    [
                        "--repo",
                        "owner/repo",
                        "--token",
                        "token",
                        "compose",
                        "--workflow",
                        "map-atlas.yml",
                        "--main-sha",
                        MAIN_SHA,
                        "--output",
                        str(root / "pages"),
                        "--manifest",
                        str(root / "manifest.json"),
                        "--defer-current-main",
                    ]
                )
            self.assertEqual(exit_code, 0)
            self.assertEqual(output.getvalue(), "ready=false\n")
            self.assertFalse((root / "pages").exists())

    def test_source_identity_must_match_selected_workflow_revision(self) -> None:
        client = FakeClient(
            {1: site_archive(source_sha=OLD_PR_SHA)},
            {},
        )
        with temporary_build_directory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(PreviewError, "source identity"):
                compose_preview_site(
                    client,
                    "map-atlas.yml",
                    MAIN_SHA,
                    root / "pages",
                    root / "manifest.json",
                )

    def test_comments_reflect_preview_and_unavailable_current_build(self) -> None:
        client = FakeClient({}, {})
        with tempfile.TemporaryDirectory() as temporary:
            manifest_path = Path(temporary) / "manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "format": "pokemon-openworld-map-atlas-pages-v1",
                        "previews": [
                            {
                                "path": "previews/pr-17/",
                                "pullRequest": 17,
                                "sourceSha": CURRENT_PR_SHA,
                            }
                        ],
                        "omitted": [
                            {
                                "pullRequest": 18,
                                "reason": "no-successful-current-build",
                                "sourceSha": OLD_PR_SHA,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            update_preview_comments(
                client, manifest_path, "https://owner.github.io/repo/"
            )
            self.assertEqual(client.marker_comments_requests, 1)
            self.assertIn("/repo/previews/pr-17/", client.comments[17])
            self.assertIn(MARKER, client.comments[17])
            self.assertIn("unavailable", client.comments[18])
            client.marker_comments = [
                MarkerComment(1, 17, f"old preview\n\n{MARKER}"),
                MarkerComment(2, 18, f"old unavailable\n\n{MARKER}"),
                MarkerComment(3, 19, f"old preview\n\n{MARKER}"),
            ]
            update_preview_comments(
                client,
                manifest_path,
                "https://owner.github.io/repo/",
                mark_closed_pull_requests=True,
            )
            self.assertEqual(set(client.updated_marker_comments), {1, 2, 3})
            self.assertIn(
                "Open the Map Atlas preview", client.updated_marker_comments[1]
            )
            self.assertIn("unavailable", client.updated_marker_comments[2])
            self.assertIn("removed", client.updated_marker_comments[3])
            update_preview_comments(
                client,
                manifest_path,
                "https://owner.github.io/repo/",
                closed_pull_request=17,
            )
            self.assertIn("removed", client.comments[17])

    def test_repository_marker_listing_ignores_foreign_and_malformed_issue_urls(
        self,
    ) -> None:
        client = GitHubActionsClient("owner/repo", "token")
        valid_body = f"preview\n\n{MARKER}"
        records = [
            {
                "body": valid_body,
                "id": 1,
                "issue_url": "https://api.github.com/repos/owner/repo/issues/17",
                "user": {"login": "github-actions[bot]"},
            },
            {
                "body": valid_body,
                "id": 2,
                "issue_url": "https://api.github.com/repos/other/repo/issues/18",
                "user": {"login": "github-actions[bot]"},
            },
            {
                "body": valid_body,
                "id": 3,
                "issue_url": "https://example.invalid/repos/owner/repo/issues/19",
                "user": {"login": "github-actions[bot]"},
            },
            {
                "body": valid_body,
                "id": 4,
                "issue_url": "https://api.github.com/repos/owner/repo/issues/20/comments/4",
                "user": {"login": "github-actions[bot]"},
            },
            {
                "body": valid_body,
                "id": 5,
                "issue_url": "https://api.github.com/repos/owner/repo/issues/21",
                "user": {"login": "a-person"},
            },
        ]
        with patch.object(client, "_pages", return_value=iter(records)):
            markers = client.repository_marker_comments()
        self.assertEqual(markers, [MarkerComment(1, 17, valid_body)])

    def test_publisher_paths_are_limited_to_strict_non_symlink_build_descendants(
        self,
    ) -> None:
        with temporary_build_directory() as temporary:
            root = Path(temporary)
            self.assertEqual(_prepare_output_path(root / "pages"), root / "pages")
            for path in (
                Path("."),
                Path(".."),
                Path(".git") / "pages",
                Path("tools") / "pages",
                Path("build"),
                Path("build") / ".." / "outside",
                Path(tempfile.gettempdir()) / "outside-pages",
            ):
                with self.subTest(path=path), self.assertRaises(PreviewError):
                    _prepare_output_path(path)
            for path in (
                Path("build"),
                Path(".git") / "manifest.json",
                Path("build") / ".." / "manifest.json",
                Path(tempfile.gettempdir()) / "outside-manifest.json",
            ):
                with self.subTest(manifest=path), self.assertRaises(PreviewError):
                    _write_manifest(path, {"format": "test"})

            symlink = root / "symlink"
            symlink.symlink_to(Path.cwd())
            with self.assertRaises(PreviewError):
                _prepare_output_path(symlink / "pages")
            with self.assertRaises(PreviewError):
                _write_manifest(symlink / "manifest.json", {"format": "test"})


if __name__ == "__main__":
    unittest.main()
