'''Frozen, queue-independent sts2-ascend review-model evaluator.'''
from __future__ import annotations

import argparse
import codecs
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import sys
import tarfile
import threading
import time
from typing import Callable, Sequence


ASCEND_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ASCEND_ROOT.parent
DEFAULT_OUTPUT_ROOT = ASCEND_ROOT / 'knowledge' / 'code_backups' / 'review_eval'
DEFAULT_TIMEOUT_SEC = 8 * 60 * 60
DEFAULT_SELFCHECK_TIMEOUT_SEC = 30 * 60
DEFAULT_STALL_TIMEOUT_SEC = 30 * 60


@dataclass(frozen=True)
class BackendSpec:
    key: str
    runner: str
    model: str
    variant: str = ''
    reasoning_effort: str = ''
    approve_for_me: bool = False
    sandbox: str = 'workspace-write'


@dataclass(frozen=True)
class EvalRequest:
    source_repo: Path
    baseline: str
    prompt_path: Path
    output_root: Path
    case_id: str
    backend: BackendSpec
    prompt_provenance_path: Path | None = None
    validator_revision: str = 'HEAD'
    timeout_sec: float = DEFAULT_TIMEOUT_SEC
    stall_timeout_sec: float = DEFAULT_STALL_TIMEOUT_SEC
    selfcheck_timeout_sec: float = DEFAULT_SELFCHECK_TIMEOUT_SEC
    selfcheck_command: tuple[str, ...] = (
        sys.executable, '-B', 'sts2-ascend/brain/selfcheck.py',
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='milliseconds')


def _slug(value: str, *, fallback: str = 'eval') -> str:
    cleaned = re.sub(r'[^A-Za-z0-9._-]+', '-', value).strip('-._')
    return cleaned[:96] or fallback


def _write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + '\n',
        encoding='utf-8',
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()

def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_batch_runs(values: Sequence[int]) -> tuple[int, ...]:
    runs: set[int] = set()
    for value in values:
        try:
            run = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f'invalid run number: {value!r}') from exc
        if run <= 0:
            raise ValueError('run numbers must be positive')
        runs.add(run)
    if not runs:
        raise ValueError('at least one batch run is required')
    return tuple(sorted(runs))


def parse_batch_runs(value: str) -> tuple[int, ...]:
    '''Parse comma-separated runs and inclusive start-end ranges.'''
    parsed: list[int] = []
    for token in (item.strip() for item in value.split(',')):
        if not token:
            continue
        match = re.fullmatch(r'(\d+)\s*(?:-|~)\s*(\d+)', token)
        if match:
            start, end = (int(part) for part in match.groups())
            if end < start:
                raise ValueError(f'run range is descending: {token}')
            parsed.extend(range(start, end + 1))
        elif token.isdigit():
            parsed.append(int(token))
        else:
            raise ValueError(f'invalid run selection: {token!r}')
    return _canonical_batch_runs(parsed)


def _probe_version(command: Sequence[str], *, timeout_sec: float = 30) -> dict:
    started_at = _utc_now()
    try:
        result = subprocess.run(
            list(command), check=False, capture_output=True, text=True,
            encoding='utf-8', errors='replace', timeout=timeout_sec,
        )
        return {
            'status': 'captured', 'command': list(command),
            'started_at': started_at, 'returncode': result.returncode,
            'stdout': result.stdout.strip()[:4000],
            'stderr': result.stderr.strip()[:4000],
            'stdout_sha256': _sha256_bytes(result.stdout.encode('utf-8')),
            'stderr_sha256': _sha256_bytes(result.stderr.encode('utf-8')),
        }
    except (OSError, subprocess.SubprocessError) as exc:
        return {

            'status': 'unavailable', 'command': list(command),
            'started_at': started_at,
            'error': {'type': type(exc).__name__, 'message': str(exc)},
        }


def parse_backend_key(key: str) -> BackendSpec:
    '''Parse a reproducible backend identity; never infer or fall through.'''
    value = key.strip()
    if value.startswith('opencode:'):
        body = value.removeprefix('opencode:')
        model, separator, variant = body.rpartition('@')
        if not separator:
            model, variant = body, ''
        if not model.strip():
            raise ValueError('opencode backend key is missing its model')
        return BackendSpec(
            value, 'opencode', model.strip(), variant=variant.strip())
    if value.startswith('codex:'):
        body = value.removeprefix('codex:')
        auto_review = body.endswith(':auto-review')
        if auto_review:
            body = body.removesuffix(':auto-review')
        model, separator, reasoning = body.rpartition('@')
        if not separator:
            model, reasoning = body, ''
        if not model.strip():
            raise ValueError('codex backend key is missing its model')
        return BackendSpec(
            value, 'codex', model.strip(),
            reasoning_effort=reasoning.strip(), approve_for_me=auto_review,
        )
    raise ValueError(
        'unsupported backend key; use opencode:<provider/model>[@variant] or '
        'codex:<model>[@reasoning][:auto-review]'
    )


def _git(
    repo: Path,
    args: Sequence[str],
    *,
    text: bool = True,
    check: bool = True,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        ['git', *args], cwd=str(repo), check=check, capture_output=True,
        text=text, encoding='utf-8' if text else None,
        errors='replace' if text else None,
    )


def resolve_baseline(source_repo: Path, revision: str) -> str:
    result = _git(
        source_repo, ['rev-parse', '--verify', f'{revision}^{{commit}}'])
    return result.stdout.strip()


def create_isolated_repository(
    source_repo: Path,
    source_baseline: str,
    destination: Path,
) -> str:
    '''Create a history-free repo without remotes, hardlinks or shared index.'''
    destination.mkdir(parents=True, exist_ok=False)
    archive_path = destination.parent / 'baseline.tar'
    _git(source_repo, [
        'archive', '--format=tar', '-o', str(archive_path), source_baseline,
    ])
    try:
        with tarfile.open(archive_path, mode='r:') as archive:
            archive.extractall(destination, filter='data')
    finally:
        archive_path.unlink(missing_ok=True)

    _git(destination, ['init', '--quiet'])
    _git(destination, ['config', 'core.autocrlf', 'false'])
    _git(destination, ['config', 'user.name', 'sts2 review evaluator'])
    _git(destination, ['config', 'user.email', 'review-eval@localhost'])
    _git(destination, ['add', '-A'])
    _git(destination, [
        'commit', '--quiet', '--no-verify', '-m', 'frozen evaluation baseline',
    ])
    local_baseline = _git(destination, ['rev-parse', 'HEAD']).stdout.strip()
    remotes = _git(destination, ['remote']).stdout.strip()
    if remotes:
        raise RuntimeError(
            f'isolated evaluation repository unexpectedly has remotes: {remotes}')
    return local_baseline


def create_validator_snapshot(
    source_repo: Path,
    revision: str,
    destination: Path,
) -> str:
    '''Freeze the current production validator for a whole A/B campaign.'''
    baseline = resolve_baseline(source_repo, revision)
    destination.mkdir(parents=True, exist_ok=False)
    archive_path = destination.parent / 'validator.tar'
    archived = _git(
        source_repo,
        [
            'archive', '--format=tar', '-o', str(archive_path),
            baseline, 'sts2-ascend/brain',
        ],
        check=False,
    )
    if archived.returncode != 0:
        raise RuntimeError(
            'validator snapshot archive failed: '
            + archived.stderr.strip()[:1000])
    try:
        with tarfile.open(archive_path, mode='r:') as archive:
            archive.extractall(destination, filter='data')
    finally:
        archive_path.unlink(missing_ok=True)
    required = (
        'sts2-ascend/brain/llm_review.py',
        'sts2-ascend/brain/review_runners.py',
        'sts2-ascend/brain/lifecycle.py',
        'sts2-ascend/brain/autogit.py',
    )
    missing = [
        relative for relative in required
        if not (destination / relative).is_file()
    ]
    if missing:
        raise FileNotFoundError(
            'validator snapshot is incomplete: ' + ', '.join(missing))
    return baseline


def _git_path_oid(repo: Path, baseline: str, relative: str) -> str:
    result = _git(
        repo, ['rev-parse', '--verify', f'{baseline}:{relative}'],
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else ''


def _versioned_file_record(
    source_repo: Path,
    source_baseline: str,
    snapshot: Path,
    relative: str,
) -> dict:
    path = snapshot / relative
    record = {
        'path': relative,
        'git_object_id': _git_path_oid(
            source_repo, source_baseline, relative),
        'present': path.is_file(),
    }
    if path.is_file():
        record.update({'bytes': path.stat().st_size, 'sha256': _sha256(path)})
    return record


def _extract_prompt_packet(prompt: str) -> dict:
    fence = re.escape(chr(96) * 3)
    marker = re.search(fence + r'json\s*\n(.*?)\n' + fence, prompt, re.DOTALL)
    if not marker:
        raise ValueError('reconstructed prompt has no first fenced JSON packet')
    packet = json.loads(marker.group(1))
    if not isinstance(packet, dict):
        raise ValueError('reconstructed prompt packet is not an object')
    return packet


def _create_generator_repository(
    source_repo: Path,
    source_baseline: str,
    destination: Path,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    clone = _git(source_repo, [
        'clone', '--quiet', '--no-hardlinks', '--no-checkout',
        str(source_repo), str(destination),
    ], check=False)
    if clone.returncode != 0:
        raise RuntimeError(
            'prompt generator clone failed: ' + clone.stderr.strip()[:1000])
    _git(destination, ['config', 'core.autocrlf', 'false'])
    _git(destination, ['config', 'core.eol', 'lf'])
    checkout = _git(
        destination, ['checkout', '--quiet', '--detach', source_baseline],
        check=False,
    )
    if checkout.returncode != 0:
        raise RuntimeError(
            'prompt generator checkout failed: '
            + checkout.stderr.strip()[:1000])
    _git(destination, ['remote', 'remove', 'origin'], check=False)
    if _git(destination, ['remote']).stdout.strip():
        raise RuntimeError('prompt generator snapshot unexpectedly has remotes')


def reconstruct_prompt_bundle(
    source_repo: Path,
    revision: str,
    batch_runs: Sequence[int],
    destination: Path,
    *,
    python_binary: str = sys.executable,
) -> tuple[Path, dict]:
    '''Build one frozen prompt reusable by paired backends.

    This is a deterministic reconstruction, not a claim that the bytes were
    captured from the historical production review.
    '''
    source_repo = source_repo.resolve()
    destination = destination.resolve()
    runs = _canonical_batch_runs(batch_runs)
    destination.mkdir(parents=True, exist_ok=False)
    snapshot = destination / 'generator_snapshot'
    prompt_path = destination / 'prompt.md'
    stdout_path = destination / 'generator.stdout.log'
    stderr_path = destination / 'generator.stderr.log'
    provenance: dict = {
        'schema_version': 1,
        'kind': 'deterministic_baseline_reconstruction',
        'status': 'initializing',
        'created_at': _utc_now(),
        'evaluator': {
            'path': Path(__file__).resolve().name,
            'sha256': _sha256(Path(__file__).resolve()),
            'python_executable': sys.executable,
            'python_version': sys.version,
        },
        'source_repo': str(source_repo),
        'requested_baseline': revision,
        'source_baseline': None,
        'batch_runs': list(runs),
        'historical_byte_original': False,
        'statement': (
            'Deterministically reconstructed from the selected commit and runs; '
            'not the historical byte-for-byte production prompt.'
        ),
        'queue_independent': True,
        'live_brain_accessed': False,
        'excluded_live_state': [
            'sts2-ascend/.runtime',
            'sts2-ascend/knowledge/review_queue.json',
            'sts2-ascend/knowledge/review_active.flag',
            'sts2-ascend/knowledge/pending_restart.json',
            'sts2-ascend/knowledge/preferred_model_state.json',
        ],
        'errors': [],
    }
    try:
        source_baseline = resolve_baseline(source_repo, revision)
        provenance['source_baseline'] = source_baseline
        provenance['git_version'] = _probe_version(['git', '--version'])
        _create_generator_repository(
            source_repo, source_baseline, snapshot)

        relatives = (
            'sts2-ascend/brain/llm_review.py',
            'sts2-ascend/brain/config.json',
            'sts2-ascend/brain/knowledge.py',
            'sts2-ascend/brain/native_knowledge.py',
        )
        inputs = [
            _versioned_file_record(
                source_repo, source_baseline, snapshot, relative)
            for relative in relatives
        ]
        if not all(item['present'] for item in inputs[:3]):
            missing = [item['path'] for item in inputs[:3]
                       if not item['present']]
            raise FileNotFoundError(
                'baseline prompt generator inputs missing: ' + ', '.join(missing))
        provenance['generator_inputs'] = inputs
        provenance['knowledge_tree_git_object_id'] = _git_path_oid(
            source_repo, source_baseline, 'sts2-ascend/knowledge')

        evidence: list[dict] = []
        run_root = snapshot / 'sts2-ascend' / 'knowledge' / 'runs'
        if run_root.is_dir():
            for path in sorted(run_root.glob('*.json')):
                try:
                    payload = json.loads(path.read_text(encoding='utf-8'))
                    run_number = int(payload.get('run_number') or 0)
                except (OSError, ValueError, TypeError, json.JSONDecodeError):
                    continue
                if run_number in runs:
                    relative = path.relative_to(snapshot).as_posix()
                    evidence.append({
                        'run_number': run_number,
                        **_versioned_file_record(
                            source_repo, source_baseline, snapshot, relative),
                    })
        provenance['direct_run_evidence'] = evidence

        for relative in provenance['excluded_live_state']:
            target = snapshot / relative
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink(missing_ok=True)

        helper = (
            'import json,sys; from pathlib import Path; '
            'root=Path.cwd(); brain=root/"sts2-ascend"/"brain"; '
            'sys.path.insert(0,str(brain)); '
            'from knowledge import Knowledge; import llm_review; '
            'raw=json.loads((brain/"config.json").read_text(encoding="utf-8")); '
            'cfg=raw.get("llm",raw); '
            'know=Knowledge(root/"sts2-ascend"/"knowledge"); '
            'runs=json.loads(sys.argv[1]); '
            'prompt=llm_review.build_prompt(know,cfg,batch_runs=runs); '
            'Path(sys.argv[2]).write_text(prompt,encoding="utf-8")'
        )
        command = [
            python_binary, '-B', '-c', helper,
            json.dumps(list(runs)), str(prompt_path),
        ]
        provenance['generator_command'] = [
            python_binary, '-B', '-c', '<embedded-baseline-generator>',
            json.dumps(list(runs)), 'prompt.md',
        ]
        generated = subprocess.run(
            command, cwd=str(snapshot), check=False, capture_output=True,
            text=True, encoding='utf-8', errors='replace',
            env=evaluation_environment(), timeout=15 * 60,
        )
        stdout_path.write_text(generated.stdout, encoding='utf-8')
        stderr_path.write_text(generated.stderr, encoding='utf-8')
        provenance['generator_result'] = {
            'returncode': generated.returncode,
            'stdout_sha256': _sha256(stdout_path),
            'stderr_sha256': _sha256(stderr_path),
        }
        if generated.returncode != 0 or not prompt_path.is_file():
            raise RuntimeError(
                'baseline prompt generator failed: '
                + generated.stderr.strip()[:1000])
        packet = _extract_prompt_packet(
            prompt_path.read_text(encoding='utf-8'))
        scope = packet.get('run_evidence_scope') or {}
        exact = sorted(int(value) for value in (scope.get('exact') or []))
        missing = sorted(int(value) for value in (scope.get('missing') or []))
        if exact != list(runs) or missing:
            raise ValueError(
                f'baseline prompt did not resolve exact runs: '
                f'exact={exact}, missing={missing}')
        provenance['run_evidence_scope'] = {
            'exact': exact, 'missing': missing,
        }
        provenance['prompt'] = {
            'path': prompt_path.name,
            'bytes': prompt_path.stat().st_size,
            'sha256': _sha256(prompt_path),
        }
        provenance['status'] = 'ready'
    except (
        OSError, ValueError, RuntimeError, subprocess.SubprocessError,
    ) as exc:
        provenance['status'] = 'failed'
        provenance['errors'].append({
            'stage': 'prompt_reconstruction',
            'type': type(exc).__name__,
            'message': str(exc),
        })
    finally:
        provenance['finished_at'] = _utc_now()
        _write_json(destination / 'prompt_provenance.json', provenance)
        if provenance['status'] == 'ready' and snapshot.is_dir():
            shutil.rmtree(snapshot)
    return destination, provenance


def _validate_prompt_provenance(
    provenance: object,
    prompt: Path,
    source_baseline: str,
) -> tuple[int, ...]:
    if not isinstance(provenance, dict):
        raise ValueError('prompt provenance must be an object')
    if provenance.get('kind') != 'deterministic_baseline_reconstruction':
        raise ValueError('prompt provenance kind is not a reconstruction bundle')
    if provenance.get('status') != 'ready':
        raise ValueError('prompt bundle is not ready')
    if provenance.get('historical_byte_original') is not False:
        raise ValueError('prompt bundle lacks reconstruction provenance')
    if provenance.get('source_baseline') != source_baseline:
        raise ValueError('prompt bundle baseline does not match evaluation baseline')
    try:
        runs = _canonical_batch_runs(provenance.get('batch_runs') or [])
    except (TypeError, ValueError) as exc:
        raise ValueError('prompt provenance has invalid batch_runs') from exc
    scope = provenance.get('run_evidence_scope')
    if not isinstance(scope, dict):
        raise ValueError('prompt provenance has no run_evidence_scope')
    try:
        exact = _canonical_batch_runs(scope.get('exact') or [])
    except (TypeError, ValueError) as exc:
        raise ValueError('prompt provenance has invalid exact run scope') from exc
    if exact != runs or list(scope.get('missing') or []):
        raise ValueError('prompt provenance run scope is incomplete')
    prompt_record = provenance.get('prompt')
    if not isinstance(prompt_record, dict):
        raise ValueError('prompt provenance prompt record must be an object')
    expected = str(prompt_record.get('sha256') or '')
    if not expected or _sha256(prompt) != expected:
        raise ValueError('prompt bundle SHA-256 verification failed')
    packet = _extract_prompt_packet(prompt.read_text(encoding='utf-8'))
    packet_scope = packet.get('run_evidence_scope')
    if not isinstance(packet_scope, dict):
        raise ValueError('prompt packet has no run_evidence_scope')
    try:
        packet_exact = _canonical_batch_runs(packet_scope.get('exact') or [])
    except (TypeError, ValueError) as exc:
        raise ValueError('prompt packet has invalid exact run scope') from exc
    if packet_exact != runs or list(packet_scope.get('missing') or []):
        raise ValueError('prompt packet run scope does not match provenance')
    return runs


def load_prompt_bundle(
    bundle: Path,
    source_repo: Path,
    revision: str,
) -> tuple[Path, Path, dict]:
    '''Verify a prepared prompt before sharing it across paired evaluations.'''
    bundle = bundle.resolve()
    prompt = bundle / 'prompt.md'
    provenance_path = bundle / 'prompt_provenance.json'
    provenance = json.loads(provenance_path.read_text(encoding='utf-8'))
    baseline = resolve_baseline(source_repo.resolve(), revision)
    _validate_prompt_provenance(provenance, prompt, baseline)
    return prompt, provenance_path, provenance

def _artifact_hashes(result_dir: Path) -> dict[str, dict]:
    evidence: dict[str, dict] = {}
    for path in sorted(result_dir.iterdir()):
        if (not path.is_file()
                or path.name in {'manifest.json', 'manifest.partial.json'}):
            continue
        evidence[path.name] = {
            'bytes': path.stat().st_size,
            'sha256': _sha256(path),
        }
    return evidence

def find_runner_binary(spec: BackendSpec) -> str:
    binary = shutil.which(spec.runner)
    if not binary:
        raise FileNotFoundError(
            f'{spec.runner} executable is not available on PATH')
    return binary


def build_provider_command(
    spec: BackendSpec,
    binary: str,
    workdir: Path,
    prompt_path: Path,
    title: str,
) -> tuple[list[str], str | None]:
    rel_prompt = 'sts2-ascend/knowledge/review_prompt_latest.md'
    short_prompt = (
        '\u4f60\u4f4d\u4e8e\u5bbf\u4e3b\u521b\u5efa\u7684\u9694\u79bb clone\u3002'
        f'\u8bf7\u5b8c\u6574\u9605\u8bfb {rel_prompt}\uff0c'
        '\u53ea\u53ef\u5728\u5f53\u524d\u5de5\u4f5c\u76ee\u5f55\u5185'
        '\u4f7f\u7528\u76f8\u5bf9\u8def\u5f84\uff1b'
        '\u7981\u6b62\u7edd\u5bf9\u8def\u5f84\u3001.. '
        '\u9003\u9038\u6216\u8bbf\u95ee\u5176\u4ed6\u5de5\u4f5c\u533a\u3002'
        '\u4e25\u683c\u6309\u4efb\u52a1\u4e66\u6267\u884c\u3002'
    )
    if spec.runner == 'codex':
        command = [binary, 'exec', '--model', spec.model]
        if spec.reasoning_effort:
            command += [
                '-c',
                'model_reasoning_effort=' + json.dumps(spec.reasoning_effort),
            ]
        if spec.approve_for_me:
            command.append('--approve-for-me')
        else:
            command += ['--sandbox', spec.sandbox]
        command += [
            '--json', '--ephemeral', '--color', 'never',
            '-C', str(workdir), short_prompt,
        ]
        return command, None
    if spec.runner == 'opencode':
        command = [
            binary, 'run', '--model', spec.model,
            '--format', 'json', '--thinking',
        ]
        if spec.variant:
            command += ['--variant', spec.variant]
        command += [
            '--title', title, '--dir', str(workdir), '--auto',
            short_prompt,
        ]
        return command, None
    raise ValueError(f'unsupported runner: {spec.runner}')


def evaluation_environment() -> dict[str, str]:
    env = dict(os.environ)
    for name in list(env):
        if name.startswith('STS2_ASCEND_'):
            del env[name]
    env['STS2_ASCEND_EVAL_MODE'] = '1'
    env['STS2_ASCEND_DISABLE_VIEWER'] = '1'
    return env


def _terminate_process_tree(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    if os.name == 'nt':
        subprocess.run(
            ['taskkill.exe', '/PID', str(proc.pid), '/T', '/F'],
            check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    else:
        try:
            os.killpg(proc.pid, 15)
            proc.wait(timeout=5)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            if proc.poll() is None:
                os.killpg(proc.pid, 9)


def _creation_options() -> dict[str, object]:
    if os.name == 'nt':
        return {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP}
    return {'start_new_session': True}


class _ProviderRecorder:
    def __init__(self, runner: str) -> None:
        self.runner = runner
        self.started = time.monotonic()
        self.lock = threading.Lock()
        self.raw_chunk_times: list[float] = []
        self.output_times: list[float] = []
        self.stdout_times: list[float] = []
        self.raw_bytes = 0
        self.raw_chunks = 0
        self.stdout_raw_bytes = 0
        self.stdout_raw_chunks = 0
        self.line_count = 0
        self.stdout_line_count = 0
        self.stderr_line_count = 0
        self.json_event_count = 0
        self.non_json_stdout_lines = 0
        self.error_event_count = 0
        self.first_model_work_after_sec: float | None = None
        self.usage: dict[str, int] = {}
        self.final_response = ''

    def _consume_event(self, line: str, elapsed: float) -> None:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            self.non_json_stdout_lines += 1
            return
        if not isinstance(event, dict):
            self.non_json_stdout_lines += 1
            return
        self.json_event_count += 1
        event_type = str(event.get('type') or '')
        model_work = False
        if self.runner == 'codex':
            raw_item = event.get('item')
            item = raw_item if isinstance(raw_item, dict) else {}
            item_type = str(item.get('type') or '')
            model_work = event_type.startswith('item.') and item_type in {
                'agent_message', 'reasoning', 'command_execution',
                'file_change', 'mcp_tool_call', 'web_search', 'plan_update',
            }
            if event_type == 'turn.completed':
                raw_usage = event.get('usage')
                if isinstance(raw_usage, dict):
                    self.usage = {
                        str(key): int(value)
                        for key, value in raw_usage.items()
                        if isinstance(value, int) and not isinstance(value, bool)
                    }
            if event_type in {'turn.failed', 'error'}:
                self.error_event_count += 1
            if event_type == 'item.completed' and item_type == 'agent_message':
                self.final_response = str(item.get('text') or '')
        else:
            raw_part = event.get('part')
            part = raw_part if isinstance(raw_part, dict) else {}
            part_type = str(part.get('type') or event_type)
            model_work = part_type in {
                'text', 'reasoning', 'tool', 'tool-call', 'tool_call',
                'tool-use', 'tool-result', 'tool_result', 'patch',
            }
            if part_type == 'step-finish':
                raw_tokens = part.get('tokens')
                if isinstance(raw_tokens, dict):
                    self.usage = {
                        str(key): int(value)
                        for key, value in raw_tokens.items()
                        if isinstance(value, int) and not isinstance(value, bool)
                    }
            if part_type == 'error' or event_type == 'error':
                self.error_event_count += 1
            if part_type == 'text' and isinstance(part.get('text'), str):
                self.final_response = part['text']
        if model_work and self.first_model_work_after_sec is None:
            self.first_model_work_after_sec = elapsed

    def record_raw(self, stream_name: str, size: int) -> None:
        elapsed = max(0.0, time.monotonic() - self.started)
        with self.lock:
            self.raw_chunk_times.append(elapsed)
            self.raw_bytes += size
            self.raw_chunks += 1
            if stream_name == 'stdout':
                self.stdout_raw_bytes += size
                self.stdout_raw_chunks += 1

    def record(self, stream_name: str, line: str, transcript_handle) -> None:
        elapsed = max(0.0, time.monotonic() - self.started)
        with self.lock:
            self.line_count += 1
            self.output_times.append(elapsed)
            if stream_name == 'stdout':
                self.stdout_line_count += 1
                self.stdout_times.append(elapsed)
                self._consume_event(line, elapsed)
            else:
                self.stderr_line_count += 1
            transcript_handle.write(json.dumps({
                'at': _utc_now(),
                'after_sec': round(elapsed, 6),
                'stream': stream_name,
                'text': line,
            }, ensure_ascii=False) + chr(10))
            transcript_handle.flush()

    def raw_silence_sec(self) -> float:
        elapsed = max(0.0, time.monotonic() - self.started)
        with self.lock:
            last = max(self.raw_chunk_times) if self.raw_chunk_times else 0.0
        return max(0.0, elapsed - last)

    @staticmethod
    def _max_gap(times: list[float], ended: float) -> float:
        points = [0.0, *times, ended]
        return max(
            (right - left for left, right in zip(points, points[1:])),
            default=ended,
        )

    def metrics(self, ended: float) -> dict:
        with self.lock:
            raw_times = sorted(self.raw_chunk_times)
            line_times = sorted(self.output_times)
            stdout_times = sorted(self.stdout_times)
        return {
            'raw_bytes': self.raw_bytes,
            'raw_chunks': self.raw_chunks,
            'stdout_raw_bytes': self.stdout_raw_bytes,
            'stdout_raw_chunks': self.stdout_raw_chunks,
            'line_count': self.line_count,
            'stdout_line_count': self.stdout_line_count,
            'stderr_line_count': self.stderr_line_count,
            'json_event_count': self.json_event_count,
            'non_json_stdout_lines': self.non_json_stdout_lines,
            'error_event_count': self.error_event_count,
            'first_raw_byte_after_sec':
                raw_times[0] if raw_times else None,
            'first_output_after_sec':
                line_times[0] if line_times else None,
            'first_stdout_after_sec':
                stdout_times[0] if stdout_times else None,
            'first_model_work_after_sec': self.first_model_work_after_sec,
            'max_raw_silence_sec': self._max_gap(raw_times, ended),
            'max_output_gap_sec': self._max_gap(line_times, ended),
            'max_stdout_gap_sec': self._max_gap(stdout_times, ended),
            'usage': dict(self.usage),
        }


def run_provider(
    command: Sequence[str],
    *,
    runner: str,
    cwd: Path,
    output_dir: Path,
    timeout_sec: float,
    stdin_text: str | None,
    env: dict[str, str],
    stall_timeout_sec: float = DEFAULT_STALL_TIMEOUT_SEC,
) -> dict:
    stdout_path = output_dir / 'provider_events.jsonl'
    stderr_path = output_dir / 'provider_stderr.log'
    transcript_path = output_dir / 'transcript.jsonl'
    recorder = _ProviderRecorder(runner)
    started_at = _utc_now()
    started_monotonic = time.monotonic()
    proc = subprocess.Popen(
        list(command), cwd=str(cwd),
        stdin=subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env=env, **_creation_options(),
    )
    assert proc.stdout is not None
    assert proc.stderr is not None
    stream_errors: queue.Queue[BaseException] = queue.Queue()

    with (
        stdout_path.open('wb') as stdout_handle,
        stderr_path.open('wb') as stderr_handle,
        transcript_path.open('w', encoding='utf-8', newline='') as transcript_handle,
    ):
        def pump(stream, stream_name: str, raw_handle) -> None:
            decoder = codecs.getincrementaldecoder('utf-8')(errors='replace')
            pending = ''
            try:
                reader = getattr(stream, 'read1', stream.read)
                while True:
                    raw = reader(8192)
                    if not raw:
                        break
                    recorder.record_raw(stream_name, len(raw))
                    raw_handle.write(raw)
                    raw_handle.flush()
                    pending += decoder.decode(raw)
                    while True:
                        newline = pending.find(chr(10))
                        if newline < 0:
                            break
                        line = pending[:newline]
                        pending = pending[newline + 1:]
                        if line.endswith(chr(13)):
                            line = line[:-1]
                        recorder.record(
                            stream_name, line, transcript_handle)
                pending += decoder.decode(b'', final=True)
                if pending:
                    recorder.record(stream_name, pending, transcript_handle)
            except BaseException as exc:
                stream_errors.put(exc)
            finally:
                stream.close()

        threads = [
            threading.Thread(
                target=pump,
                args=(proc.stdout, 'stdout', stdout_handle),
                daemon=True,
            ),
            threading.Thread(
                target=pump,
                args=(proc.stderr, 'stderr', stderr_handle),
                daemon=True,
            ),
        ]
        for thread in threads:
            thread.start()
        if stdin_text is not None:
            assert proc.stdin is not None
            try:
                proc.stdin.write(stdin_text.encode('utf-8'))
                proc.stdin.close()
            except BrokenPipeError:
                pass

        timed_out = False
        stalled = False
        termination_reason = ''
        while proc.poll() is None:
            elapsed = max(0.0, time.monotonic() - started_monotonic)
            if elapsed >= timeout_sec:
                timed_out = True
                termination_reason = 'overall_timeout'
                _terminate_process_tree(proc)
                break
            if recorder.raw_silence_sec() >= stall_timeout_sec:
                stalled = True
                termination_reason = 'raw_output_stall'
                _terminate_process_tree(proc)
                break
            time.sleep(0.25)
        try:
            returncode = proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            _terminate_process_tree(proc)
            returncode = proc.wait(timeout=30)
        for thread in threads:
            thread.join(timeout=30)
        if any(thread.is_alive() for thread in threads):
            _terminate_process_tree(proc)
            raise RuntimeError(
                'provider output reader did not close after process exit')
        if not stream_errors.empty():
            raise stream_errors.get()

    duration = max(0.0, time.monotonic() - started_monotonic)
    (output_dir / 'final_response.md').write_text(
        recorder.final_response, encoding='utf-8')
    return {
        'started_at': started_at,
        'finished_at': _utc_now(),
        'duration_sec': duration,
        'returncode': returncode,
        'timed_out': timed_out,
        'stalled': stalled,
        'termination_reason': termination_reason or None,
        'pid': proc.pid,
        **recorder.metrics(duration),
    }

def run_selfcheck(
    command: Sequence[str],
    *,
    cwd: Path,
    output_dir: Path,
    timeout_sec: float,
    env: dict[str, str],
) -> dict:
    started_at = _utc_now()
    started_monotonic = time.monotonic()
    proc = subprocess.Popen(
        list(command), cwd=str(cwd), stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding='utf-8', errors='replace',
        env=env, **_creation_options(),
    )
    timed_out = False
    try:
        stdout, stderr = proc.communicate(timeout=timeout_sec)
    except subprocess.TimeoutExpired:
        timed_out = True
        _terminate_process_tree(proc)
        stdout, stderr = proc.communicate(timeout=30)
    (output_dir / 'selfcheck.stdout.log').write_text(
        stdout, encoding='utf-8')
    (output_dir / 'selfcheck.stderr.log').write_text(
        stderr, encoding='utf-8')
    return {
        'command': list(command),
        'started_at': started_at,
        'finished_at': _utc_now(),
        'duration_sec': max(0.0, time.monotonic() - started_monotonic),
        'returncode': proc.returncode,
        'timed_out': timed_out,
    }


def collect_patch(repo: Path, local_baseline: str, output_dir: Path) -> dict:
    '''Capture every model/selfcheck change, including ignored files.'''
    _git(repo, ['add', '--all', '--force', '--', '.'])
    full_patch = _git(
        repo,
        ['diff', '--binary', '--cached', local_baseline, '--'],
        text=False,
    ).stdout
    full_patch_path = output_dir / 'all_changes.patch'
    full_patch_path.write_bytes(full_patch)
    raw_names = _git(
        repo,
        ['diff', '--cached', '--name-only', '-z', local_baseline, '--'],
        text=False,
    ).stdout
    all_changed_paths = [
        value.decode('utf-8', errors='surrogateescape')
        for value in raw_names.split(bytes([0])) if value
    ]
    status = _git(repo, ['status', '--short', '--ignored']).stdout
    (output_dir / 'sandbox_status.txt').write_text(
        status, encoding='utf-8')

    harness_owned = {
        'sts2-ascend/knowledge/review_prompt_latest.md',
    }
    harness_owned_paths = [
        path for path in all_changed_paths if path in harness_owned
    ]
    model_changed_paths = [
        path for path in all_changed_paths if path not in harness_owned
    ]
    return {
        'forensic_path': full_patch_path.name,
        'forensic_bytes': len(full_patch),
        'forensic_sha256': _sha256(full_patch_path),
        'all_changed_paths': all_changed_paths,
        'harness_owned_paths': harness_owned_paths,
        'model_changed_paths': model_changed_paths,
        'changed_paths': model_changed_paths,
        'eligible_path': 'changes.patch',
        'statement': (
            'all_changes.patch preserves the force-staged full scene; '
            'changes.patch is exported later from production-accepted paths.'
        ),
    }


def run_production_validation(
    *,
    validator_source_repo: Path,
    validator_revision: str,
    prompt_path: Path,
    sandbox_repo: Path,
    local_baseline: str,
    changed_paths: Sequence[str],
    execution_success: bool,
    selfcheck: dict,
    output_dir: Path,
) -> dict:
    '''Run current production deny-only and closure predicates, without queues.'''
    request_path = output_dir / 'production_validation.request.json'
    stdout_path = output_dir / 'production_validation.stdout.log'
    stderr_path = output_dir / 'production_validation.stderr.log'
    eligible_patch_path = output_dir / 'changes.patch'
    validator_repo = output_dir / 'validator' / 'repo'
    validator_baseline = ''
    try:
        validator_baseline = create_validator_snapshot(
            validator_source_repo.resolve(),
            validator_revision,
            validator_repo,
        )
        packet = _extract_prompt_packet(
            prompt_path.read_text(encoding='utf-8'))
        closure_state = packet.get('review_closure')
        if not isinstance(closure_state, dict):
            raise ValueError('prompt packet has no review_closure object')
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        return {
            'status': 'validation_error',
            'accepted_for_merge': False,
            'error': {'type': type(exc).__name__, 'message': str(exc)},
            'statement': (
                'Production acceptance was not established; quality remains '
                'a separate blind-review decision.'
            ),
        }

    request_payload = {
        'changed_paths': list(changed_paths),
        'sandbox_repo': str(sandbox_repo.resolve()),
        'local_baseline': local_baseline,
        'eligible_patch_path': str(eligible_patch_path.resolve()),
        'closure_state': closure_state,
    }
    _write_json(request_path, request_payload)
    helper = (
        'import json,subprocess,sys; from pathlib import Path; '
        'repo=Path(sys.argv[1]); req=json.loads(Path(sys.argv[2]).read_text('
        'encoding="utf-8")); brain=repo/"sts2-ascend"/"brain"; '
        'sys.path.insert(0,str(brain)); import llm_review; '
        'paths=req["changed_paths"]; '
        'allowed,transient,online,rejected='
        'llm_review._partition_review_changes(paths); '
        'sandbox=Path(req["sandbox_repo"]); baseline=req["local_baseline"]; '
        'eligible=Path(req["eligible_patch_path"]); '
        'patch_result=subprocess.run(['
        '"git","-C",str(sandbox),"diff","--binary","--cached",baseline,"--",'
        '*allowed],capture_output=True) if allowed else None; '
        'patch=(patch_result.stdout if patch_result is not None else b""); '
        'assert patch_result is None or patch_result.returncode == 0, '
        '(patch_result.stderr.decode("utf-8",errors="replace") '
        'if patch_result is not None else ""); '
        'eligible.write_bytes(patch); '
        'closure_error=llm_review._review_closure_gate_error('
        'req["closure_state"],allowed,patch); '
        'result={"deny_only":{"passed":not online and not rejected,'
        '"accepted_paths":allowed,"transient_artifact_paths":transient,'
        '"online_paths":online,"rejected_paths":rejected},'
        '"closure":{"required":bool(req["closure_state"].get('
        '"action_required")),"passed":not bool(closure_error),'
        '"error":closure_error,"action_paths":list('
        'llm_review._review_action_paths(allowed))}}; '
        'print(json.dumps(result,ensure_ascii=False,sort_keys=True))'
    )
    env = evaluation_environment()
    started_at = _utc_now()
    try:
        completed = subprocess.run(
            [
                sys.executable, '-B', '-c', helper,
                str(validator_repo.resolve()), str(request_path.resolve()),
            ],
            cwd=str(validator_repo.resolve()), check=False,
            capture_output=True, text=True, encoding='utf-8',
            errors='replace', env=env, timeout=120,
        )
        stdout_path.write_text(completed.stdout, encoding='utf-8')
        stderr_path.write_text(completed.stderr, encoding='utf-8')
        if completed.returncode != 0:
            raise RuntimeError(
                'production validator failed: '
                + completed.stderr.strip()[:1000])
        lines = [line for line in completed.stdout.splitlines() if line.strip()]
        validated = json.loads(lines[-1])
        if not isinstance(validated, dict):
            raise ValueError('production validator result is not an object')
    except (
        OSError, ValueError, RuntimeError, subprocess.SubprocessError,
        json.JSONDecodeError,
    ) as exc:
        return {
            'status': 'validation_error',
            'accepted_for_merge': False,
            'started_at': started_at,
            'finished_at': _utc_now(),
            'error': {'type': type(exc).__name__, 'message': str(exc)},
            'statement': (
                'Production acceptance was not established; quality remains '
                'a separate blind-review decision.'
            ),
        }

    selfcheck_passed = (
        selfcheck.get('returncode') == 0
        and not selfcheck.get('timed_out')
        and not selfcheck.get('harness_error')
    )
    deny_only = validated.get('deny_only') or {}
    accepted_paths = list(deny_only.get('accepted_paths') or [])
    eligible_patch = {
        'path': eligible_patch_path.name,
        'bytes': eligible_patch_path.stat().st_size,
        'sha256': _sha256(eligible_patch_path),
        'changed_paths': accepted_paths,
    }
    gate_passed = bool(
        execution_success
        and selfcheck_passed
        and deny_only.get('passed')
        and (validated.get('closure') or {}).get('passed')
        and accepted_paths
        and eligible_patch['bytes'] > 0
    )
    validator_files = []
    for relative in (
        'sts2-ascend/brain/llm_review.py',
        'sts2-ascend/brain/autogit.py',
    ):
        path = validator_repo / relative
        validator_files.append({
            'path': relative,
            'git_object_id': _git_path_oid(
                validator_source_repo, validator_baseline, relative),
            'snapshot_sha256': _sha256(path) if path.is_file() else '',
        })
    return {
        'status': (
            'gate_passed_pending_blind_review'
            if gate_passed else 'gate_rejected'
        ),
        'accepted_for_merge': gate_passed,
        'started_at': started_at,
        'finished_at': _utc_now(),
        'deny_only': deny_only,
        'closure': validated.get('closure'),
        'selfcheck': {'passed': selfcheck_passed},
        'eligible_patch': eligible_patch,
        'validator': {
            'requested_revision': validator_revision,
            'source_baseline': validator_baseline,
            'snapshot_path': str(validator_repo),
            'files': validator_files,
        },
        'statement': (
            'This is host gate eligibility only. It is not a capability or '
            'quality verdict; blind review remains pending.'
        ),
    }

def execute_evaluation(
    request: EvalRequest,
    *,
    binary_override: str | None = None,
    provider_executor: Callable[..., dict] = run_provider,
    selfcheck_executor: Callable[..., dict] = run_selfcheck,
    acceptance_validator: Callable[..., dict] = run_production_validation,
) -> tuple[Path, dict]:
    '''Execute an evaluation while preserving a manifest from initialization.'''
    source_repo = request.source_repo.resolve()
    prompt_source = request.prompt_path.resolve()
    output_root = request.output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    result_dir = output_root / (
        f'{stamp}-{_slug(request.case_id)}-{_slug(request.backend.key)}'
    )
    result_dir.mkdir(parents=True, exist_ok=False)
    partial_path = result_dir / 'manifest.partial.json'
    final_path = result_dir / 'manifest.json'
    prompt_path = result_dir / 'prompt.md'
    sandbox_repo = result_dir / 'sandbox' / 'repo'
    for artifact in (
        'provider_events.jsonl',
        'provider_stderr.log',
        'transcript.jsonl',
        'final_response.md',
        'selfcheck.stdout.log',
        'selfcheck.stderr.log',
        'changes.patch',
        'sandbox_status.txt',
    ):
        (result_dir / artifact).touch()

    manifest: dict = {
        'schema_version': 2,
        'case_id': request.case_id,
        'backend': asdict(request.backend),
        'source_repo': str(source_repo),
        'requested_baseline': request.baseline,
        'source_baseline': None,
        'local_baseline': None,
        'started_at': _utc_now(),
        'queue_independent': True,
        'live_brain_accessed': False,
        'initialization': {'status': 'initializing'},
        'tool_versions': {
            'git': _probe_version(['git', '--version']),
            'python': {
                'executable': sys.executable,
                'version': sys.version,
            },
            'evaluator': {
                'path': Path(__file__).resolve().name,
                'sha256': _sha256(Path(__file__).resolve()),
            },
        },
    }
    _write_json(partial_path, manifest)

    def finish() -> tuple[Path, dict]:
        manifest['finished_at'] = _utc_now()
        manifest['evidence_hashes'] = _artifact_hashes(result_dir)
        _write_json(final_path, manifest)
        partial_path.unlink(missing_ok=True)
        return result_dir, manifest

    initialization_stage = 'resolve_baseline'
    try:
        source_baseline = resolve_baseline(source_repo, request.baseline)
        manifest['source_baseline'] = source_baseline
        validator_baseline = resolve_baseline(
            source_repo, request.validator_revision)
        manifest['validator_source'] = {
            'requested_revision': request.validator_revision,
            'source_baseline': validator_baseline,
            'frozen_per_evaluation': True,
        }
        initialization_stage = 'freeze_prompt'
        shutil.copyfile(prompt_source, prompt_path)
        prompt_sha = _sha256(prompt_path)
        prompt_record: dict = {
            'path': prompt_path.name,
            'bytes': prompt_path.stat().st_size,
            'sha256': prompt_sha,
            'origin': 'user_supplied_frozen_file',
        }
        if request.prompt_provenance_path is not None:
            provenance_source = request.prompt_provenance_path.resolve()
            provenance = json.loads(
                provenance_source.read_text(encoding='utf-8'))
            provenance_runs = _validate_prompt_provenance(
                provenance, prompt_path, source_baseline)
            saved_provenance = result_dir / 'prompt_provenance.json'
            shutil.copyfile(provenance_source, saved_provenance)
            prompt_record.update({
                'origin': 'verified_reconstructed_bundle',
                'provenance_path': saved_provenance.name,
                'historical_byte_original': False,
                'batch_runs': list(provenance_runs),
            })
        else:
            prompt_record.update({
                'historical_byte_original': 'not_claimed',
                'provenance_statement': (
                    'Raw frozen prompt supplied without reconstruction bundle.'
                ),
            })
        manifest['prompt'] = prompt_record

        initialization_stage = 'create_isolated_repository'
        local_baseline = create_isolated_repository(
            source_repo, source_baseline, sandbox_repo)
        manifest['local_baseline'] = local_baseline
        sandbox_prompt = (
            sandbox_repo / 'sts2-ascend' / 'knowledge' /
            'review_prompt_latest.md'
        )
        sandbox_prompt.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(prompt_path, sandbox_prompt)
        manifest['sandbox'] = {
            'path': str(sandbox_repo),
            'remote_count': 0,
            'source': 'git archive + fresh root commit',
        }

        initialization_stage = 'resolve_backend_binary'
        binary = binary_override or find_runner_binary(request.backend)
        manifest['backend_binary'] = {
            'path': binary,
            'override': binary_override is not None,
        }
        manifest['tool_versions']['backend_cli'] = (
            {
                'status': 'not_probed_test_override',
                'path': binary,
            }
            if binary_override is not None
            else _probe_version([binary, '--version'])
        )
        initialization_stage = 'build_provider_command'
        command, stdin_text = build_provider_command(
            request.backend, binary, sandbox_repo, prompt_path,
            f'sts2-eval-{_slug(request.case_id)}',
        )
        manifest['provider_command'] = list(command)
        manifest['initialization'] = {
            'status': 'ready', 'finished_at': _utc_now(),
        }
    except (
        OSError, ValueError, RuntimeError, subprocess.SubprocessError,
        json.JSONDecodeError,
    ) as exc:
        error = {
            'stage': initialization_stage,
            'type': type(exc).__name__,
            'message': str(exc),
        }
        manifest['initialization'] = {
            'status': 'failed', 'finished_at': _utc_now(), 'error': error,
        }
        manifest['harness_errors'] = [error]
        manifest['provider'] = {
            'status': 'not_started', 'returncode': None, 'timed_out': False,
        }
        manifest['selfcheck'] = {
            'status': 'not_started', 'returncode': None, 'timed_out': False,
        }
        manifest['patch'] = {
            'path': 'changes.patch', 'bytes': 0,
            'sha256': _sha256(result_dir / 'changes.patch'),
            'changed_paths': [],
        }
        manifest['execution_success'] = False

        manifest['production_acceptance'] = {
            'status': 'not_evaluated_initialization_failed',
            'accepted_for_merge': False,
        }
        manifest['blind_review'] = {
            'status': 'not_ready',
            'verdict': None,
            'reason': 'evaluation did not initialize',
        }
        return finish()

    env = evaluation_environment()
    harness_errors: list[dict[str, str]] = []
    try:
        manifest['provider'] = provider_executor(
            command,
            runner=request.backend.runner,
            cwd=sandbox_repo,
            output_dir=result_dir,
            timeout_sec=request.timeout_sec,
            stdin_text=stdin_text,
            env=env,
            stall_timeout_sec=request.stall_timeout_sec,
        )
    except Exception as exc:
        error = {
            'stage': 'provider', 'type': type(exc).__name__,
            'message': str(exc),
        }
        harness_errors.append(error)
        manifest['provider'] = {
            'returncode': None, 'timed_out': False, 'harness_error': error,
        }
    try:
        manifest['selfcheck'] = selfcheck_executor(
            request.selfcheck_command,
            cwd=sandbox_repo,
            output_dir=result_dir,
            timeout_sec=request.selfcheck_timeout_sec,
            env=env,
        )
    except Exception as exc:
        error = {
            'stage': 'selfcheck', 'type': type(exc).__name__,
            'message': str(exc),
        }
        harness_errors.append(error)
        manifest['selfcheck'] = {
            'returncode': None, 'timed_out': False, 'harness_error': error,
        }
    try:
        manifest['patch'] = collect_patch(
            sandbox_repo, local_baseline, result_dir)
    except Exception as exc:
        error = {
            'stage': 'patch', 'type': type(exc).__name__,
            'message': str(exc),
        }
        harness_errors.append(error)
        manifest['patch'] = {
            'forensic_path': 'all_changes.patch',
            'eligible_path': 'changes.patch',
            'all_changed_paths': [],
            'model_changed_paths': [],
            'changed_paths': [],
            'harness_error': error,
        }
    if harness_errors:
        manifest['harness_errors'] = harness_errors
    fatal_execution_stages = {
        item['stage'] for item in harness_errors
        if item['stage'] in {'provider', 'patch'}
    }
    execution_success = bool(
        not fatal_execution_stages
        and manifest['provider'].get('returncode') == 0
        and not manifest['provider'].get('timed_out')
        and not manifest['provider'].get('stalled')
    )
    manifest['execution_success'] = execution_success

    try:
        manifest['production_acceptance'] = acceptance_validator(
            validator_source_repo=source_repo,
            validator_revision=validator_baseline,
            prompt_path=prompt_path,
            sandbox_repo=sandbox_repo,
            local_baseline=local_baseline,
            changed_paths=(
                manifest['patch'].get('model_changed_paths') or []),
            execution_success=execution_success,
            selfcheck=manifest['selfcheck'],
            output_dir=result_dir,
        )
    except Exception as exc:
        manifest['production_acceptance'] = {
            'status': 'validation_error',
            'accepted_for_merge': False,
            'error': {'type': type(exc).__name__, 'message': str(exc)},
        }
    manifest['blind_review'] = {
        'status': (
            'pending' if execution_success else 'not_ready'
        ),
        'verdict': None,
        'statement': (
            'Execution and production gates do not establish model capability '
            'or patch quality. Independent blind review is required.'
        ),
    }
    return finish()


def _positive_seconds(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError('value must be greater than zero')
    return parsed


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            'Run one frozen GLM/Codex review evaluation without the live queue.'),
    )
    parser.add_argument(
        '--baseline', required=True,
        help='Committed source revision to freeze',
    )
    parser.add_argument(
        '--prompt', type=Path,
        help='Frozen evaluation prompt',
    )
    parser.add_argument(
        '--case-id',
        help='Stable evaluation case identifier',
    )
    parser.add_argument(
        '--backend-key',
        help=(
            'Exact backend: opencode:provider/model@variant or '
            'codex:model@reasoning:auto-review'
        ),
    )
    parser.add_argument(
        '--prepare-prompt', action='store_true',
        help='Prepare a deterministic baseline+runs prompt bundle and exit',
    )
    parser.add_argument('--batch-runs')
    parser.add_argument('--bundle-dir', type=Path)
    parser.add_argument('--prompt-bundle', type=Path)
    parser.add_argument(
        '--validator-baseline', default='HEAD',
        help='One fixed commit used for production gates across paired runs',
    )
    parser.add_argument('--source-repo', type=Path, default=SOURCE_ROOT)
    parser.add_argument(
        '--output-root', type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument(
        '--timeout-sec', type=_positive_seconds, default=DEFAULT_TIMEOUT_SEC)
    parser.add_argument(
        '--stall-timeout-sec',
        type=_positive_seconds,
        default=DEFAULT_STALL_TIMEOUT_SEC,
    )
    parser.add_argument(
        '--selfcheck-timeout-sec',
        type=_positive_seconds,
        default=DEFAULT_SELFCHECK_TIMEOUT_SEC,
    )
    parser.add_argument(
        '--selfcheck-command-json',
        default=json.dumps(list(EvalRequest.selfcheck_command)),
        help='JSON array command run inside the isolated repository',
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_argument_parser().parse_args(argv)
    try:
        if args.prepare_prompt:
            if not args.batch_runs or args.bundle_dir is None:
                raise ValueError(
                    '--prepare-prompt requires --batch-runs and --bundle-dir')
            bundle, provenance = reconstruct_prompt_bundle(
                args.source_repo, args.baseline,
                parse_batch_runs(args.batch_runs), args.bundle_dir,
            )
            print(json.dumps({
                'bundle_dir': str(bundle),
                'status': provenance['status'],
                'source_baseline': provenance.get('source_baseline'),
                'prompt_sha256': (
                    provenance.get('prompt') or {}).get('sha256'),
            }, ensure_ascii=False))
            return 0 if provenance['status'] == 'ready' else 2
        if not args.case_id or not args.backend_key:
            raise ValueError(
                'evaluation requires --case-id and --backend-key')
        if bool(args.prompt) == bool(args.prompt_bundle):
            raise ValueError(
                'evaluation requires exactly one of --prompt/--prompt-bundle')

        raw_selfcheck = json.loads(args.selfcheck_command_json)
        if (
            not isinstance(raw_selfcheck, list)
            or not raw_selfcheck
            or not all(
                isinstance(value, str) and value for value in raw_selfcheck)
        ):
            raise ValueError(
                '--selfcheck-command-json must be a non-empty JSON string array')

        provenance_path = None
        if args.prompt_bundle:
            args.prompt, provenance_path, _ = load_prompt_bundle(
                args.prompt_bundle, args.source_repo, args.baseline)
        request = EvalRequest(
            source_repo=args.source_repo,
            baseline=args.baseline,
            prompt_path=args.prompt,
            output_root=args.output_root,
            case_id=args.case_id,
            backend=parse_backend_key(args.backend_key),
            prompt_provenance_path=provenance_path,
            validator_revision=args.validator_baseline,
            timeout_sec=args.timeout_sec,
            stall_timeout_sec=args.stall_timeout_sec,
            selfcheck_timeout_sec=args.selfcheck_timeout_sec,
            selfcheck_command=tuple(raw_selfcheck),
        )
        result_dir, manifest = execute_evaluation(request)
    except (
        OSError, ValueError, RuntimeError, subprocess.SubprocessError,
    ) as exc:
        print(f'review evaluation failed: {exc}', file=sys.stderr)
        return 2
    print(json.dumps({
        'result_dir': str(result_dir),
        'execution_success': manifest['execution_success'],
        'backend_key': request.backend.key,
        'source_baseline': manifest['source_baseline'],
    }, ensure_ascii=False))
    return 0 if manifest['execution_success'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
