"""Losslessly archive one store's old, closed runs while the stack stays online.

Dry-run is the default.  --apply writes only archive ZIP/manifest/catalog files
and removes the exact, verified old runs.  Learning state, markdown, review
queues, reset archives and runtime files are untouched.  Full knowledge and
markdown compaction remains an offline operation in brain/compact_knowledge.py.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import sys
import time
import zipfile
from collections import defaultdict
from datetime import date
from pathlib import Path


BRAIN = Path(__file__).resolve().parents[1] / "brain"
if str(BRAIN) not in sys.path:
    sys.path.insert(0, str(BRAIN))

import compact_knowledge as compact  # noqa: E402


SUMMARY_REL = Path("archive") / "history_summary.md"


def plan_run_archive(root: Path, *, archive_before: str,
                     keep_recent: int = compact.DEFAULT_KEEP_RECENT) -> compact.CompactionPlan:
    """Plan a single store without reading mutable learning state or markdown."""
    root = Path(root).resolve()
    options = compact.CompactionOptions(
        archive_before=archive_before, keep_recent=max(0, keep_recent))
    cutoff = date.fromisoformat(archive_before)
    manifest = compact._load_manifest(root)
    archived = compact._archived_run_map(manifest)
    records = compact._scan_runs(root)
    keep = compact._select_working_set(records, options)
    new, duplicates, warnings = [], [], []
    for record in records:
        recorded_date = compact._recorded_run_date(record.summary)
        # Unlike offline compaction this operation is strictly date-bounded.
        if recorded_date is None or recorded_date >= cutoff:
            compact._mark(keep, record, "outside_online_archive_window")
        if record.name in keep:
            continue
        prior = archived.get(record.name)
        if prior is None:
            new.append(record)
        elif prior.get("sha256") == record.sha256:
            duplicates.append(record)
        else:
            compact._mark(keep, record, "archive_name_hash_collision")
            warnings.append(f"kept {record.name}: archive contains a different hash")
    return compact.CompactionPlan(
        root=root, options=options, runs=records, keep_reasons=keep,
        archive_new=new, archive_duplicates=duplicates, markdown=[],
        manifest=manifest, archived_by_name=archived, stats_sha256=None,
        runtime_logs=[], warnings=warnings)


def _build_archive(plan: compact.CompactionPlan) -> tuple[Path, str, dict, dict]:
    """Use shared ZIP verification without snapshotting mutable learning files."""
    selection = {
        "schema_version": compact.SCHEMA_VERSION,
        "operation": "online_closed_run_archive",
        "selection_rules": plan.options.selection_rules(),
        "kept": [{"file": name, "reasons": reasons}
                 for name, reasons in sorted(plan.keep_reasons.items())],
        "archived": [record.summary for record in plan.archive_new],
    }
    members = {compact._safe_zip_member(f"runs/{r.name}"): r.raw
               for r in plan.archive_new}
    members["metadata/selection.json"] = compact._json_bytes(selection)
    fingerprint = hashlib.sha256()
    for name, raw in sorted(members.items()):
        fingerprint.update(name.encode("utf-8") + b"\0")
        fingerprint.update(compact._sha256(raw).encode("ascii") + b"\n")
    batch_id = fingerprint.hexdigest()[:20]
    archive = plan.root / "archive" / f"batch-{batch_id}.zip"
    expected = {name: (compact._sha256(raw), len(raw)) for name, raw in members.items()}
    archive.parent.mkdir(parents=True, exist_ok=True)
    if archive.exists():
        compact._verify_zip(archive, expected)
        return archive, batch_id, selection, members
    temp = archive.with_name(f".{archive.name}.tmp-{os.getpid()}-{time.time_ns()}")
    try:
        with zipfile.ZipFile(temp, "w", compression=zipfile.ZIP_DEFLATED,
                             compresslevel=9, allowZip64=True) as output:
            for name, raw in sorted(members.items()):
                compact._zip_entry(output, name, raw)
        with temp.open("rb+") as handle:
            os.fsync(handle.fileno())
        compact._verify_zip(temp, expected)
        os.replace(temp, archive)
        compact._verify_zip(archive, expected)
    finally:
        temp.unlink(missing_ok=True)
    return archive, batch_id, selection, members


def _publication_catalog(plan: compact.CompactionPlan, manifest: dict) -> bytes:
    """Publish ZIP locations before removing sources, with no second full scan.

    Live sources remain authoritative to consumers.  Their planned summaries
    are just a cache; files created during compression are found by consumers'
    normal active-directory scan.  The selected rows must already use ZIP
    storage so readers never observe a missing source without its replacement.
    """
    archived = compact._archived_run_map(manifest)
    selected = {r.name for r in plan.archive_new + plan.archive_duplicates}
    entries = {}
    for name, row in archived.items():
        entries[name] = {key: value for key, value in row.items() if key != "archive"}
        entries[name]["storage"] = {
            "kind": "zip", "archive": row["archive"], "member": row["member"]}
    for record in plan.runs:
        if record.name not in selected:
            entries[record.name] = dict(
                record.summary,
                storage={"kind": "active", "path": f"runs/{record.name}"})
    header = {
        "schema_version": compact.SCHEMA_VERSION,
        "description": "Searchable summaries; raw archived runs remain exact in ZIP.",
    }
    return b"".join(compact._json_bytes(row, indent=None)
                    for row in [header, *(entries[name] for name in sorted(entries))])


def _manifest_bytes(root: Path) -> bytes | None:
    try:
        return (root / compact.MANIFEST_REL).read_bytes()
    except FileNotFoundError:
        return None


def _history_summary(catalog: bytes, *, archive_before: str, root: Path | None = None) -> bytes:
    """Produce a deterministic evidence index, never strategy or learning stats."""
    groups = defaultdict(list)
    for line in catalog.decode("utf-8").splitlines():
        row = json.loads(line)
        if "file" not in row:
            continue
        recorded_date = compact._recorded_run_date(row)
        groups[recorded_date.isoformat() if recorded_date else "unknown"].append(row)
    lines = [
        "# 对局历史证据索引", "",
        "这是原始记录的日期索引，不是当前版本能力评估，也不是在线学习统计。",
        f"本次归档边界：记录内 started_at 的日期严格早于 {archive_before}；近期局和异常局仍保留。",
        "日期不能证明代码版本；缺失版本、日期、编号或其他字段时不猜测。",
        "最高楼层取 catalog 的原始 run/decision 楼层投影，不加胜利 50 分。",
        "胜利列按记录真值计数，可能包括被排除局；已闭合只统计 in_progress=false。", "",
        "| 日期 | 文件 | ZIP | 已闭合 | 进行中 | 排除标记 | 胜利 | 最高楼层 | run_number 范围 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for day, rows in sorted(groups.items()):
        numbers = [row["run_number"] for row in rows
                   if type(row.get("run_number")) is int]
        floors = [row["floor"] for row in rows if type(row.get("floor")) is int]
        run_range = f"{min(numbers)}–{max(numbers)}" if numbers else "unknown"
        if numbers and len(numbers) < len(rows):
            run_range += " (含 unknown)"
        excluded = sum(any(row.get(key) is True for key in (
            "human_assisted", "excluded_from_learning", "orphaned")) for row in rows)
        values = [
            day, len(rows), sum(row.get("storage", {}).get("kind") == "zip" for row in rows),
            sum(row.get("in_progress") is False for row in rows),
            sum(row.get("in_progress") is True for row in rows), excluded,
            sum(row.get("victory") is True for row in rows),
            max(floors) if floors else "unknown", run_range,
        ]
        lines.append("| " + " | ".join(map(str, values)) + " |")
    example = next((row["file"] for rows in groups.values() for row in rows
                    if row.get("storage", {}).get("kind") == "zip"), "FILENAME")
    store = str(root) if root is not None else "PATH"
    lines.extend([
        "", "未知字段不计入对应数字列；按文件统计，不合并可能重复的 run_id。",
        "ZIP 内保留原 JSON 的全部字节；摘要只用于检索。当前活动记录可能在索引生成后继续变化。",
        "", "- [完整 manifest](manifest.json)", "- [逐文件 catalog](run_catalog.jsonl)",
        "", "从仓库根读取一条原始记录（替换 --show-run 参数可检索 catalog 中的其他 file）：",
        "", "```powershell",
        f'python sts2-ascend/brain/compact_knowledge.py --knowledge-dir "{store}" --show-run "{example}"',
        "```", "",
    ])
    return "\n".join(lines).encode("utf-8")


def _verify_run_sources(plan: compact.CompactionPlan) -> None:
    for record in plan.archive_new + plan.archive_duplicates:
        if not record.path.is_file() or compact._sha256(record.path.read_bytes()) != record.sha256:
            raise RuntimeError(f"run changed during online archiving: {record.path}")


def apply_run_archive(root: Path, *, archive_before: str,
                      keep_recent: int = compact.DEFAULT_KEEP_RECENT,
                      lock_timeout: float = 10.0) -> dict:
    """Prepare outside the repository lock; publish then remove verified sources.

    A failure preserves published ZIP evidence.  Re-running recovers duplicate
    sources after a manifest/catalog publication or partial deletion failure.
    """
    import autogit

    root = Path(root).resolve()
    with compact._compaction_lock(root):
        original_manifest = _manifest_bytes(root)
        plan = plan_run_archive(root, archive_before=archive_before, keep_recent=keep_recent)
        if not (plan.archive_new or plan.archive_duplicates):
            return {"changed": False, "idempotent_noop": True,
                    "archived_runs": 0, "removed_duplicate_runs": 0}
        manifest = copy.deepcopy(plan.manifest)
        archive = None
        batch_id = None
        if plan.archive_new:
            archive, batch_id, selection, members = _build_archive(plan)
            batch = compact._manifest_batch(plan, archive, batch_id, selection, members)
            batch["operation"] = "online_closed_run_archive"
            manifest["batches"].append(batch)
        compact._verify_archived_duplicates(plan)
        catalog = _publication_catalog(plan, manifest)
        summary = _history_summary(catalog, archive_before=archive_before, root=root)
        # Coordinate publication with the existing repository transactions.
        # Compression and ZIP validation never hold this lock.  Old closed
        # runs are immutable in normal operation; run saves do not take it.
        with autogit.repository_lock(timeout=max(0.0, lock_timeout)):
            if _manifest_bytes(root) != original_manifest:
                raise RuntimeError("archive manifest changed during online archiving; retry")
            _verify_run_sources(plan)
            if plan.archive_new:
                compact._atomic_write(root / compact.MANIFEST_REL, compact._json_bytes(manifest))
            compact._write_if_changed(root / compact.CATALOG_REL, catalog)
            compact._write_if_changed(root / SUMMARY_REL, summary)
            for record in plan.archive_new + plan.archive_duplicates:
                if compact._sha256(record.path.read_bytes()) != record.sha256:
                    raise RuntimeError(f"run changed before removal: {record.path}")
                record.path.unlink()
        return {
            "changed": True, "idempotent_noop": False,
            "operation": "online_closed_run_archive", "knowledge_dir": str(root),
            "batch_id": batch_id, "archive": str(archive) if archive else None,
            "history_summary": str(root / SUMMARY_REL),
            "archive_bytes": archive.stat().st_size if archive else 0,
            "archived_runs": len(plan.archive_new),
            "removed_duplicate_runs": len(plan.archive_duplicates),
            "removed_source_bytes": sum(r.size for r in plan.archive_new + plan.archive_duplicates),
            "kept_runs": len(plan.kept), "warnings": plan.warnings,
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--knowledge-dir", type=Path,
                        default=BRAIN.parent / "knowledge",
                        help="one knowledge store; nested profiles are not traversed")
    parser.add_argument("--archive-before", required=True,
                        type=compact._archive_before_date, metavar="YYYY-MM-DD")
    parser.add_argument("--keep-recent", type=int, default=compact.DEFAULT_KEEP_RECENT)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    kwargs = {"archive_before": args.archive_before, "keep_recent": max(0, args.keep_recent)}
    if args.apply:
        result = apply_run_archive(args.knowledge_dir, **kwargs)
    else:
        result = compact.plan_report(plan_run_archive(args.knowledge_dir, **kwargs))
        result["operation"] = "online_closed_run_archive"
        result["scope"] = "single store; old closed runs only; no learning/markdown/runtime changes"
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
