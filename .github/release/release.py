#!/usr/bin/env python3
"""Fail-closed GitHub Release validation and publication for pokemon-openworld."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import html
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
from typing import Any, Callable, Iterable


ASSET_NAMES = (
    "pokemon-openworld.gba",
    "pokemon-openworld.map",
    "pokemon-openworld.sym",
)
CI_WORKFLOW_PATH = ".github/workflows/ci.yml"
SHA_RE = re.compile(r"[0-9a-f]{40}\Z")
VERSION_RE = re.compile(r"v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\Z")
SOURCE_RE = re.compile(r"build-([0-9a-f]{12})\Z")
DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
CONVENTIONAL_RE = re.compile(
    r"(build|chore|ci|docs|feat|fix|perf|refactor|revert|style|test)"
    r"(?:\(([a-z0-9._/-]+)\))?(!)?: (.+)\Z"
)
BREAKING_RE = re.compile(r"^BREAKING(?: CHANGE|-CHANGE):\s*\S", re.MULTILINE)
TYPE_HEADINGS = (
    ("feat", "Features"),
    ("fix", "Bug Fixes"),
    ("perf", "Performance"),
    ("refactor", "Refactoring"),
    ("docs", "Documentation"),
    ("test", "Tests"),
    ("build", "Build"),
    ("ci", "Continuous Integration"),
    ("chore", "Chores"),
    ("revert", "Reverts"),
    ("style", "Style"),
)


class ReleaseError(RuntimeError):
    pass


@dataclass(frozen=True)
class Change:
    sha: str
    type: str
    scope: str | None
    description: str
    breaking: bool


@dataclass(frozen=True)
class StableRelease:
    tag: str
    version: tuple[int, int, int]
    release: dict[str, Any]


def fail(message: str) -> None:
    raise ReleaseError(message)


def env(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        fail(f"required environment variable {name} is empty")
    return value


def validate_sha(value: str) -> str:
    if not SHA_RE.fullmatch(value):
        fail("source SHA must be exactly 40 lowercase hexadecimal characters")
    return value


def version_tuple(value: str) -> tuple[int, int, int]:
    match = VERSION_RE.fullmatch(value)
    if not match:
        fail("version must be canonical vX.Y.Z SemVer without leading zeroes")
    return tuple(int(part) for part in match.groups())


def validate_version(value: str) -> str:
    version_tuple(value)
    return value


def validate_source_tag(value: str) -> str:
    if not SOURCE_RE.fullmatch(value):
        fail("source must be build- followed by exactly 12 lowercase hex characters")
    return value


def run(*args: str, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        args,
        cwd=cwd,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check and result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
        fail(f"command failed ({args[0]}): {detail}")
    return result


def git(*args: str, cwd: Path | None = None) -> str:
    return run("git", *args, cwd=cwd).stdout.strip()


def gh(*args: str) -> str:
    return run("gh", *args).stdout


def gh_api(path: str, *, optional: bool = False) -> Any | None:
    result = run("gh", "api", path, check=False)
    if result.returncode:
        if optional and "HTTP 404" in result.stderr:
            return None
        detail = result.stderr.strip() or result.stdout.strip()
        fail(f"GitHub API request failed for {path}: {detail}")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        fail(f"GitHub API returned invalid JSON for {path}: {error}")


def gh_api_pages(path: str) -> list[list[Any]]:
    result = run("gh", "api", "--paginate", "--slurp", path)
    try:
        pages = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        fail(f"GitHub API returned invalid paginated JSON for {path}: {error}")
    if not isinstance(pages, list) or any(not isinstance(page, list) for page in pages):
        fail("paginated GitHub API response has an unexpected form")
    return pages


def repository() -> str:
    value = env("GITHUB_REPOSITORY")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value):
        fail("GITHUB_REPOSITORY has an unexpected form")
    return value


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def validate_asset_dir(directory: Path) -> dict[str, str]:
    if not directory.is_dir() or directory.is_symlink():
        fail(f"asset path is not a real directory: {directory}")
    entries = list(directory.iterdir())
    names = {entry.name for entry in entries}
    if names != set(ASSET_NAMES) or len(entries) != len(ASSET_NAMES):
        fail(f"assets must contain exactly {', '.join(ASSET_NAMES)}")
    digests: dict[str, str] = {}
    for name in ASSET_NAMES:
        path = directory / name
        mode = path.lstat().st_mode
        if not stat.S_ISREG(mode) or path.is_symlink():
            fail(f"asset must be a regular non-symlink file: {name}")
        if path.stat().st_size <= 0:
            fail(f"asset must be nonempty: {name}")
        digests[name] = sha256(path)
    return digests


def release_assets(release: dict[str, Any]) -> dict[str, dict[str, Any]]:
    assets = release.get("assets")
    if not isinstance(assets, list):
        fail("release assets are missing")
    by_name: dict[str, dict[str, Any]] = {}
    for asset in assets:
        if not isinstance(asset, dict) or not isinstance(asset.get("name"), str):
            fail("release contains malformed asset metadata")
        name = asset["name"]
        if name in by_name:
            fail(f"release contains duplicate asset {name}")
        if name not in ASSET_NAMES:
            fail(f"release contains unexpected asset {name}")
        if asset.get("state") != "uploaded" or type(asset.get("size")) is not int or asset["size"] <= 0:
            fail(f"release asset is not a completed nonempty upload: {name}")
        digest = asset.get("digest")
        if not isinstance(digest, str) or not DIGEST_RE.fullmatch(digest):
            fail(f"release asset lacks a valid GitHub sha256 digest: {name}")
        by_name[name] = asset
    return by_name


def validate_release_metadata(
    release: dict[str, Any], tag: str, source_sha: str, *, prerelease: bool, title: str
) -> None:
    if release.get("tag_name") != tag:
        fail("release tag does not match the requested tag")
    if release.get("target_commitish") != source_sha:
        fail("release target does not match the immutable source commit")
    if release.get("draft") is not False or release.get("prerelease") is not prerelease:
        fail("release draft/prerelease state is unexpected")
    if release.get("name") != title:
        fail("release title is unexpected")


def validate_release_body(release: dict[str, Any], expected: str) -> None:
    body = release.get("body")
    if not isinstance(body, str):
        fail("release notes are missing")
    # GitHub's release API preserves LF newlines. Compare the complete text,
    # including the final newline, so provenance and changelog edits fail closed.
    if body != expected:
        fail("release notes do not exactly match the generated notes")


def validate_release_asset_bytes(
    release: dict[str, Any], local_digests: dict[str, str], *, allow_missing: bool
) -> list[str]:
    remote = release_assets(release)
    missing = [name for name in ASSET_NAMES if name not in remote]
    if missing and not allow_missing:
        fail(f"release is missing assets: {', '.join(missing)}")
    for name, asset in remote.items():
        if asset["digest"] != local_digests[name]:
            fail(f"release asset digest does not match local bytes: {name}")
    return missing


def resolve_tag_commit(repo: str, tag: str, *, optional: bool = False) -> str | None:
    ref = gh_api(f"repos/{repo}/git/ref/tags/{tag}", optional=optional)
    if ref is None:
        return None
    commit = gh_api(f"repos/{repo}/commits/{tag}")
    if not isinstance(commit, dict) or not isinstance(commit.get("sha"), str):
        fail(f"could not resolve tag {tag} to a commit")
    return validate_sha(commit["sha"])


def release_for_tag(repo: str, tag: str) -> dict[str, Any] | None:
    release = gh_api(f"repos/{repo}/releases/tags/{tag}", optional=True)
    if release is not None and not isinstance(release, dict):
        fail("release response has an unexpected form")
    return release


def published_stable_releases(pages: Iterable[Iterable[Any]]) -> list[StableRelease]:
    found: dict[str, StableRelease] = {}
    for page in pages:
        for release in page:
            if not isinstance(release, dict):
                fail("release listing contains a malformed entry")
            tag = release.get("tag_name")
            draft = release.get("draft")
            prerelease = release.get("prerelease")
            if not isinstance(tag, str) or type(draft) is not bool or type(prerelease) is not bool:
                fail("release listing contains malformed metadata")
            if draft or prerelease or not VERSION_RE.fullmatch(tag):
                continue
            if tag in found:
                fail(f"release listing contains duplicate stable tag {tag}")
            found[tag] = StableRelease(tag, version_tuple(tag), release)
    return sorted(found.values(), key=lambda item: item.version)


def all_published_stables(repo: str) -> list[StableRelease]:
    return published_stable_releases(gh_api_pages(f"repos/{repo}/releases?per_page=100"))


def enforce_version_monotonicity(
    requested: str, stables: Iterable[StableRelease], *, allow_existing: bool
) -> None:
    requested_value = version_tuple(requested)
    others = [item.version for item in stables if not allow_existing or item.tag != requested]
    if any(requested_value <= existing for existing in others):
        fail("stable version must be strictly greater than every published stable version")


def is_ancestor_via_api(repo: str, ancestor: str, source_sha: str) -> bool:
    comparison = gh_api(f"repos/{repo}/compare/{ancestor}...{source_sha}")
    if not isinstance(comparison, dict) or not isinstance(comparison.get("status"), str):
        fail("commit comparison response has an unexpected form")
    return comparison["status"] in ("ahead", "identical")


def previous_stable_boundary(
    repo: str,
    source_sha: str,
    requested: str,
    stables: Iterable[StableRelease],
    *,
    resolver: Callable[[str, str], str | None] | None = None,
    reachable: Callable[[str, str, str], bool] | None = None,
) -> tuple[str, str] | None:
    resolver = resolver or (lambda selected_repo, tag: resolve_tag_commit(selected_repo, tag, optional=True))
    reachable = reachable or is_ancestor_via_api
    candidates: list[tuple[tuple[int, int, int], str, str]] = []
    for item in stables:
        if item.tag == requested:
            continue
        tag_sha = resolver(repo, item.tag)
        if tag_sha is not None and reachable(repo, tag_sha, source_sha):
            candidates.append((item.version, item.tag, tag_sha))
    if not candidates:
        return None
    _, tag, tag_sha = max(candidates)
    return tag, tag_sha


def verify_ci_run(run_data: dict[str, Any], repo: str, source_sha: str) -> None:
    head_repo = run_data.get("head_repository") or {}
    expected = {
        "name": "CI",
        "path": CI_WORKFLOW_PATH,
        "event": "push",
        "head_branch": "main",
        "head_sha": source_sha,
        "conclusion": "success",
        "status": "completed",
    }
    for key, value in expected.items():
        if run_data.get(key) != value:
            fail(f"CI run has unexpected {key}")
    if not isinstance(head_repo, dict) or head_repo.get("full_name") != repo:
        fail("CI run did not originate in this repository")


def validate_snapshot_source() -> None:
    repo = repository()
    source_sha = validate_sha(env("SOURCE_SHA"))
    run_id = env("SOURCE_RUN_ID")
    if not re.fullmatch(r"[1-9][0-9]*", run_id):
        fail("workflow run ID must be a positive integer")
    data = gh_api(f"repos/{repo}/actions/runs/{run_id}")
    if not isinstance(data, dict):
        fail("workflow run response has an unexpected form")
    verify_ci_run(data, repo, source_sha)
    if git("rev-parse", "HEAD") != source_sha:
        fail("checkout does not match the validated CI source SHA")


def find_successful_ci_run(repo: str, source_sha: str) -> str:
    query = (
        f"repos/{repo}/actions/workflows/ci.yml/runs"
        f"?head_sha={source_sha}&event=push&branch=main&status=completed&per_page=100"
    )
    data = gh_api(query)
    runs = data.get("workflow_runs") if isinstance(data, dict) else None
    if not isinstance(runs, list):
        fail("CI workflow run search response has an unexpected form")
    valid: list[dict[str, Any]] = []
    for candidate in runs:
        if not isinstance(candidate, dict):
            fail("CI workflow run search contains a malformed entry")
        try:
            verify_ci_run(candidate, repo, source_sha)
        except ReleaseError:
            continue
        valid.append(candidate)
    if not valid:
        fail("no exact successful CI push/main run exists for the source commit")
    run_ids = [candidate.get("id") for candidate in valid]
    if any(type(run_id) is not int or run_id <= 0 for run_id in run_ids):
        fail("successful CI run has an invalid ID")
    return str(min(run_ids))


def append_env(name: str, value: str) -> None:
    if not re.fullmatch(r"[A-Z_]+", name) or "\n" in value or "\r" in value:
        fail("refusing to write malformed workflow environment data")
    target = os.environ.get("GITHUB_ENV")
    if target:
        with Path(target).open("a", encoding="utf-8") as handle:
            handle.write(f"{name}={value}\n")


def resolve_stable_source() -> str:
    repo = repository()
    version = validate_version(env("RELEASE_VERSION"))
    source = validate_source_tag(env("SNAPSHOT_TAG"))
    source_sha = resolve_tag_commit(repo, source)
    if source_sha is None:
        fail("snapshot tag does not exist")
    suffix = SOURCE_RE.fullmatch(source)
    assert suffix is not None
    if suffix.group(1) != source_sha[:12]:
        fail("snapshot tag suffix does not match its full source SHA")
    release = release_for_tag(repo, source)
    if release is None:
        fail("snapshot tag has no published release")
    validate_release_metadata(release, source, source_sha, prerelease=True, title=f"Snapshot {source}")
    ci_run_id = find_successful_ci_run(repo, source_sha)
    snapshot_change = parse_conventional_commit(
        source_sha,
        git("show", "-s", "--format=%s", source_sha),
        git("show", "-s", "--format=%b", source_sha),
    )
    snapshot_changelog = render_changes([snapshot_change] if snapshot_change else []).strip()
    validate_release_body(
        release,
        release_notes_text(
            "snapshot", snapshot_changelog, source_sha, repo, ci_run_id,
        ),
    )
    if set(release_assets(release)) != set(ASSET_NAMES):
        fail("snapshot release does not contain exactly the required assets")
    if not is_ancestor_via_api(repo, source_sha, "main"):
        fail("snapshot source is not reachable from main")

    stables = all_published_stables(repo)
    existing_release = next((item.release for item in stables if item.tag == version), None)
    existing_tag_sha = resolve_tag_commit(repo, version, optional=True)
    if existing_release is not None:
        if existing_tag_sha is None:
            fail("published stable release exists without its tag")
        if existing_tag_sha != source_sha:
            fail("existing stable tag points at a different commit")
        validate_release_metadata(
            existing_release, version, source_sha, prerelease=False,
            title=f"Pokémon OpenWorld {version}",
        )
    elif existing_tag_sha is not None and existing_tag_sha != source_sha:
        fail("existing stable tag points at a different commit")
    enforce_version_monotonicity(version, stables, allow_existing=existing_release is not None)
    boundary = previous_stable_boundary(repo, source_sha, version, stables)
    if boundary:
        append_env("PREVIOUS_STABLE_TAG", boundary[0])
        append_env("PREVIOUS_STABLE_SHA", boundary[1])
    append_env("SOURCE_CI_RUN_ID", ci_run_id)
    return source_sha


def fetch_stable_source() -> None:
    source_sha = validate_sha(env("SOURCE_SHA"))
    policy_sha = git("rev-parse", "HEAD")
    if git("rev-parse", "origin/main") != policy_sha:
        fail("stable policy checkout is not the current origin/main commit")
    run("git", "fetch", "--no-tags", "origin", source_sha)
    if git("rev-parse", f"{source_sha}^{{commit}}") != source_sha:
        fail("resolved snapshot source is not a commit")
    result = run("git", "merge-base", "--is-ancestor", source_sha, policy_sha, check=False)
    if result.returncode != 0:
        fail("snapshot source is not an ancestor of the current main policy commit")
    if git("rev-parse", "HEAD") != policy_sha:
        fail("source inspection changed the checked-out policy revision")


def download_snapshot(directory: Path) -> None:
    repo = repository()
    source = validate_source_tag(env("SNAPSHOT_TAG"))
    directory.mkdir(mode=0o700, parents=False, exist_ok=False)
    for name in ASSET_NAMES:
        gh("release", "download", source, "--repo", repo, "--dir", str(directory), "--pattern", name)


def verify_snapshot_assets(directory: Path) -> None:
    repo = repository()
    source = validate_source_tag(env("SNAPSHOT_TAG"))
    source_sha = validate_sha(env("SOURCE_SHA"))
    if resolve_tag_commit(repo, source) != source_sha:
        fail("snapshot tag changed while assets were downloaded")
    release = release_for_tag(repo, source)
    if release is None:
        fail("snapshot release disappeared while assets were downloaded")
    validate_release_metadata(release, source, source_sha, prerelease=True, title=f"Snapshot {source}")
    digests = validate_asset_dir(directory)
    validate_release_asset_bytes(release, digests, allow_missing=False)


def parse_conventional_commit(sha: str, subject: str, body: str) -> Change | None:
    validate_sha(sha)
    if "\n" in subject or "\r" in subject or "\x00" in subject or "\x00" in body:
        fail("commit metadata contains forbidden control characters")
    match = CONVENTIONAL_RE.fullmatch(subject)
    if not match:
        return None
    type_, scope, marker, description = match.groups()
    return Change(sha, type_, scope, description, bool(marker) or bool(BREAKING_RE.search(body)))


def markdown_escape(value: str) -> str:
    escaped = html.escape(value, quote=False)
    return re.sub(r"([\\`*_{}\[\]()<>#+.!|~-])", r"\\\1", escaped)


def render_changes(changes: Iterable[Change]) -> str:
    grouped: dict[str, list[Change]] = {type_: [] for type_, _ in TYPE_HEADINGS}
    breaking: list[Change] = []
    for change in changes:
        (breaking if change.breaking else grouped[change.type]).append(change)
    sections: list[tuple[str, list[Change]]] = []
    if breaking:
        sections.append(("Breaking Changes", breaking))
    sections.extend((heading, grouped[type_]) for type_, heading in TYPE_HEADINGS if grouped[type_])
    if not sections:
        return "No Conventional Commit entries in this range.\n"
    output: list[str] = []
    for heading, entries in sections:
        output.append(f"### {heading}\n")
        for change in entries:
            scope = f"**{markdown_escape(change.scope)}:** " if change.scope else ""
            output.append(f"- {scope}{markdown_escape(change.description)} (`{change.sha[:7]}`)")
        output.append("")
    return "\n".join(output).rstrip() + "\n"


def revision_range(kind: str, source_sha: str, previous_sha: str | None) -> str:
    validate_sha(source_sha)
    if kind == "snapshot":
        if previous_sha is not None:
            fail("snapshot changelog cannot have a previous stable boundary")
        return f"{source_sha}^!"
    if kind == "stable":
        return f"{validate_sha(previous_sha)}..{source_sha}" if previous_sha else source_sha
    fail("changelog kind must be snapshot or stable")


def changelog(kind: str, output: Path) -> None:
    source_sha = validate_sha(env("SOURCE_SHA"))
    previous = os.environ.get("PREVIOUS_STABLE_SHA") or None
    revision = revision_range(kind, source_sha, previous)
    shas = git("rev-list", "--reverse", revision).splitlines()
    changes: list[Change] = []
    for commit_sha in shas:
        commit_sha = validate_sha(commit_sha)
        subject = git("show", "-s", "--format=%s", commit_sha)
        body = git("show", "-s", "--format=%b", commit_sha)
        change = parse_conventional_commit(commit_sha, subject, body)
        if change:
            changes.append(change)
    output.write_text(render_changes(changes), encoding="utf-8")


def release_notes_text(
    kind: str,
    changes: str,
    source_sha: str,
    repo: str,
    run_id: str,
    *,
    source: str | None = None,
) -> str:
    validate_sha(source_sha)
    if kind == "snapshot":
        heading = f"Source commit: `{source_sha}`\n\nCI origin: https://github.com/{repo}/actions/runs/{run_id}"
    elif kind == "stable":
        if source is None:
            fail("stable notes require a snapshot source tag")
        validate_source_tag(source)
        heading = (
            f"Source commit: `{source_sha}`\n\n"
            f"Promoted snapshot: https://github.com/{repo}/releases/tag/{source}\n\n"
            f"CI origin: https://github.com/{repo}/actions/runs/{run_id}"
        )
    else:
        fail("notes kind must be snapshot or stable")
    return f"{heading}\n\n## Changes\n\n{changes}\n"


def compose_notes(kind: str, changelog_path: Path, output: Path) -> None:
    source_sha = validate_sha(env("SOURCE_SHA"))
    repo = repository()
    changes = changelog_path.read_text(encoding="utf-8").strip()
    if kind == "snapshot":
        rendered = release_notes_text(kind, changes, source_sha, repo, env("SOURCE_RUN_ID"))
    elif kind == "stable":
        rendered = release_notes_text(
            kind,
            changes,
            source_sha,
            repo,
            env("SOURCE_CI_RUN_ID"),
            source=env("SNAPSHOT_TAG"),
        )
    else:
        fail("notes kind must be snapshot or stable")
    output.write_text(rendered, encoding="utf-8")


def latest_release_tag(repo: str) -> str | None:
    release = gh_api(f"repos/{repo}/releases/latest", optional=True)
    if release is None:
        return None
    if not isinstance(release, dict) or not isinstance(release.get("tag_name"), str):
        fail("latest release response has an unexpected form")
    return release["tag_name"]


def upload_assets(repo: str, tag: str, directory: Path, names: list[str]) -> None:
    for name in names:
        gh("release", "upload", tag, str(directory / name), "--repo", repo)


def release_create_args(
    tag: str,
    repo: str,
    source_sha: str,
    title: str,
    notes: Path,
    directory: Path,
    *,
    prerelease: bool,
    verify_tag: bool,
) -> list[str]:
    args = ["release", "create", tag]
    args.extend(str(directory / name) for name in ASSET_NAMES)
    args.extend(
        [
            "--repo", repo,
            "--target", source_sha,
            "--title", title,
            "--notes-file", str(notes),
        ]
    )
    args.extend(["--prerelease", "--latest=false"] if prerelease else ["--latest"])
    if verify_tag:
        args.append("--verify-tag")
    return args


def stable_repair_actions(tag_sha: str | None, release: dict[str, Any] | None, source_sha: str) -> tuple[bool, bool]:
    if tag_sha is not None and tag_sha != source_sha:
        fail("existing stable tag points at a different commit")
    if release is not None and tag_sha is None:
        fail("stable release exists without its immutable tag")
    return release is None, tag_sha is not None


def needs_latest_reassertion(latest_tag: str | None, version: str) -> bool:
    validate_version(version)
    return latest_tag != version


def publish_snapshot(directory: Path, notes: Path) -> None:
    repo = repository()
    source_sha = validate_sha(env("SOURCE_SHA"))
    tag = f"build-{source_sha[:12]}"
    title = f"Snapshot {tag}"
    expected_body = notes.read_text(encoding="utf-8")
    digests = validate_asset_dir(directory)
    tag_sha = resolve_tag_commit(repo, tag, optional=True)
    if tag_sha is not None and tag_sha != source_sha:
        fail("existing snapshot tag points at a different commit")
    release = release_for_tag(repo, tag)
    if release is not None and tag_sha is None:
        fail("snapshot release exists without its immutable tag")
    existing_release = release is not None
    if not existing_release:
        gh(*release_create_args(
            tag, repo, source_sha, title, notes, directory,
            prerelease=True, verify_tag=tag_sha is not None,
        ))
        release = release_for_tag(repo, tag)
        if release is None:
            fail("snapshot release was not visible after creation")
    if resolve_tag_commit(repo, tag) != source_sha:
        fail("snapshot tag changed during publication")
    validate_release_metadata(release, tag, source_sha, prerelease=True, title=title)
    validate_release_body(release, expected_body)
    if latest_release_tag(repo) == tag:
        fail("snapshot release unexpectedly became latest")
    missing = validate_release_asset_bytes(release, digests, allow_missing=existing_release)
    if missing:
        # Legacy releases created before immutable releases were enabled may be
        # repairable. A published immutable release will reject this upload,
        # which intentionally fails closed without deleting or retargeting it.
        upload_assets(repo, tag, directory, missing)
        release = release_for_tag(repo, tag)
        if release is None:
            fail("snapshot release disappeared after asset upload")
        validate_release_metadata(release, tag, source_sha, prerelease=True, title=title)
        validate_release_body(release, expected_body)
        validate_release_asset_bytes(release, digests, allow_missing=False)


def publish_stable(directory: Path, notes: Path) -> None:
    repo = repository()
    version = validate_version(env("RELEASE_VERSION"))
    source_sha = validate_sha(env("SOURCE_SHA"))
    title = f"Pokémon OpenWorld {version}"
    expected_body = notes.read_text(encoding="utf-8")
    digests = validate_asset_dir(directory)
    verify_snapshot_assets(directory)

    tag_sha = resolve_tag_commit(repo, version, optional=True)
    release = release_for_tag(repo, version)
    create_release, verify_tag = stable_repair_actions(tag_sha, release, source_sha)
    existing_release = not create_release
    if release is not None:
        validate_release_metadata(release, version, source_sha, prerelease=False, title=title)
        validate_release_body(release, expected_body)
        validate_release_asset_bytes(release, digests, allow_missing=True)
    if create_release:
        gh(*release_create_args(
            version, repo, source_sha, title, notes, directory,
            prerelease=False, verify_tag=verify_tag,
        ))

    release = release_for_tag(repo, version)
    if release is None or resolve_tag_commit(repo, version) != source_sha:
        fail("stable release/tag was not visible at the expected commit")
    validate_release_metadata(release, version, source_sha, prerelease=False, title=title)
    validate_release_body(release, expected_body)
    missing = validate_release_asset_bytes(release, digests, allow_missing=existing_release)
    if missing:
        upload_assets(repo, version, directory, missing)
        release = release_for_tag(repo, version)
        if release is None or resolve_tag_commit(repo, version) != source_sha:
            fail("stable release/tag changed during asset repair")
        validate_release_metadata(release, version, source_sha, prerelease=False, title=title)
        validate_release_body(release, expected_body)
        validate_release_asset_bytes(release, digests, allow_missing=False)

    if needs_latest_reassertion(latest_release_tag(repo), version):
        if not existing_release:
            fail("new stable release was not marked latest during atomic publication")
        gh("release", "edit", version, "--repo", repo, "--latest")
    if latest_release_tag(repo) != version:
        fail("stable release is not marked latest")


def fixture_release(
    tag: str,
    sha: str,
    digests: dict[str, str],
    names: tuple[str, ...],
    *,
    prerelease: bool = True,
    body: str = "generated notes\n",
) -> dict[str, Any]:
    return {
        "tag_name": tag,
        "target_commitish": sha,
        "draft": False,
        "prerelease": prerelease,
        "name": f"Snapshot {tag}" if prerelease else f"Pokémon OpenWorld {tag}",
        "body": body,
        "assets": [
            {"name": name, "state": "uploaded", "size": 1, "digest": digests[name]}
            for name in names
        ],
    }


def expect_failure(callable_: Callable[[], Any], message: str) -> None:
    try:
        callable_()
    except (ReleaseError, FileExistsError):
        return
    fail(f"self-test expected failure: {message}")


def self_test() -> None:
    sha = "a" * 40
    other_sha = "b" * 40
    assert validate_sha(sha) == sha
    assert validate_version("v1.2.3") == "v1.2.3"
    assert validate_source_tag("build-" + "a" * 12)
    for malformed in ("v1.2", "v01.2.3", "1.2.3", "v1.2.3 ", "v1.2.3\n"):
        expect_failure(lambda value=malformed: validate_version(value), malformed)
    for malformed in ("build-ABCDEF123456", "build-abc", "build-" + "a" * 13):
        expect_failure(lambda value=malformed: validate_source_tag(value), malformed)
    assert revision_range("snapshot", sha, None) == f"{sha}^!"
    assert revision_range("stable", sha, other_sha) == f"{other_sha}..{sha}"
    assert revision_range("stable", sha, None) == sha

    ci_run = {
        "name": "CI",
        "path": CI_WORKFLOW_PATH,
        "event": "push",
        "head_branch": "main",
        "head_sha": sha,
        "conclusion": "success",
        "status": "completed",
        "head_repository": {"full_name": "owner/repo"},
    }
    verify_ci_run(ci_run, "owner/repo", sha)
    expect_failure(
        lambda: verify_ci_run(
            dict(ci_run, path=".github/workflows/untrusted-ci.yml"), "owner/repo", sha
        ),
        "same-name CI run at another workflow path",
    )

    scoped = parse_conventional_commit(sha, "feat(world-map)!: add Johto", "")
    assert scoped == Change(sha, "feat", "world-map", "add Johto", True)
    assert parse_conventional_commit(sha, "fix: stop crash", "BREAKING CHANGE: save format") == Change(
        sha, "fix", None, "stop crash", True
    )
    assert parse_conventional_commit(sha, "not conventional", "") is None
    assert parse_conventional_commit(sha, "feat(Bad): rejected scope", "") is None
    expect_failure(lambda: parse_conventional_commit(sha, "feat: injected\n### Pwn", ""), "subject newline")
    rendered = render_changes(
        [
            Change(sha, "fix", None, "escape [link](javascript:bad)", False),
            Change(other_sha, "feat", "map", "add region", False),
            Change(sha, "ci", None, "change release", True),
        ]
    )
    assert rendered.index("### Breaking Changes") < rendered.index("### Features") < rendered.index("### Bug Fixes")
    assert "**map:** add region" in rendered
    assert "[link](javascript:bad)" not in rendered

    release_rows = [
        {"tag_name": "v1.0.0", "draft": False, "prerelease": False},
        {"tag_name": "v2.0.0", "draft": True, "prerelease": False},
        {"tag_name": "v3.0.0", "draft": False, "prerelease": True},
        {"tag_name": "build-aaaaaaaaaaaa", "draft": False, "prerelease": False},
        {"tag_name": "v1.5.0", "draft": False, "prerelease": False},
    ]
    stables = published_stable_releases([release_rows[:2], release_rows[2:]])
    assert [item.tag for item in stables] == ["v1.0.0", "v1.5.0"]
    expect_failure(lambda: enforce_version_monotonicity("v1.5.0", stables, allow_existing=False), "not greater")
    enforce_version_monotonicity("v1.5.0", stables, allow_existing=True)
    enforce_version_monotonicity("v2.0.0", stables, allow_existing=False)
    boundary = previous_stable_boundary(
        "owner/repo", sha, "v2.0.0", stables,
        resolver=lambda _repo, tag: {"v1.0.0": other_sha, "v1.5.0": "c" * 40}[tag],
        reachable=lambda _repo, candidate, _source: candidate == other_sha,
    )
    assert boundary == ("v1.0.0", other_sha), "unreachable published releases must not bound changelogs"
    expect_failure(lambda: published_stable_releases([[{"tag_name": "v1.0.0"}]]), "malformed release")

    assert stable_repair_actions(None, None, sha) == (True, False)
    assert stable_repair_actions(sha, None, sha) == (True, True)
    assert stable_repair_actions(sha, {}, sha) == (False, True)
    expect_failure(lambda: stable_repair_actions(other_sha, None, sha), "retarget refusal")
    expect_failure(lambda: stable_repair_actions(None, {}, sha), "release without tag")
    assert needs_latest_reassertion(None, "v1.2.3")
    assert needs_latest_reassertion("v1.2.2", "v1.2.3")
    assert not needs_latest_reassertion("v1.2.3", "v1.2.3")

    create_args = release_create_args(
        "build-" + sha[:12], "owner/repo", sha, "Snapshot", Path("notes.md"),
        Path("release"), prerelease=True, verify_tag=True,
    )
    assert create_args[:3] == ["release", "create", "build-" + sha[:12]]
    assert create_args[3:6] == [str(Path("release") / name) for name in ASSET_NAMES]
    assert "--prerelease" in create_args and "--latest=false" in create_args
    assert create_args[-1] == "--verify-tag"
    stable_create_args = release_create_args(
        "v1.2.3", "owner/repo", sha, "Stable", Path("notes.md"),
        Path("release"), prerelease=False, verify_tag=False,
    )
    assert stable_create_args[3:6] == [str(Path("release") / name) for name in ASSET_NAMES]
    assert "--latest" in stable_create_args and "--prerelease" not in stable_create_args

    workflow = (Path(__file__).parents[1] / "workflows" / "release.yml").read_text(encoding="utf-8")
    if "ref: refs/heads/main" not in workflow or "ref: ${{ steps.source.outputs.sha }}" in workflow:
        fail("stable workflow must keep current main policy checked out")
    uses = re.findall(r"^\s*uses:\s*([^\s]+)$", workflow, re.MULTILINE)
    if not uses or any(not re.fullmatch(r"actions/[A-Za-z0-9_.-]+@[0-9a-f]{40}", use) for use in uses):
        fail("release workflow actions must use immutable official commit SHAs")

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        assets = root / "assets"
        assets.mkdir()
        for name in ASSET_NAMES:
            (assets / name).write_bytes(name.encode())
        digests = validate_asset_dir(assets)
        full = fixture_release("build-" + sha[:12], sha, digests, ASSET_NAMES)
        validate_release_metadata(full, "build-" + sha[:12], sha, prerelease=True, title=f"Snapshot build-{sha[:12]}")
        validate_release_body(full, "generated notes\n")
        expect_failure(lambda: validate_release_body(full, "generated notes"), "final newline mismatch")
        expect_failure(lambda: validate_release_body(dict(full, body="altered notes\n"), "generated notes\n"), "notes mismatch")
        assert validate_release_asset_bytes(full, digests, allow_missing=True) == []
        partial = fixture_release("build-" + sha[:12], sha, digests, ASSET_NAMES[:2])
        assert validate_release_asset_bytes(partial, digests, allow_missing=True) == [ASSET_NAMES[2]]
        expect_failure(lambda: validate_release_asset_bytes(partial, digests, allow_missing=False), "partial assets")
        stable = fixture_release("v1.2.3", sha, digests, ASSET_NAMES, prerelease=False)
        validate_release_metadata(stable, "v1.2.3", sha, prerelease=False, title="Pokémon OpenWorld v1.2.3")
        wrong_digest = json.loads(json.dumps(stable))
        wrong_digest["assets"][0]["digest"] = "sha256:" + "0" * 64
        expect_failure(lambda: validate_release_asset_bytes(wrong_digest, digests, allow_missing=True), "digest mismatch")
        wrong_title = dict(stable, name="malicious")
        expect_failure(
            lambda: validate_release_metadata(wrong_title, "v1.2.3", sha, prerelease=False, title="Pokémon OpenWorld v1.2.3"),
            "title mismatch",
        )
        extra = assets / "unexpected.txt"
        extra.write_text("x")
        expect_failure(lambda: validate_asset_dir(assets), "extra asset")
        extra.unlink()
        (assets / ASSET_NAMES[0]).unlink()
        (assets / ASSET_NAMES[0]).symlink_to(assets / ASSET_NAMES[1])
        expect_failure(lambda: validate_asset_dir(assets), "symlink asset")

        fixture = root / "repo"
        fixture.mkdir()
        git("init", "-q", cwd=fixture)
        git("config", "user.email", "release-test@example.invalid", cwd=fixture)
        git("config", "user.name", "Release Test", cwd=fixture)
        for index, subject in enumerate(("feat: first", "fix(core): second", "ci!: third"), start=1):
            (fixture / "file").write_text(str(index))
            git("add", "file", cwd=fixture)
            git("commit", "-q", "-m", subject, cwd=fixture)
        head = git("rev-parse", "HEAD", cwd=fixture)
        assert len(git("rev-list", revision_range("snapshot", head, None), cwd=fixture).splitlines()) == 1
        root_sha = git("rev-list", "--max-parents=0", "HEAD", cwd=fixture)
        assert len(git("rev-list", revision_range("stable", head, root_sha), cwd=fixture).splitlines()) == 2
    print("release helper self-tests passed")


def main(argv: list[str]) -> None:
    if not argv:
        fail("missing command")
    command, *args = argv
    if command == "validate-snapshot-source" and not args:
        validate_snapshot_source()
    elif command == "resolve-stable-source" and not args:
        print(resolve_stable_source())
    elif command == "fetch-stable-source" and not args:
        fetch_stable_source()
    elif command == "validate-assets" and len(args) == 1:
        validate_asset_dir(Path(args[0]))
    elif command == "download-snapshot" and len(args) == 1:
        download_snapshot(Path(args[0]))
    elif command == "verify-snapshot-assets" and len(args) == 1:
        verify_snapshot_assets(Path(args[0]))
    elif command == "changelog" and len(args) == 2:
        changelog(args[0], Path(args[1]))
    elif command == "notes" and len(args) == 3:
        compose_notes(args[0], Path(args[1]), Path(args[2]))
    elif command == "publish-snapshot" and len(args) == 2:
        publish_snapshot(Path(args[0]), Path(args[1]))
    elif command == "publish-stable" and len(args) == 2:
        publish_stable(Path(args[0]), Path(args[1]))
    elif command == "self-test" and not args:
        self_test()
    else:
        fail(f"invalid arguments for command {command}")


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except ReleaseError as error:
        print(f"release error: {error}", file=sys.stderr)
        raise SystemExit(1) from error
