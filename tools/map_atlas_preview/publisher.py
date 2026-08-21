"""Compose safe Map Atlas preview sites from GitHub Actions artifacts.

This module intentionally uses only the Python standard library.  It runs in a
trusted default-branch workflow, never checks out a pull request ref, and treats
every downloaded artifact as untrusted static input.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import stat
import sys
import tempfile
import urllib.parse
import urllib.request
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence


MARKER = "<!-- map-atlas-preview -->"
IDENTITY_FILE = "map-atlas-preview-source.json"
MAX_ARCHIVE_BYTES = 128 * 1024 * 1024
MAX_SITE_MEMBERS = 20_000
MAX_SITE_DIRECTORIES = 10_000
MAX_SITE_FILES = 10_000
MAX_SITE_BYTES = 256 * 1024 * 1024
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_COMPRESSION_RATIO = 100
MAX_PATH_LENGTH = 512
MAX_PATH_DEPTH = 32
MAX_COMPOSED_FILES = 250_000
# Keep enough headroom below GitHub Pages' 1 GB site limit for its packaging.
MAX_COMPOSED_BYTES = 900 * 1024 * 1024
MAX_COMPOSED_DIRECTORIES = 250_000
MAX_COMPOSED_MEMBERS = 500_000
API_VERSION = "2022-11-28"


class PreviewError(RuntimeError):
    """The preview publisher cannot safely compose a Pages tree."""


class CurrentMainUnavailable(PreviewError):
    """The current main commit has no successful downloadable atlas artifact yet."""


class _ArtifactRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Do not forward the GitHub token to an artifact storage redirect."""

    def redirect_request(
        self,
        request: urllib.request.Request,
        file_pointer: Any,
        code: int,
        message: str,
        headers: Any,
        new_url: str,
    ) -> urllib.request.Request | None:
        redirected = super().redirect_request(
            request, file_pointer, code, message, headers, new_url
        )
        if redirected is None:
            return None
        old_origin = urllib.parse.urlsplit(request.full_url).netloc
        new_origin = urllib.parse.urlsplit(new_url).netloc
        if old_origin != new_origin:
            redirected.remove_header("Authorization")
        return redirected


@dataclass(frozen=True)
class PullRequest:
    """An open same-repository pull request with a current source revision."""

    number: int
    head_ref: str
    head_sha: str


@dataclass(frozen=True)
class ArtifactSource:
    """A successful workflow artifact bound to one source revision."""

    run_id: int
    artifact_id: int
    source_sha: str
    event: str
    pull_request: PullRequest | None


@dataclass(frozen=True)
class TreeStats:
    """The bounded contents of one extracted static site."""

    files: int
    directories: int
    bytes: int

    @property
    def members(self) -> int:
        return self.files + self.directories


@dataclass(frozen=True)
class MarkerComment:
    """One bot-owned Map Atlas marker comment attached to a pull request."""

    comment_id: int
    pull_request: int
    body: str


def _expect_mapping(value: object, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise PreviewError(f"GitHub API returned an invalid {context}")
    return value


def _expect_list(value: object, context: str) -> list[Any]:
    if not isinstance(value, list):
        raise PreviewError(f"GitHub API returned an invalid {context}")
    return value


def _nonempty_string(value: object, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise PreviewError(f"GitHub API returned an invalid {context}")
    return value


class GitHubActionsClient:
    """Small fail-closed GitHub REST client for trusted preview publication."""

    def __init__(
        self, repository: str, token: str, api_base: str = "https://api.github.com"
    ):
        if not repository or "/" not in repository:
            raise PreviewError("repository must be an owner/name value")
        if not token:
            raise PreviewError("a GitHub token is required")
        self.repository = repository
        self.token = token
        self.api_base = api_base.rstrip("/")
        self._opener = urllib.request.build_opener(_ArtifactRedirectHandler())

    def _request(self, method: str, path: str, body: object | None = None) -> Any:
        url = f"{self.api_base}{path}"
        data = None
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self.token}",
            "User-Agent": "pokemon-openworld-map-atlas-preview-publisher",
            "X-GitHub-Api-Version": API_VERSION,
        }
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with self._opener.open(request, timeout=30) as response:
                payload = response.read()
        except OSError as error:
            raise PreviewError(
                f"GitHub API request failed for {path}: {error}"
            ) from error
        try:
            return json.loads(payload.decode("utf-8")) if payload else {}
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise PreviewError(
                f"GitHub API returned invalid JSON for {path}"
            ) from error

    def _pages(self, path: str, key: str | None) -> Iterable[Mapping[str, Any]]:
        separator = "&" if "?" in path else "?"
        for page in range(1, 1_001):
            payload = self._request("GET", f"{path}{separator}per_page=100&page={page}")
            records = (
                _expect_list(payload, path)
                if key is None
                else _expect_list(_expect_mapping(payload, path).get(key), key)
            )
            for record in records:
                yield _expect_mapping(record, key)
            if len(records) < 100:
                return
        raise PreviewError(f"GitHub API pagination limit reached for {path}")

    def workflow_runs(
        self, workflow_file: str, event: str, branch: str | None = None
    ) -> list[Mapping[str, Any]]:
        query: dict[str, str] = {"event": event, "status": "success"}
        if branch:
            query["branch"] = branch
        encoded = urllib.parse.urlencode(query)
        workflow = urllib.parse.quote(workflow_file, safe="")
        return list(
            self._pages(
                f"/repos/{self.repository}/actions/workflows/{workflow}/runs?{encoded}",
                "workflow_runs",
            )
        )

    def _same_repository_pull_request_records(
        self, state: str
    ) -> Iterable[Mapping[str, Any]]:
        if state not in {"open", "closed"}:
            raise PreviewError("unsupported pull request state")
        records = self._pages(f"/repos/{self.repository}/pulls?state={state}", None)
        for record in records:
            head = _expect_mapping(record.get("head"), "pull request head")
            source_repo = _expect_mapping(
                head.get("repo"), "pull request head repository"
            )
            if source_repo.get("full_name") == self.repository:
                yield record

    def open_same_repository_pull_requests(self) -> list[PullRequest]:
        pull_requests: list[PullRequest] = []
        for record in self._same_repository_pull_request_records("open"):
            number = record.get("number")
            head = _expect_mapping(record.get("head"), "pull request head")
            if not isinstance(number, int) or number <= 0:
                raise PreviewError("GitHub API returned an invalid pull request number")
            pull_requests.append(
                PullRequest(
                    number=number,
                    head_ref=_nonempty_string(head.get("ref"), "pull request head ref"),
                    head_sha=_nonempty_string(head.get("sha"), "pull request head SHA"),
                )
            )
        return sorted(pull_requests, key=lambda pull_request: pull_request.number)

    def artifact_for_run(
        self, run: Mapping[str, Any], source_sha: str, pull_request: PullRequest | None
    ) -> ArtifactSource | None:
        run_id = run.get("id")
        if not isinstance(run_id, int) or run_id <= 0:
            raise PreviewError("GitHub API returned an invalid workflow run ID")
        artifacts = self._pages(
            f"/repos/{self.repository}/actions/runs/{run_id}/artifacts", "artifacts"
        )
        candidates = [
            artifact
            for artifact in artifacts
            if artifact.get("name") == "map-atlas-site"
            and artifact.get("expired") is False
        ]
        if not candidates:
            return None
        candidates.sort(
            key=lambda artifact: str(artifact.get("created_at", "")), reverse=True
        )
        artifact_id = candidates[0].get("id")
        if not isinstance(artifact_id, int) or artifact_id <= 0:
            raise PreviewError("GitHub API returned an invalid artifact ID")
        size = candidates[0].get("size_in_bytes")
        if not isinstance(size, int) or size < 0 or size > MAX_ARCHIVE_BYTES:
            raise PreviewError("Map Atlas artifact has an invalid or unreasonable size")
        event = run.get("event")
        if event not in {"pull_request", "pull_request_target", "push", "schedule"}:
            raise PreviewError(
                "GitHub API returned an invalid Map Atlas workflow event"
            )
        if pull_request is None and event not in {
            "pull_request_target",
            "push",
            "schedule",
        }:
            raise PreviewError(
                "main Map Atlas artifact did not come from a production run"
            )
        if pull_request is not None and event != "pull_request":
            raise PreviewError(
                "pull request Map Atlas artifact did not come from a pull request run"
            )
        return ArtifactSource(run_id, artifact_id, source_sha, event, pull_request)

    def download_artifact(self, artifact: ArtifactSource, destination: Path) -> None:
        path = f"/repos/{self.repository}/actions/artifacts/{artifact.artifact_id}/zip"
        request = urllib.request.Request(
            f"{self.api_base}{path}",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "User-Agent": "pokemon-openworld-map-atlas-preview-publisher",
                "X-GitHub-Api-Version": API_VERSION,
            },
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        total = 0
        try:
            with (
                self._opener.open(request, timeout=60) as response,
                destination.open("xb") as output,
            ):
                while chunk := response.read(1024 * 1024):
                    total += len(chunk)
                    if total > MAX_ARCHIVE_BYTES:
                        raise PreviewError(
                            "Map Atlas artifact archive exceeds the safe size limit"
                        )
                    output.write(chunk)
        except OSError as error:
            raise PreviewError(
                f"Map Atlas artifact download failed: {error}"
            ) from error
        if total == 0:
            raise PreviewError("Map Atlas artifact download was empty")

    def _marker_comments(self, pull_request_number: int) -> list[Mapping[str, Any]]:
        if pull_request_number <= 0:
            raise PreviewError("pull request number must be positive")
        comments = self._pages(
            f"/repos/{self.repository}/issues/{pull_request_number}/comments", None
        )
        existing = [
            comment
            for comment in comments
            if MARKER in str(comment.get("body", ""))
            and _expect_mapping(comment.get("user"), "comment user").get("login")
            == "github-actions[bot]"
        ]
        existing.sort(
            key=lambda comment: str(comment.get("updated_at", "")), reverse=True
        )
        return existing

    def repository_marker_comments(self) -> list[MarkerComment]:
        """List valid marker comments once, without querying every closed pull request."""

        api_origin = urllib.parse.urlsplit(self.api_base)
        expected_path = f"{api_origin.path.rstrip('/')}/repos/{self.repository}/issues/"
        markers: list[MarkerComment] = []
        for comment in self._pages(f"/repos/{self.repository}/issues/comments", None):
            body = comment.get("body")
            user = comment.get("user")
            comment_id = comment.get("id")
            issue_url = comment.get("issue_url")
            if (
                not isinstance(body, str)
                or MARKER not in body
                or not isinstance(user, Mapping)
                or user.get("login") != "github-actions[bot]"
                or not isinstance(comment_id, int)
                or comment_id <= 0
                or not isinstance(issue_url, str)
            ):
                continue
            parsed = urllib.parse.urlsplit(issue_url)
            if (
                parsed.scheme != api_origin.scheme
                or parsed.netloc != api_origin.netloc
                or parsed.query
                or parsed.fragment
                or not parsed.path.startswith(expected_path)
            ):
                continue
            number_text = parsed.path.removeprefix(expected_path)
            if not number_text.isascii() or not number_text.isdecimal():
                continue
            pull_request = int(number_text)
            if pull_request <= 0:
                continue
            markers.append(MarkerComment(comment_id, pull_request, body))
        return markers

    def update_comment_by_id(self, comment_id: int, body: str) -> None:
        if comment_id <= 0:
            raise PreviewError("comment ID must be positive")
        self._request(
            "PATCH",
            f"/repos/{self.repository}/issues/comments/{comment_id}",
            {"body": body},
        )

    def update_existing_marker_comment(
        self, pull_request_number: int, body: str
    ) -> bool:
        existing = self._marker_comments(pull_request_number)
        if existing:
            comment_id = existing[0].get("id")
            if not isinstance(comment_id, int) or comment_id <= 0:
                raise PreviewError("GitHub API returned an invalid comment ID")
            if existing[0].get("body") != body:
                self.update_comment_by_id(comment_id, body)
            return True
        return False

    def upsert_comment(self, pull_request_number: int, body: str) -> None:
        if self.update_existing_marker_comment(pull_request_number, body):
            return
        self.create_comment(pull_request_number, body)

    def create_comment(self, pull_request_number: int, body: str) -> None:
        if pull_request_number <= 0:
            raise PreviewError("pull request number must be positive")
        self._request(
            "POST",
            f"/repos/{self.repository}/issues/{pull_request_number}/comments",
            {"body": body},
        )


def _static_member_path(name: str) -> PurePosixPath:
    if not name or "\\" in name or "\x00" in name:
        raise PreviewError("artifact contains an invalid path")
    if len(name.encode("utf-8")) > MAX_PATH_LENGTH:
        raise PreviewError("artifact contains an overlong path")
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise PreviewError(f"artifact contains an unsafe path: {name!r}")
    if len(path.parts) > MAX_PATH_DEPTH:
        raise PreviewError("artifact contains a path with excessive depth")
    if any(":" in part for part in path.parts[:1]):
        raise PreviewError(f"artifact contains an unsafe path: {name!r}")
    return path


def _validate_zip_member(
    info: zipfile.ZipInfo, paths: set[PurePosixPath]
) -> PurePosixPath:
    path = _static_member_path(info.filename.rstrip("/"))
    if path in paths:
        raise PreviewError(f"artifact contains a duplicate path: {path.as_posix()}")
    paths.add(path)
    mode = info.external_attr >> 16
    file_type = stat.S_IFMT(mode)
    if stat.S_ISLNK(mode) or file_type not in {0, stat.S_IFREG, stat.S_IFDIR}:
        raise PreviewError(f"artifact contains a non-regular file: {path.as_posix()}")
    if info.is_dir() and file_type == stat.S_IFREG:
        raise PreviewError(
            f"artifact has an invalid directory entry: {path.as_posix()}"
        )
    if not info.is_dir():
        if info.file_size > MAX_FILE_BYTES:
            raise PreviewError(f"artifact file is too large: {path.as_posix()}")
        if info.file_size > max(1, info.compress_size) * MAX_COMPRESSION_RATIO:
            raise PreviewError(
                f"artifact file has an unsafe compression ratio: {path.as_posix()}"
            )
    return path


def safe_extract_static_site(archive: Path, destination: Path) -> TreeStats:
    """Extract a bounded regular-file-only ZIP without invoking its contents."""

    if destination.exists() or destination.is_symlink():
        raise PreviewError(f"extraction destination is not empty: {destination}")
    destination.mkdir(parents=True)
    files = 0
    member_count = 0
    directories = 0
    total_bytes = 0
    try:
        with zipfile.ZipFile(archive) as package:
            paths: set[PurePosixPath] = set()
            file_paths: set[PurePosixPath] = set()
            members: list[tuple[zipfile.ZipInfo, PurePosixPath]] = []
            for info in package.infolist():
                member_count += 1
                if member_count > MAX_SITE_MEMBERS:
                    raise PreviewError("artifact has too many ZIP members")
                path = _validate_zip_member(info, paths)
                if any(parent in file_paths for parent in path.parents):
                    raise PreviewError(
                        f"artifact has a file/directory path conflict: {path.as_posix()}"
                    )
                if not info.is_dir():
                    if any(path in existing.parents for existing in paths - {path}):
                        raise PreviewError(
                            f"artifact has a file/directory path conflict: {path.as_posix()}"
                        )
                    file_paths.add(path)
                    files += 1
                    total_bytes += info.file_size
                    if files > MAX_SITE_FILES or total_bytes > MAX_SITE_BYTES:
                        raise PreviewError("artifact static tree exceeds safe limits")
                else:
                    directories += 1
                    if directories > MAX_SITE_DIRECTORIES:
                        raise PreviewError("artifact has too many directories")
                members.append((info, path))
            for info, path in members:
                target = destination.joinpath(*path.parts)
                if info.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                written = 0
                with package.open(info, "r") as source, target.open("xb") as output:
                    while chunk := source.read(1024 * 1024):
                        written += len(chunk)
                        if written > info.file_size:
                            raise PreviewError(
                                "artifact file expanded beyond its declared size"
                            )
                        output.write(chunk)
                if written != info.file_size:
                    raise PreviewError("artifact file did not match its declared size")
    except zipfile.BadZipFile as error:
        raise PreviewError("Map Atlas artifact is not a valid ZIP archive") from error
    except (OSError, RuntimeError, NotImplementedError) as error:
        raise PreviewError(
            f"could not extract Map Atlas artifact safely: {error}"
        ) from error
    return validate_static_tree(
        destination,
        MAX_SITE_FILES,
        MAX_SITE_BYTES,
        MAX_SITE_DIRECTORIES,
        MAX_SITE_MEMBERS,
    )


def validate_static_tree(
    root: Path,
    max_files: int,
    max_bytes: int,
    max_directories: int,
    max_members: int,
) -> TreeStats:
    """Require a bounded directory containing only static regular files."""

    if root.is_symlink() or not root.is_dir():
        raise PreviewError("static site root must be a directory")
    index = root / "index.html"
    if index.is_symlink() or not index.is_file():
        raise PreviewError("static site is missing index.html")
    files = 0
    directories = 0
    total_bytes = 0
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        _static_member_path(relative.as_posix())
        details = path.lstat()
        if stat.S_ISLNK(details.st_mode):
            raise PreviewError(f"static site contains a symlink: {relative.as_posix()}")
        if stat.S_ISDIR(details.st_mode):
            directories += 1
            if directories > max_directories or files + directories > max_members:
                raise PreviewError("static site exceeds safe limits")
            continue
        if not stat.S_ISREG(details.st_mode):
            raise PreviewError(
                f"static site contains a non-regular file: {relative.as_posix()}"
            )
        files += 1
        total_bytes += details.st_size
        if (
            details.st_size > MAX_FILE_BYTES
            or files > max_files
            or total_bytes > max_bytes
            or files + directories > max_members
        ):
            raise PreviewError("static site exceeds safe limits")
    return TreeStats(files, directories, total_bytes)


def validate_static_site_identity(root: Path, source: ArtifactSource) -> None:
    """Bind an extracted site to the revision and event selected from GitHub's API."""

    identity_path = root / IDENTITY_FILE
    try:
        identity = json.loads(identity_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PreviewError(
            "static site is missing valid source identity metadata"
        ) from error
    identity = _expect_mapping(identity, "static site source identity")
    if (
        identity.get("sourceSha") != source.source_sha
        or identity.get("event") != source.event
    ):
        raise PreviewError(
            "static site source identity does not match its workflow run"
        )


def _require_composed_tree_limits(stats: TreeStats) -> None:
    if (
        stats.files > MAX_COMPOSED_FILES
        or stats.directories > MAX_COMPOSED_DIRECTORIES
        or stats.members > MAX_COMPOSED_MEMBERS
        or stats.bytes > MAX_COMPOSED_BYTES
    ):
        raise PreviewError("composed static tree exceeds safe limits")


def _run_matches(
    run: Mapping[str, Any], repository: str, source_sha: str, head_ref: str | None
) -> bool:
    if run.get("conclusion") != "success" or run.get("head_sha") != source_sha:
        return False
    head_repository = run.get("head_repository")
    if (
        not isinstance(head_repository, Mapping)
        or head_repository.get("full_name") != repository
    ):
        return False
    return head_ref is None or run.get("head_branch") == head_ref


def _latest_matching_run(
    runs: Sequence[Mapping[str, Any]],
    repository: str,
    source_sha: str,
    head_ref: str | None,
) -> Mapping[str, Any] | None:
    matches = [
        run for run in runs if _run_matches(run, repository, source_sha, head_ref)
    ]
    if not matches:
        return None
    return max(
        matches, key=lambda run: (str(run.get("updated_at", "")), int(run.get("id", 0)))
    )


def _build_descendant(path: Path, label: str) -> Path:
    """Accept only a non-symlink strict descendant of this checkout's build tree."""

    repository = Path.cwd().resolve()
    build = repository / "build"
    candidate = path if path.is_absolute() else repository / path
    if ".." in candidate.parts:
        raise PreviewError(f"{label} must not contain parent-directory traversal")
    try:
        candidate.relative_to(build)
    except ValueError as error:
        raise PreviewError(f"{label} must be a strict descendant of build/") from error
    if candidate == build:
        raise PreviewError(f"{label} must not be build/ itself")
    current = candidate
    while True:
        if current.is_symlink():
            raise PreviewError(f"{label} must not contain a symlink")
        if current == build:
            break
        current = current.parent
    resolved = candidate.resolve()
    try:
        relative = resolved.relative_to(build.resolve())
    except ValueError as error:
        raise PreviewError(f"{label} must be a strict descendant of build/") from error
    if relative == Path("."):
        raise PreviewError(f"{label} must not be build/ itself")
    return resolved


def _prepare_output_path(output: Path) -> Path:
    resolved = _build_descendant(output, "output")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    return resolved


def _publish_tree(staging: Path, output: Path) -> None:
    backup = output.parent / f".{output.name}.previous-{uuid.uuid4().hex}"
    if output.exists():
        if not output.is_dir() or output.is_symlink():
            raise PreviewError("output must be a regular directory")
        output.rename(backup)
    try:
        staging.rename(output)
    except OSError:
        if backup.exists():
            backup.rename(output)
        raise
    if backup.exists():
        shutil.rmtree(backup)


def _write_manifest(path: Path, manifest: Mapping[str, Any]) -> None:
    path = _build_descendant(path, "manifest")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as output:
            json.dump(manifest, output, indent=2, sort_keys=True)
            output.write("\n")
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _manifest_record(source: ArtifactSource, path: str) -> dict[str, Any]:
    if source.pull_request is None:
        return {
            "artifactId": source.artifact_id,
            "event": source.event,
            "runId": source.run_id,
            "sourceSha": source.source_sha,
        }
    return {
        "artifactId": source.artifact_id,
        "event": source.event,
        "path": path,
        "pullRequest": source.pull_request.number,
        "runId": source.run_id,
        "sourceSha": source.source_sha,
    }


def compose_preview_site(
    client: GitHubActionsClient,
    workflow_file: str,
    main_sha: str,
    output: Path,
    manifest_path: Path,
) -> Mapping[str, Any]:
    """Compose current main plus every eligible current same-repository PR."""

    if not re.fullmatch(r"[0-9a-f]{40}", main_sha):
        raise PreviewError("main SHA must be a full Git revision")
    main_runs = [
        *client.workflow_runs(workflow_file, "push", branch="main"),
        *client.workflow_runs(workflow_file, "pull_request_target", branch="main"),
        *client.workflow_runs(workflow_file, "schedule", branch="main"),
    ]
    main_run = _latest_matching_run(main_runs, client.repository, main_sha, None)
    if main_run is None:
        raise CurrentMainUnavailable(
            "no successful current-main Map Atlas workflow run exists"
        )
    main_source = client.artifact_for_run(main_run, main_sha, None)
    if main_source is None:
        raise CurrentMainUnavailable(
            "current-main Map Atlas site artifact is missing or expired"
        )

    sources: list[ArtifactSource] = [main_source]
    omitted: list[dict[str, Any]] = []
    for pull_request in client.open_same_repository_pull_requests():
        runs = client.workflow_runs(
            workflow_file, "pull_request", branch=pull_request.head_ref
        )
        run = _latest_matching_run(
            runs, client.repository, pull_request.head_sha, pull_request.head_ref
        )
        if run is None:
            omitted.append(
                {
                    "pullRequest": pull_request.number,
                    "reason": "no-successful-current-build",
                    "sourceSha": pull_request.head_sha,
                }
            )
            continue
        try:
            artifact = client.artifact_for_run(run, pull_request.head_sha, pull_request)
        except PreviewError as error:
            omitted.append(
                {
                    "pullRequest": pull_request.number,
                    "reason": f"artifact-unavailable: {error}",
                    "sourceSha": pull_request.head_sha,
                }
            )
            continue
        if artifact is None:
            omitted.append(
                {
                    "pullRequest": pull_request.number,
                    "reason": "artifact-missing-or-expired",
                    "sourceSha": pull_request.head_sha,
                }
            )
            continue
        sources.append(artifact)

    output = _prepare_output_path(output)
    manifest_path = _build_descendant(manifest_path, "manifest")
    manifest: dict[str, Any] = {
        "format": "pokemon-openworld-map-atlas-pages-v1",
        "main": _manifest_record(main_source, "/"),
        "omitted": omitted,
        "previews": [],
    }
    with tempfile.TemporaryDirectory(
        prefix="map-atlas-pages-", dir=output.parent
    ) as temporary:
        workspace = Path(temporary)
        staging = workspace / "site"
        downloads = workspace / "downloads"
        composed_stats: TreeStats | None = None
        for source in sources:
            archive = downloads / f"artifact-{source.artifact_id}.zip"
            try:
                client.download_artifact(source, archive)
                if source.pull_request is None:
                    safe_extract_static_site(archive, staging)
                    validate_static_site_identity(staging, source)
                    composed_stats = validate_static_tree(
                        staging,
                        MAX_COMPOSED_FILES,
                        MAX_COMPOSED_BYTES,
                        MAX_COMPOSED_DIRECTORIES,
                        MAX_COMPOSED_MEMBERS,
                    )
                else:
                    extracted = (
                        workspace / "extracted" / f"pr-{source.pull_request.number}"
                    )
                    preview_stats = safe_extract_static_site(archive, extracted)
                    validate_static_site_identity(extracted, source)
                    target = staging / "previews" / f"pr-{source.pull_request.number}"
                    if composed_stats is None:
                        raise PreviewError("main static site was not composed first")
                    parent_directories = 0 if target.parent.exists() else 1
                    candidate_stats = TreeStats(
                        composed_stats.files + preview_stats.files,
                        composed_stats.directories
                        + preview_stats.directories
                        + parent_directories
                        + 1,
                        composed_stats.bytes + preview_stats.bytes,
                    )
                    _require_composed_tree_limits(candidate_stats)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(extracted), target)
                    composed_stats = candidate_stats
            except PreviewError as error:
                if source.pull_request is None:
                    raise
                omitted.append(
                    {
                        "pullRequest": source.pull_request.number,
                        "reason": f"unsafe-or-unavailable-artifact: {error}",
                        "sourceSha": source.source_sha,
                    }
                )
                continue
            if source.pull_request is not None:
                manifest["previews"].append(
                    _manifest_record(
                        source, f"previews/pr-{source.pull_request.number}/"
                    )
                )
        validate_static_tree(
            staging,
            MAX_COMPOSED_FILES,
            MAX_COMPOSED_BYTES,
            MAX_COMPOSED_DIRECTORIES,
            MAX_COMPOSED_MEMBERS,
        )
        _publish_tree(staging, output)
    manifest["previews"].sort(key=lambda preview: preview["pullRequest"])
    manifest["omitted"].sort(key=lambda preview: preview["pullRequest"])
    _write_manifest(manifest_path, manifest)
    return manifest


def _load_manifest(path: Path) -> Mapping[str, Any]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PreviewError(f"could not read preview manifest: {error}") from error
    manifest = _expect_mapping(loaded, "preview manifest")
    if manifest.get("format") != "pokemon-openworld-map-atlas-pages-v1":
        raise PreviewError("preview manifest has an unsupported format")
    _expect_list(manifest.get("previews"), "preview manifest previews")
    _expect_list(manifest.get("omitted"), "preview manifest omitted previews")
    return manifest


def _comment_for_preview(page_url: str, preview: Mapping[str, Any]) -> tuple[int, str]:
    number = preview.get("pullRequest")
    source_sha = preview.get("sourceSha")
    if (
        not isinstance(number, int)
        or number <= 0
        or not isinstance(source_sha, str)
        or len(source_sha) < 7
    ):
        raise PreviewError("preview manifest has an invalid preview record")
    url = f"{page_url.rstrip('/')}/previews/pr-{number}/"
    return (
        number,
        f"[Open the Map Atlas preview]({url}) for `{source_sha[:12]}`.\n\n{MARKER}",
    )


def _comment_for_omission(omitted: Mapping[str, Any]) -> tuple[int, str]:
    number = omitted.get("pullRequest")
    source_sha = omitted.get("sourceSha")
    if (
        not isinstance(number, int)
        or number <= 0
        or not isinstance(source_sha, str)
        or len(source_sha) < 7
    ):
        raise PreviewError("preview manifest has an invalid omitted record")
    return (
        number,
        "The Map Atlas preview is unavailable for "
        f"`{source_sha[:12]}` because the current build did not produce an eligible site artifact.\n\n"
        f"{MARKER}",
    )


def update_preview_comments(
    client: GitHubActionsClient,
    manifest_path: Path,
    page_url: str,
    closed_pull_request: int | None = None,
    mark_closed_pull_requests: bool = False,
) -> None:
    """Upsert one bot-owned marker comment for each manifest decision."""

    manifest = _load_manifest(manifest_path)
    closed_comment = f"The Map Atlas preview was removed because this pull request was closed.\n\n{MARKER}"
    if closed_pull_request is not None:
        client.update_existing_marker_comment(closed_pull_request, closed_comment)
        return
    if not page_url.startswith("https://"):
        raise PreviewError("Pages deployment URL must be an HTTPS URL")
    decisions: dict[int, str] = {}
    for preview in _expect_list(manifest["previews"], "preview manifest previews"):
        number, body = _comment_for_preview(
            page_url, _expect_mapping(preview, "preview record")
        )
        decisions[number] = body
    for omitted in _expect_list(
        manifest["omitted"], "preview manifest omitted previews"
    ):
        number, body = _comment_for_omission(
            _expect_mapping(omitted, "omitted preview record")
        )
        decisions[number] = body
    # One repository-wide scan covers both current preview decisions and cleanup.
    # Do not list comments per closed (or open) pull request: that grows linearly
    # with repository history and can exhaust the workflow token's REST budget.
    markers_by_pull_request: dict[int, MarkerComment] = {}
    markers = client.repository_marker_comments()
    for marker in markers:
        markers_by_pull_request.setdefault(marker.pull_request, marker)
    for number in sorted(decisions):
        marker = markers_by_pull_request.get(number)
        if marker is None:
            client.create_comment(number, decisions[number])
        elif marker.body != decisions[number]:
            client.update_comment_by_id(marker.comment_id, decisions[number])
    if mark_closed_pull_requests:
        for marker in markers:
            if marker.pull_request not in decisions and marker.body != closed_comment:
                client.update_comment_by_id(marker.comment_id, closed_comment)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, help="GitHub owner/name repository")
    parser.add_argument(
        "--token", required=True, help="GitHub token with the required permissions"
    )
    parser.add_argument("--api-base", default="https://api.github.com")
    commands = parser.add_subparsers(dest="command", required=True)

    compose = commands.add_parser("compose", help="compose the Pages static tree")
    compose.add_argument(
        "--workflow", required=True, help="dedicated Map Atlas workflow filename"
    )
    compose.add_argument("--main-sha", required=True)
    compose.add_argument("--output", required=True, type=Path)
    compose.add_argument("--manifest", required=True, type=Path)
    compose.add_argument(
        "--defer-current-main",
        action="store_true",
        help="succeed without a deployment when exact current-main output is pending",
    )

    comment = commands.add_parser("comment", help="upsert preview status comments")
    comment.add_argument("--manifest", required=True, type=Path)
    comment.add_argument("--page-url", required=True)
    comment.add_argument("--closed-pull-request", type=int)
    comment.add_argument("--mark-closed-pull-requests", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    client = GitHubActionsClient(args.repo, args.token, args.api_base)
    try:
        if args.command == "compose":
            try:
                compose_preview_site(
                    client, args.workflow, args.main_sha, args.output, args.manifest
                )
            except CurrentMainUnavailable:
                if not args.defer_current_main:
                    raise
                print("ready=false")
                return 0
            print("ready=true")
        else:
            update_preview_comments(
                client,
                args.manifest,
                args.page_url,
                args.closed_pull_request,
                args.mark_closed_pull_requests,
            )
    except PreviewError as error:
        print(f"map-atlas-preview: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
