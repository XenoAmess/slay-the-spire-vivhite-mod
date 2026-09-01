"""Offline tests for the Vivhite promo capture contract and adapter boundary.

The suite deliberately uses only tiny synthetic files.  It must remain safe to
run on a developer machine with no game, Steam client, OBS, or recorder
attached.  In particular, the validate-only test turns any attempt to spawn a
process into a test failure.
"""

from __future__ import annotations

import copy
import hashlib
import importlib
import inspect
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[3]
PROMO_ROOT = ROOT / "tools" / "promo"
SCHEMA_PATH = PROMO_ROOT / "schemas" / "vivhite-promo-capture-v1.schema.json"
PROJECT_PATH = PROMO_ROOT / "project.json"
PRESET_PATH = PROMO_ROOT / "preset.json"
FFMPEG_LOCK_PATH = PROMO_ROOT / "ffmpeg-lock.json"
STORYBOARD_PATH = PROMO_ROOT / "storyboard.json"
CLAIMS_PATH = PROMO_ROOT / "claims" / "claims.json"
FIXTURE_ROOT = PROMO_ROOT / "fixtures" / "minimal_capture"


def _add_local_import_paths() -> None:
    """Make the source check runnable without installing either local package."""

    for candidate in (
        PROMO_ROOT,
        Path(r"G:\workspace\xar_promo_toolchain") / "src",
    ):
        if candidate.is_dir() and str(candidate) not in sys.path:
            sys.path.insert(0, str(candidate))


def _read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise AssertionError(f"{path} must contain a JSON object")
    return value


def _fixture_contract_path() -> Path:
    """Find the fixture contract without coupling tests to a private filename."""

    candidates = sorted(
        path
        for path in FIXTURE_ROOT.glob("*.json")
        if path.name.lower() not in {"manifest.json", "metadata.json"}
    )
    if not candidates:
        raise AssertionError(f"no contract JSON found below {FIXTURE_ROOT}")
    # Prefer the conventional names if both a contract and auxiliary JSON exist.
    for name in ("capture.json", "contract.json", "capture_contract.json"):
        for candidate in candidates:
            if candidate.name.lower() == name:
                return candidate
    return candidates[0]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _iter_artifact_records(value: object):
    """Yield dictionaries that look like a bound media/evidence artifact."""

    if isinstance(value, dict):
        if {"path", "bytes", "sha256"}.issubset(value):
            yield value
        for child in value.values():
            yield from _iter_artifact_records(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_artifact_records(child)


def _receipt_payload(payload: dict) -> dict:
    """Return the direct or nested generic receipt portion."""

    receipt = payload.get("capture_receipt")
    return receipt if isinstance(receipt, dict) else payload


def _raw_record(payload: dict) -> dict:
    """Locate the raw media binding in either supported wire shape."""

    receipt = _receipt_payload(payload)
    media = receipt.get("media")
    if isinstance(media, dict):
        record = media.get("raw")
    else:
        record = receipt.get("raw_capture", receipt.get("raw"))
    if isinstance(record, dict) and isinstance(record.get("artifact"), dict):
        record = record["artifact"]
    if not isinstance(record, dict):
        raise AssertionError("capture contract has no raw media binding")
    return record


def _iter_key_values(value: object):
    """Yield ``(key, value)`` pairs from a JSON object tree."""

    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key), child
            yield from _iter_key_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from _iter_key_values(child)


def _call_contract_loader(module, path: Path, project_root: Path):
    loader = getattr(module, "load_capture_contract")
    parameters = inspect.signature(loader).parameters
    kwargs = {}
    for name in ("project_root", "artifact_root", "root"):
        if name in parameters:
            kwargs[name] = project_root
    return loader(path, **kwargs)


def _call_contract_validator(module, path: Path, payload: dict, project_root: Path):
    validator = getattr(module, "validate_capture_contract")
    parameters = inspect.signature(validator).parameters
    kwargs = {}
    root_name = next(
        (name for name in ("project_root", "artifact_root", "root") if name in parameters),
        None,
    )
    if root_name is not None:
        kwargs[root_name] = project_root
    # The public contract accepts either a path or an already decoded payload;
    # inspect the first parameter name to avoid masking implementation errors.
    first = next(iter(parameters.values()), None)
    if first is not None and first.name in {"path", "contract_path", "capture_path"}:
        first_value = path
    else:
        first_value = payload

    # ``validate_capture_contract`` deliberately keeps artifact_root as a
    # required positional parameter, while loader accepts it as a keyword.
    # Handle both forms without weakening the public contract.
    if root_name is None:
        positional = [first_value]
        remaining = list(parameters.values())[1:]
        if remaining and remaining[0].name in {"project_root", "artifact_root", "root"}:
            positional.append(project_root)
        return validator(*positional, **kwargs)
    return validator(first_value, **kwargs)


def _assert_validation_success(testcase: unittest.TestCase, result: object) -> None:
    """Accept the documented None/bool/result-object success conventions."""

    if result is None:
        return
    if isinstance(result, bool):
        testcase.assertTrue(result, "contract validator returned False")
        return
    for attribute in ("ok", "valid", "is_valid"):
        if hasattr(result, attribute):
            testcase.assertTrue(
                bool(getattr(result, attribute)),
                f"contract validator returned {attribute}=False: {result!r}",
            )
            return
    if isinstance(result, (list, tuple, set, frozenset, dict)):
        testcase.assertFalse(result, f"contract validator returned errors: {result!r}")


def _assert_validation_failure(testcase: unittest.TestCase, callback) -> None:
    try:
        result = callback()
    except (AssertionError, OSError, RuntimeError, ValueError, TypeError, KeyError) as exc:
        # A rejected contract is allowed to be represented as a domain error.
        testcase.assertTrue(str(exc) or exc.__class__.__name__)
        return
    if result is None:
        testcase.fail("invalid capture contract was accepted")
    if isinstance(result, bool):
        testcase.assertFalse(result)
        return
    for attribute in ("ok", "valid", "is_valid"):
        if hasattr(result, attribute):
            testcase.assertFalse(bool(getattr(result, attribute)))
            return
    if isinstance(result, (list, tuple, set, frozenset, dict)):
        testcase.assertTrue(result, "invalid capture contract returned no diagnostics")
        return
    testcase.fail(f"invalid capture contract returned ambiguous result: {result!r}")


class VivhitePromoContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        _add_local_import_paths()
        cls.schema = _read_json(SCHEMA_PATH)
        cls.contract_path = _fixture_contract_path()
        cls.contract = _read_json(cls.contract_path)
        try:
            cls.capture_contract = importlib.import_module(
                "vivhite_promo.capture_contract"
            )
        except ModuleNotFoundError as exc:
            raise AssertionError(
                "the Vivhite promo package must be importable from tools/promo"
            ) from exc

    def test_schema_declares_vivhite_capture_contract(self) -> None:
        self.assertEqual(self.schema.get("type"), "object")
        self.assertEqual(self.schema.get("properties", {}).get("kind", {}).get("const"), "vivhite_promo_capture")
        self.assertEqual(self.schema.get("properties", {}).get("contract_version", {}).get("const"), 1)
        required = set(self.schema.get("required", []))
        self.assertIn("kind", required)
        self.assertIn("contract_version", required)
        self.assertIn("project_context", required)
        self.assertTrue(
            "capture_receipt" in required or {"media", "marks", "clean_spans", "evidence"}.issubset(required),
            f"schema must expose either capture_receipt or direct receipt fields: {sorted(required)}",
        )

    def test_fixture_artifacts_are_relative_and_hash_bound(self) -> None:
        self.assertEqual(self.contract.get("kind"), "vivhite_promo_capture")
        self.assertEqual(self.contract.get("contract_version"), 1)
        self.assertEqual(self.contract.get("mode"), "vivhite-promo")
        self.assertTrue(self.contract.get("producer_id"))
        self.assertTrue(self.contract.get("run_id"))

        records = list(_iter_artifact_records(self.contract))
        self.assertGreaterEqual(len(records), 2, "fixture needs raw media and evidence")
        for record in records:
            relative = Path(str(record["path"]))
            self.assertFalse(relative.is_absolute(), record)
            self.assertNotIn("..", relative.parts, record)
            resolved = (FIXTURE_ROOT / relative).resolve()
            self.assertTrue(
                resolved.is_relative_to(FIXTURE_ROOT.resolve()),
                f"artifact escapes fixture root: {record['path']}",
            )
            self.assertTrue(resolved.is_file(), resolved)
            self.assertEqual(int(record["bytes"]), resolved.stat().st_size, record)
            self.assertEqual(str(record["sha256"]).lower(), _sha256(resolved), record)

    def test_fixture_has_safe_capture_context(self) -> None:
        context = self.contract.get("project_context")
        self.assertIsInstance(context, dict)
        self.assertEqual(context.get("mod_id"), "Vivhite")
        self.assertTrue(context.get("game_version"))
        self.assertTrue(context.get("mod_version"))
        self.assertEqual(str(context.get("renderer")).lower(), "vulkan")
        self.assertEqual(context.get("resolution"), [1920, 1080])
        self.assertEqual(context.get("fps"), 60)
        for field in ("overlays_absent", "loading_absent", "console_absent"):
            self.assertIs(context.get(field), True, f"{field} must be true")

    def test_fixture_does_not_enable_an_overlay_or_debug_surface(self) -> None:
        # Positive/visible switches are forbidden in a capture receipt.  The
        # policy assertions above are intentionally the inverse (`*_absent`),
        # so merely documenting a forbidden surface is not rejected.
        forbidden_positive_keys = {
            "overlay_enabled",
            "overlay_visible",
            "capture_overlay",
            "debug_visible",
            "debug_enabled",
            "console_visible",
            "console_enabled",
            "loading_visible",
            "loading_screen_visible",
            "ai_tab_visible",
        }
        violations = []
        for key, value in _iter_key_values(self.contract):
            if key.casefold() in forbidden_positive_keys and value is not False:
                violations.append(f"{key}={value!r}")
        self.assertFalse(violations, "capture enables forbidden UI: " + ", ".join(violations))

    def test_preset_keeps_capture_policy_fail_closed(self) -> None:
        preset = importlib.import_module("vivhite_promo.preset")
        policy = preset.load_policy(PRESET_PATH)
        self.assertTrue(policy.require_vulkan)
        self.assertTrue(policy.forbid_overlays)
        self.assertTrue(policy.forbid_loading)
        self.assertTrue(policy.forbid_console)
        self.assertTrue(policy.preserve_failed_attempts)

    def test_voice_and_bgm_policy_are_pinned(self) -> None:
        preset = importlib.import_module("vivhite_promo.preset")
        policy = preset.load_policy(PRESET_PATH)
        self.assertEqual(policy.voice, "zh-CN-XiaoxiaoNeural")
        self.assertFalse(policy.include_bgm)
        request = preset.build_narration_request("离线旁白契约测试")
        self.assertEqual(request.voice, "zh-CN-XiaoxiaoNeural")

        for override in (
            {"voice": "zh-CN-YunxiNeural"},
            {"include_bgm": True},
            {"game_version": "0.110.0"},
            {"mod_version": "0.2.0"},
            {"width": 1280},
        ):
            with self.subTest(override=override), tempfile.TemporaryDirectory(
                prefix="vivhite-promo-policy-"
            ) as raw:
                path = Path(raw) / "preset.json"
                payload = _read_json(PRESET_PATH)
                payload.update(override)
                path.write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                with self.assertRaises(preset.VivhitePresetError):
                    preset.load_policy(path)

        adapter_module = importlib.import_module("vivhite_promo.adapter")
        with self.assertRaisesRegex(adapter_module.VivhiteAdapterError, "invalid Vivhite promo policy"):
            adapter_module.VivhiteAdapter(
                policy=preset.VivhitePolicy(include_bgm=True),
                project_root=PROMO_ROOT,
            )
        with self.assertRaises(preset.VivhitePresetError):
            preset.build_narration_request(
                "不应使用替代声线",
                policy=preset.VivhitePolicy(voice="zh-CN-YunxiNeural"),
            )

    def test_variant_manifests_match_storyboard_editorial_lists(self) -> None:
        preset = importlib.import_module("vivhite_promo.preset")
        storyboard = preset.load_storyboard(STORYBOARD_PATH)
        variants = preset.load_variants(
            PROMO_ROOT / "variants",
            storyboard=storyboard,
        )
        self.assertEqual(3, len(variants))
        with tempfile.TemporaryDirectory(prefix="vivhite-promo-variants-") as raw:
            variant_root = Path(raw)
            for source in (PROMO_ROOT / "variants").glob("*.json"):
                (variant_root / source.name).write_text(
                    source.read_text(encoding="utf-8"), encoding="utf-8"
                )
            broken_path = variant_root / "cut-15.json"
            broken = _read_json(broken_path)
            broken["source_shots"] = ["S01-identity", "S03-cough"]
            broken_path.write_text(
                json.dumps(broken, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            with self.assertRaisesRegex(preset.VivhitePresetError, "do not match storyboard"):
                preset.load_variants(variant_root, storyboard=storyboard)

    def test_claim_source_refs_resolve_in_project(self) -> None:
        """Every pending claim starts with an auditable source reference."""

        claims = _read_json(CLAIMS_PATH)
        self.assertIsInstance(claims.get("claims"), list)
        for claim in claims["claims"]:
            self.assertIsInstance(claim, dict)
            claim_id = str(claim.get("claim_id", ""))
            refs = claim.get("source_refs")
            self.assertTrue(refs, claim_id)
            for reference in refs:
                relative = Path(str(reference))
                self.assertFalse(relative.is_absolute(), (claim_id, reference))
                self.assertNotIn("..", relative.parts, (claim_id, reference))
                self.assertTrue((ROOT / relative).exists(), (claim_id, reference))

    def test_ffmpeg_lock_pins_in_place_windows_install(self) -> None:
        lock = _read_json(FFMPEG_LOCK_PATH)
        self.assertEqual(lock.get("format_version"), 1)
        self.assertEqual(lock.get("kind"), "vivhite_promo_ffmpeg_lock")
        self.assertIn("tpad", lock.get("required_filters", []))
        install = lock.get("windows_install")
        self.assertIsInstance(install, dict)
        self.assertEqual(install.get("directory"), "C:/ffmpeg/bin")
        for tool in ("ffmpeg", "ffprobe"):
            with self.subTest(tool=tool):
                entry = install.get(tool)
                self.assertIsInstance(entry, dict)
                self.assertRegex(str(entry.get("file")), r"^[^/\\]+\.exe$")
                self.assertRegex(str(entry.get("sha256")), r"^[A-Fa-f0-9]{64}$")

    def test_loader_and_validator_accept_minimal_fixture(self) -> None:
        loaded = _call_contract_loader(
            self.capture_contract, self.contract_path, FIXTURE_ROOT
        )
        _assert_validation_success(
            self,
            _call_contract_validator(
                self.capture_contract, self.contract_path, self.contract, FIXTURE_ROOT
            ),
        )
        verify = getattr(loaded, "verify_unchanged", None)
        if callable(verify):
            _assert_validation_success(self, verify())

    def test_tampered_raw_media_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="vivhite-promo-contract-") as raw:
            isolated = Path(raw) / "capture"
            self._copy_fixture(isolated)
            contract_path = self._copy_contract(isolated)
            payload = _read_json(contract_path)
            raw_record = _raw_record(payload)
            raw_path = isolated / str(raw_record["path"])
            raw_path.write_bytes(raw_path.read_bytes() + b"tamper")
            _assert_validation_failure(
                self,
                lambda: _call_contract_validator(
                    self.capture_contract, contract_path, payload, isolated
                ),
            )

    def test_path_escape_is_rejected(self) -> None:
        payload = copy.deepcopy(self.contract)
        _raw_record(payload)["path"] = "../outside.mp4"
        with tempfile.TemporaryDirectory(prefix="vivhite-promo-path-") as raw:
            isolated = Path(raw)
            contract_path = isolated / self.contract_path.name
            contract_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            _assert_validation_failure(
                self,
                lambda: _call_contract_validator(
                    self.capture_contract, contract_path, payload, isolated
                ),
            )

    def test_non_monotonic_marks_are_rejected(self) -> None:
        payload = copy.deepcopy(self.contract)
        receipt = _receipt_payload(payload)
        marks = receipt.get("marks", [])
        self.assertGreaterEqual(len(marks), 2)
        # Make the mandatory stop boundary collapse onto the HUD boundary;
        # this is invalid regardless of how many optional intermediate marks
        # the fixture contains.
        stop = next(
            (item for item in marks if item.get("label") == "recording_stop_requested"),
            marks[-1],
        )
        stop["seconds"] = marks[0]["seconds"]
        with tempfile.TemporaryDirectory(prefix="vivhite-promo-marks-") as raw:
            isolated = Path(raw)
            contract_path = isolated / self.contract_path.name
            contract_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            _assert_validation_failure(
                self,
                lambda: _call_contract_validator(
                    self.capture_contract, contract_path, payload, isolated
                ),
            )

    def test_entry_points_and_project_identity_are_declared(self) -> None:
        pyproject = PROMO_ROOT / "pyproject.toml"
        self.assertTrue(pyproject.is_file(), pyproject)
        try:
            import tomllib
        except ModuleNotFoundError:  # pragma: no cover - Python 3.11+ is required.
            self.skipTest("tomllib is unavailable")
        with pyproject.open("rb") as handle:
            document = tomllib.load(handle)
        entry_points = document.get("project", {}).get("entry-points", {})
        adapters = entry_points.get("xar_promo.adapters", {})
        presets = entry_points.get("xar_promo.presets", {})
        composers = entry_points.get("xar_promo.composers", {})
        self.assertIn("vivhite", adapters)
        self.assertIn("vivhite-player-10m", presets)
        self.assertIn("vivhite-player-10m", composers)
        self.assertIn(":", str(adapters["vivhite"]))
        self.assertIn(":", str(presets["vivhite-player-10m"]))
        self.assertIn(":", str(composers["vivhite-player-10m"]))

    def test_validate_only_is_keyword_and_does_not_spawn_processes(self) -> None:
        pipeline = importlib.import_module("vivhite_promo.pipeline")
        compose = getattr(pipeline, "compose", None)
        self.assertIsNotNone(compose, "promo composer must expose compose")
        signature = inspect.signature(compose)
        self.assertIn("validate_only", signature.parameters)

        # This is a source-level safety contract in addition to the runtime
        # smoke test below: validate-only must be an explicit branch, not a
        # value silently ignored by a producer implementation.
        source = inspect.getsource(pipeline)
        self.assertIn("validate_only", source)
        self.assertRegex(source, r"if\s+validate_only|validate_only\s*:")

        calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
        forbidden_names = ("run", "Popen", "call", "check_call", "check_output")
        originals = {name: getattr(subprocess, name) for name in forbidden_names}

        def forbidden_run(*args, **kwargs):
            calls.append((args, kwargs))
            raise AssertionError("validate_only attempted external process")

        for name in forbidden_names:
            setattr(subprocess, name, forbidden_run)
        try:
            # The composer may require xAR's typed config/run objects.  Passing
            # empty mappings is intentional: validation must fail cleanly or
            # return a diagnostic before any external process is touched.
            try:
                compose(
                    {},
                    {},
                    config_path=PROJECT_PATH,
                    run_path=self.contract_path,
                    workdir=FIXTURE_ROOT,
                    validate_only=True,
                )
            except (AssertionError, KeyError, TypeError, ValueError, RuntimeError):
                # Input diagnostics are acceptable; process execution is not.
                pass
            validate_project = getattr(pipeline, "validate_only_project", None)
            self.assertIsNotNone(validate_project)
            report = validate_project(PROJECT_PATH)
            self.assertEqual(report.get("status"), "validated")
            self.assertEqual(report.get("xar_invocation"), "deferred")

            # Exercise the real composer with a valid checked-in config.  It
            # should build an in-memory invocation (ten planned shots) while
            # leaving capture resolution and all external execution deferred.
            preset = importlib.import_module("vivhite_promo.preset")
            adapter = importlib.import_module("vivhite_promo.adapter")
            config = preset.load_project_config(PROJECT_PATH)
            with tempfile.TemporaryDirectory(prefix="vivhite-promo-plan-") as raw:
                invocation = compose(
                    config,
                    {},
                    config_path=PROJECT_PATH,
                    run_path=None,
                    workdir=Path(raw),
                    adapter_factory=adapter.create_adapter,
                    preset_factory=preset.create_preset,
                    validate_only=True,
                )
                self.assertEqual(len(invocation.draft.segments), 10)
                self.assertTrue(
                    all(
                        segment.visual_source.requires_resolution
                        for segment in invocation.draft.segments
                    )
                )
        finally:
            for name, original in originals.items():
                setattr(subprocess, name, original)
        self.assertFalse(calls, "validate_only must not spawn external processes")

    @staticmethod
    def _copy_fixture(destination: Path) -> None:
        destination.mkdir(parents=True, exist_ok=True)
        for source in FIXTURE_ROOT.rglob("*"):
            if source.is_file():
                target = destination / source.relative_to(FIXTURE_ROOT)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(source.read_bytes())

    def _copy_contract(self, destination: Path) -> Path:
        target = destination / self.contract_path.name
        # The original contract paths are relative to FIXTURE_ROOT.  Keep the
        # same layout in the isolated copy.
        target.write_text(self.contract_path.read_text(encoding="utf-8"), encoding="utf-8")
        return target


if __name__ == "__main__":
    unittest.main()
