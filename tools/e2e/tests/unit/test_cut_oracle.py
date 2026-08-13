from pathlib import Path
import hashlib
import json

import pytest

from tools.e2e.generate_cut_oracle import (
    BASE_FIXTURE_PATH,
    CAPABILITIES,
    LEGACY_FLAGS,
    ORACLE_PATH,
    instrumentation_overlay,
    load_reviewed_oracle,
    run,
)
from tools.e2e.generate_populated_fixture import canonical_patch
from tools.e2e.save_file import SaveImage, with_saved_flags


ROOT = Path(__file__).parents[4]


def test_capability_oracle_binds_committed_overlay_and_reviewed_base_fixture():
    oracle = load_reviewed_oracle(ROOT / ORACLE_PATH)
    image = SaveImage.from_path(ROOT / BASE_FIXTURE_PATH)
    bases, overlay = instrumentation_overlay(ROOT)

    assert image.sha256 == oracle["source"]["baseFixtureSha256"]
    assert (
        hashlib.sha256(canonical_patch(bases, overlay)).hexdigest()
        == oracle["source"]["instrumentationPatchSha256"]
    )


def test_capability_oracle_matrix_is_complete_and_variants_add_no_regional_facts():
    oracle = load_reviewed_oracle(ROOT / ORACLE_PATH)
    image = SaveImage.from_path(ROOT / BASE_FIXTURE_PATH)
    scenarios = {
        tuple(item["legacySlots"]): item["unlockedCapabilities"]
        for item in oracle["matrix"]
    }

    assert scenarios == {
        tuple(index == granted for index in range(len(CAPABILITIES))): (
            [] if granted is None else [CAPABILITIES[granted][0]]
        )
        for granted in (None, *range(len(CAPABILITIES)))
    }
    for slots in scenarios:
        variant = with_saved_flags(image, dict(zip(LEGACY_FLAGS, slots, strict=True)))
        for flag, enabled in zip(LEGACY_FLAGS, slots, strict=True):
            assert variant.active_slot.saved_flag(flag) is enabled
        assert all(
            not variant.active_slot.saved_flag(flag) for flag in range(0x20, 0x35)
        )


def test_candidate_cannot_overwrite_reviewed_oracle_before_capture():
    captured = False

    def capture(_source_tree, _skyemu):
        nonlocal captured
        captured = True
        raise AssertionError("capture must not run")

    with pytest.raises(ValueError, match="cannot overwrite"):
        run(
            [
                "--source-tree",
                str(ROOT),
                "--skyemu",
                "/unused/skyemu",
                "--candidate-output",
                str(ROOT / ORACLE_PATH),
            ],
            capture=capture,
        )

    assert not captured


@pytest.mark.parametrize(
    "mutation",
    [
        lambda oracle: oracle.update(
            {"reviewStatus": "UNREVIEWED_CANDIDATE_DO_NOT_USE_AS_ORACLE"}
        ),
        lambda oracle: oracle["source"].update({"unexpected": "value"}),
        lambda oracle: oracle["matrix"][0].pop("unlockedCapabilities"),
    ],
    ids=["unreviewed-candidate", "extra-source-key", "missing-matrix-key"],
)
def test_e2e_oracle_loader_rejects_unreviewed_or_malformed_documents(
    tmp_path, mutation
):
    oracle = json.loads((ROOT / ORACLE_PATH).read_text())
    mutation(oracle)
    candidate = tmp_path / "candidate.json"
    candidate.write_text(json.dumps(oracle))

    with pytest.raises(ValueError, match="malformed"):
        load_reviewed_oracle(candidate)
