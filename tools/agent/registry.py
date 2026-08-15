"""Load the reviewed check routing authority."""

import json
import os
from pathlib import Path

REGISTRY_PATH = Path(__file__).with_name("registry.json")


def load_registry():
    document = json.loads(REGISTRY_PATH.read_text())
    if document.get("schemaVersion") != 1 or not isinstance(
        document.get("checks"), dict
    ):
        raise ValueError("unsupported tools.agent check registry")
    return document


def resolve(check_id, *, selector=None, workflows=()):
    definition = load_registry()["checks"].get(check_id)
    if definition is None:
        raise ValueError(f"unknown check id: {check_id}")
    selector_type = definition.get("selector")
    if selector_type in {"unittest", "pytest"}:
        if not selector or not _valid_python_selector(selector, selector_type):
            raise ValueError(f"{check_id} requires a valid --selector")
    elif selector:
        raise ValueError(f"{check_id} does not accept --selector")
    if selector_type == "workflows":
        if not workflows:
            raise ValueError("actionlint requires at least one --workflow")
        for workflow in workflows:
            path = Path(workflow)
            if (
                path.is_absolute()
                or ".." in path.parts
                or len(path.parts) != 3
                or path.parts[:2] != (".github", "workflows")
                or path.suffix not in {".yml", ".yaml"}
            ):
                raise ValueError(f"workflow is outside .github/workflows: {workflow}")
    elif workflows:
        raise ValueError(f"{check_id} does not accept --workflow")
    jobs = max(1, os.cpu_count() or 1)
    argv = []
    for value in definition["argv"]:
        if value == "{workflows}":
            argv.extend(sorted(set(workflows)))
        else:
            argv.append(value.format(selector=selector, jobs=jobs))
    return argv, definition


def _valid_python_selector(selector, selector_type):
    if (
        not selector
        or selector.startswith("-")
        or any(char.isspace() for char in selector)
    ):
        return False
    if selector_type == "pytest":
        path = selector.split("::", 1)[0]
        return (
            path.endswith(".py")
            and not Path(path).is_absolute()
            and ".." not in Path(path).parts
        )
    return all(part.isidentifier() for part in selector.split("."))
