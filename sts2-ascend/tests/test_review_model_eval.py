'''Tests for the queue-independent review-model evaluator.'''
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = (
    Path(__file__).resolve().parents[1] / 'scripts' / 'review_model_eval.py')
SPEC = importlib.util.spec_from_file_location('review_model_eval', SCRIPT)
assert SPEC is not None and SPEC.loader is not None
review_model_eval = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = review_model_eval
SPEC.loader.exec_module(review_model_eval)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ['git', *args], cwd=repo, check=True, capture_output=True,
        text=True, encoding='utf-8',
    ).stdout.strip()


def _source_repo(root: Path) -> Path:
    source = root / 'source'
    source.mkdir()
    _git(source, 'init', '--quiet')
    _git(source, 'config', 'user.name', 'test')
    _git(source, 'config', 'user.email', 'test@localhost')
    (source / 'tracked.txt').write_text('baseline\n', encoding='utf-8')
    (source / '.gitignore').write_text(
        'sts2-ascend/knowledge/review_prompt_latest.md\n',
        encoding='utf-8',
    )
    _git(source, 'add', '-A')
    _git(source, 'commit', '--quiet', '-m', 'baseline')
    return source


class BackendKeyTests(unittest.TestCase):
    def test_explicit_glm_and_luna_keys_preserve_options(self) -> None:
        glm = review_model_eval.parse_backend_key(
            'opencode:opencode-go/glm-5.3-flash@max')
        luna = review_model_eval.parse_backend_key(
            'codex:gpt-5.6-luna@max:auto-review')
        self.assertEqual(
            (glm.runner, glm.model, glm.variant),
            ('opencode', 'opencode-go/glm-5.3-flash', 'max'),
        )
        self.assertEqual(
            (
                luna.runner, luna.model, luna.reasoning_effort,
                luna.approve_for_me,
            ),
            ('codex', 'gpt-5.6-luna', 'max', True),
        )

    def test_codex_command_matches_production_short_prompt_shape(self) -> None:
        spec = review_model_eval.parse_backend_key(
            'codex:gpt-5.6-luna@max:auto-review')
        with tempfile.TemporaryDirectory() as root:
            prompt = Path(root) / 'prompt.md'
            prompt.write_text('frozen prompt', encoding='utf-8')
            command, stdin_text = review_model_eval.build_provider_command(
                spec, 'codex.CMD', Path(root) / 'repo', prompt, 'eval-case')
        self.assertIsNone(stdin_text)
        self.assertIn(
            'sts2-ascend/knowledge/review_prompt_latest.md', command[-1])
        self.assertEqual(
            command[:6],
            ['codex.CMD', '-a', 'never', 'exec', '--model', 'gpt-5.6-luna'],
        )
        self.assertIn('model_reasoning_effort=' + json.dumps('max'), command)
        windows_sandbox = 'windows.sandbox="unelevated"'
        self.assertEqual(command.count(windows_sandbox), 1)
        self.assertEqual(command[command.index(windows_sandbox) - 1], '-c')
        self.assertIn(
            ('permissions.luna_commit={extends=":workspace",'
             'filesystem={":workspace_roots"={".git"="write"}},'
             'network={enabled=false}}'),
            command,
        )
        self.assertIn('default_permissions="luna_commit"', command)
        for option in ('--json', '--ephemeral', '--ignore-user-config'):
            self.assertIn(option, command)
        self.assertLess(command.index('-a'), command.index('exec'))
        self.assertGreater(
            command.index('--ignore-user-config'), command.index('exec'))
        self.assertEqual(sum(
            option in {'-C', '--cd'} for option in command), 1)
        self.assertEqual(
            command[command.index('-C') + 1], str(Path(root) / 'repo'))
        for forbidden in (
            '--approve-for-me', '--sandbox', '--add-dir', '--yolo',
            '--dangerously-bypass-approvals-and-sandbox',
            'danger-full-access',
        ):
            self.assertNotIn(forbidden, command)

    def test_codex_non_auto_review_uses_the_same_hard_boundary(self) -> None:
        spec = review_model_eval.parse_backend_key(
            'codex:gpt-5.6-luna@max')
        with tempfile.TemporaryDirectory() as root:
            prompt = Path(root) / 'prompt.md'
            prompt.write_text('frozen prompt', encoding='utf-8')
            command, _ = review_model_eval.build_provider_command(
                spec, 'codex.CMD', Path(root) / 'repo', prompt, 'eval-case')
        self.assertNotIn('--approve-for-me', command)
        self.assertNotIn('--sandbox', command)
        self.assertEqual(command.count('windows.sandbox="unelevated"'), 1)
        self.assertIn('default_permissions="luna_commit"', command)

    def test_codex_rejects_a_non_workspace_sandbox(self) -> None:
        spec = review_model_eval.BackendSpec(
            key='codex:gpt-5.6-luna@max:auto-review',
            runner='codex',
            model='gpt-5.6-luna',
            reasoning_effort='max',
            approve_for_me=True,
            sandbox='read-only',
        )
        with tempfile.TemporaryDirectory() as root:
            prompt = Path(root) / 'prompt.md'
            prompt.write_text('frozen prompt', encoding='utf-8')
            with self.assertRaisesRegex(
                    ValueError,
                    'requires workspace-write configuration semantics'):
                review_model_eval.build_provider_command(
                    spec, 'codex.CMD', Path(root) / 'repo', prompt,
                    'eval-case')

    def test_unknown_runner_is_rejected_without_fallback(self) -> None:
        with self.assertRaisesRegex(ValueError, 'unsupported backend key'):
            review_model_eval.parse_backend_key('auto:gpt-5.6-luna')


class IsolationTests(unittest.TestCase):
    def test_snapshot_has_no_remote_or_shared_git_metadata(self) -> None:
        with tempfile.TemporaryDirectory(prefix='sts2-eval-test-') as root:
            base = Path(root)
            source = _source_repo(base)
            source_head = _git(source, 'rev-parse', 'HEAD')
            isolated = base / 'output' / 'sandbox' / 'repo'
            local_head = review_model_eval.create_isolated_repository(
                source, source_head, isolated)

            self.assertEqual(_git(isolated, 'remote'), '')
            self.assertEqual(
                (isolated / 'tracked.txt').read_text(encoding='utf-8'),
                'baseline\n',
            )
            self.assertNotEqual(local_head, source_head)
            self.assertNotEqual(
                (isolated / '.git').resolve(), (source / '.git').resolve())


    def test_force_staged_forensics_preserve_ignored_and_exclude_harness_prompt(
            self) -> None:
        with tempfile.TemporaryDirectory(prefix='sts2-eval-test-') as root:
            base = Path(root)
            source = _source_repo(base)
            with (source / '.gitignore').open('a', encoding='utf-8') as handle:
                handle.write('ignored-cache/' + chr(10))
            _git(source, 'add', '.gitignore')
            _git(source, 'commit', '--quiet', '-m', 'ignore cache')
            isolated = base / 'sandbox'
            local = review_model_eval.create_isolated_repository(
                source, 'HEAD', isolated)
            cache_file = isolated / 'ignored-cache' / 'artifact.bin'
            cache_file.parent.mkdir()
            cache_file.write_bytes(b'cache evidence')
            prompt_file = (
                isolated / 'sts2-ascend' / 'knowledge'
                / 'review_prompt_latest.md'
            )
            prompt_file.parent.mkdir(parents=True)
            prompt_file.write_text('host prompt', encoding='utf-8')
            output = base / 'result'
            output.mkdir()

            inventory = review_model_eval.collect_patch(
                isolated, local, output)

            self.assertIn(
                'ignored-cache/artifact.bin',
                inventory['all_changed_paths'],
            )
            self.assertIn(
                'ignored-cache/artifact.bin',
                inventory['model_changed_paths'],
            )
            self.assertIn(
                'sts2-ascend/knowledge/review_prompt_latest.md',
                inventory['harness_owned_paths'],
            )
            self.assertNotIn(
                'sts2-ascend/knowledge/review_prompt_latest.md',
                inventory['model_changed_paths'],
            )
            self.assertIn(
                b'cache evidence',
                (output / 'all_changes.patch').read_bytes(),
            )


class EvaluationArtifactTests(unittest.TestCase):
    def test_saves_transcript_metrics_patch_and_selfcheck(self) -> None:
        with tempfile.TemporaryDirectory(prefix='sts2-eval-test-') as root:
            base = Path(root)
            source = _source_repo(base)
            prompt = base / 'input-prompt.md'
            prompt.write_text('inspect and improve', encoding='utf-8')

            def fake_provider(_command, **kwargs):
                output_dir = kwargs['output_dir']
                (kwargs['cwd'] / 'tracked.txt').write_text(
                    'improved\n', encoding='utf-8')
                event = {
                    'type': 'turn.completed',
                    'usage': {'input_tokens': 10},
                }
                (output_dir / 'provider_events.jsonl').write_text(
                    json.dumps(event) + '\n', encoding='utf-8')
                (output_dir / 'provider_stderr.log').write_text(
                    '', encoding='utf-8')
                (output_dir / 'transcript.jsonl').write_text(
                    json.dumps({'stream': 'stdout', 'text': 'done'}) + '\n',
                    encoding='utf-8',
                )
                (output_dir / 'final_response.md').write_text(
                    'done', encoding='utf-8')
                return {
                    'returncode': 0,
                    'timed_out': False,
                    'duration_sec': 1.25,
                    'usage': {'input_tokens': 10},
                }

            def fake_selfcheck(_command, **kwargs):
                output_dir = kwargs['output_dir']
                (output_dir / 'selfcheck.stdout.log').write_text(
                    'SELFCHECK OK\n', encoding='utf-8')
                (output_dir / 'selfcheck.stderr.log').write_text(
                    '', encoding='utf-8')
                return {
                    'returncode': 0,
                    'timed_out': False,
                    'duration_sec': 0.5,
                }

            request = review_model_eval.EvalRequest(
                source_repo=source,
                baseline='HEAD',
                prompt_path=prompt,
                output_root=base / 'results',
                case_id='case-one',
                backend=review_model_eval.parse_backend_key(
                    'codex:gpt-5.6-luna@max:auto-review'),
            )
            result_dir, manifest = review_model_eval.execute_evaluation(
                request,
                binary_override='codex.CMD',
                provider_executor=fake_provider,
                selfcheck_executor=fake_selfcheck,
            )

            self.assertTrue(manifest['execution_success'])
            self.assertTrue(manifest['queue_independent'])
            for name in (
                'prompt.md',
                'provider_events.jsonl',
                'provider_stderr.log',
                'transcript.jsonl',
                'final_response.md',
                'selfcheck.stdout.log',
                'selfcheck.stderr.log',
                'changes.patch',
                'all_changes.patch',
                'manifest.json',
            ):
                self.assertTrue((result_dir / name).is_file(), name)
            self.assertIn('tracked.txt', manifest['patch']['changed_paths'])
            self.assertIn(
                b'improved', (result_dir / 'all_changes.patch').read_bytes())
            saved = json.loads(
                (result_dir / 'manifest.json').read_text(encoding='utf-8'))
            self.assertEqual(
                saved['backend']['key'],
                'codex:gpt-5.6-luna@max:auto-review',
            )
            self.assertEqual(
                saved['provider']['usage']['input_tokens'], 10)
            sandbox_prompt = (
                result_dir / 'sandbox' / 'repo' / 'sts2-ascend' /
                'knowledge' / 'review_prompt_latest.md'
            )
            self.assertEqual(
                sandbox_prompt.read_text(encoding='utf-8'),
                'inspect and improve',
            )
            self.assertNotIn(
                'sts2-ascend/knowledge/review_prompt_latest.md',
                manifest['patch']['changed_paths'],
            )

    def test_module_import_has_no_live_brain_or_queue_dependency(self) -> None:
        self.assertNotIn('llm_review', review_model_eval.__dict__)
        self.assertNotIn('Knowledge', review_model_eval.__dict__)
        env = review_model_eval.evaluation_environment()
        self.assertEqual(env['STS2_ASCEND_EVAL_MODE'], '1')
        self.assertEqual(env['STS2_ASCEND_DISABLE_VIEWER'], '1')
        self.assertFalse(any(
            key.startswith('STS2_ASCEND_SESSION')
            for key in env
        ))

    def test_provider_exception_still_saves_patch_and_selfcheck(self) -> None:
        with tempfile.TemporaryDirectory(prefix='sts2-eval-test-') as root:
            base = Path(root)
            source = _source_repo(base)
            prompt = base / 'prompt.md'
            prompt.write_text('frozen', encoding='utf-8')

            def failing_provider(_command, **kwargs):
                (kwargs['cwd'] / 'tracked.txt').write_text(
                    'partial model work\n', encoding='utf-8')
                raise OSError('provider start failed')

            def passing_selfcheck(_command, **kwargs):
                return {'returncode': 0, 'timed_out': False}

            request = review_model_eval.EvalRequest(
                source_repo=source,
                baseline='HEAD',
                prompt_path=prompt,
                output_root=base / 'results',
                case_id='provider-failure',
                backend=review_model_eval.parse_backend_key(
                    'codex:gpt-5.6-luna@max:auto-review'),
            )
            result_dir, manifest = review_model_eval.execute_evaluation(
                request,
                binary_override='codex.CMD',
                provider_executor=failing_provider,
                selfcheck_executor=passing_selfcheck,
            )

            self.assertFalse(manifest['execution_success'])
            self.assertEqual(
                manifest['harness_errors'][0]['stage'], 'provider')
            self.assertEqual(manifest['selfcheck']['returncode'], 0)
            self.assertIn(
                b'partial model work',
                (result_dir / 'all_changes.patch').read_bytes(),
            )
            for name in (
                'provider_events.jsonl', 'transcript.jsonl',
                'selfcheck.stdout.log', 'manifest.json',
            ):
                self.assertTrue((result_dir / name).is_file(), name)


class ProvenanceAndOutcomeTests(unittest.TestCase):
    def test_batch_run_parser_is_canonical_and_rejects_descending(self) -> None:
        self.assertEqual(
            review_model_eval.parse_batch_runs('855,843-845,844'),
            (843, 844, 845, 855),
        )
        with self.assertRaisesRegex(ValueError, 'descending'):
            review_model_eval.parse_batch_runs('10-8')

    def test_prompt_bundle_verifies_baseline_and_sha(self) -> None:
        with tempfile.TemporaryDirectory(prefix='sts2-eval-test-') as root:
            base = Path(root)
            source = _source_repo(base)
            baseline = _git(source, 'rev-parse', 'HEAD')
            bundle = base / 'bundle'
            bundle.mkdir()
            prompt = bundle / 'prompt.md'
            fence = chr(96) * 3
            prompt.write_text(
                fence + 'json' + chr(10)
                + json.dumps({
                    'run_evidence_scope': {
                        'exact': [1, 2],
                        'missing': [],
                    },
                })
                + chr(10) + fence,
                encoding='utf-8',
            )
            provenance = {
                'kind': 'deterministic_baseline_reconstruction',
                'status': 'ready',
                'historical_byte_original': False,
                'source_baseline': baseline,
                'batch_runs': [1, 2],
                'run_evidence_scope': {
                    'exact': [1, 2],
                    'missing': [],
                },
                'prompt': {
                    'sha256': review_model_eval._sha256(prompt),
                },
            }
            (bundle / 'prompt_provenance.json').write_text(
                json.dumps(provenance), encoding='utf-8')

            loaded, provenance_path, saved = (
                review_model_eval.load_prompt_bundle(
                    bundle, source, baseline))
            self.assertEqual(loaded, prompt.resolve())
            self.assertTrue(provenance_path.is_file())
            self.assertEqual(saved['batch_runs'], [1, 2])

            prompt.write_text('tampered', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'SHA-256'):
                review_model_eval.load_prompt_bundle(
                    bundle, source, baseline)

    def test_malformed_prompt_record_is_a_formal_initialization_failure(
            self) -> None:
        with tempfile.TemporaryDirectory(prefix='sts2-eval-test-') as root:
            base = Path(root)
            source = _source_repo(base)
            baseline = _git(source, 'rev-parse', 'HEAD')
            bundle = base / 'bundle'
            bundle.mkdir()
            prompt = bundle / 'prompt.md'
            fence = chr(96) * 3
            prompt.write_text(
                fence + 'json' + chr(10)
                + json.dumps({
                    'run_evidence_scope': {
                        'exact': [1],
                        'missing': [],
                    },
                })
                + chr(10) + fence,
                encoding='utf-8',
            )
            provenance = {
                'kind': 'deterministic_baseline_reconstruction',
                'status': 'ready',
                'historical_byte_original': False,
                'source_baseline': baseline,
                'batch_runs': [1],
                'run_evidence_scope': {
                    'exact': [1],
                    'missing': [],
                },
                'prompt': ['not', 'an', 'object'],
            }
            provenance_path = bundle / 'prompt_provenance.json'
            provenance_path.write_text(
                json.dumps(provenance), encoding='utf-8')
            request = review_model_eval.EvalRequest(
                source_repo=source,
                baseline=baseline,
                prompt_path=prompt,
                prompt_provenance_path=provenance_path,
                output_root=base / 'results',
                case_id='malformed-provenance',
                backend=review_model_eval.parse_backend_key(
                    'codex:gpt-5.6-luna@max:auto-review'),
            )

            result_dir, manifest = review_model_eval.execute_evaluation(
                request, binary_override='codex.CMD')

            self.assertFalse(manifest['execution_success'])
            self.assertEqual(
                manifest['initialization']['status'], 'failed')
            self.assertTrue((result_dir / 'manifest.json').is_file())
            self.assertFalse(
                (result_dir / 'manifest.partial.json').exists())

    def test_initialization_failure_writes_final_manifest(self) -> None:
        with tempfile.TemporaryDirectory(prefix='sts2-eval-test-') as root:
            base = Path(root)
            source = _source_repo(base)
            prompt = base / 'prompt.md'
            prompt.write_text('frozen', encoding='utf-8')
            request = review_model_eval.EvalRequest(
                source_repo=source,
                baseline='missing-baseline',
                prompt_path=prompt,
                output_root=base / 'results',
                case_id='init-failure',
                backend=review_model_eval.parse_backend_key(
                    'codex:gpt-5.6-luna@max:auto-review'),
            )

            result_dir, manifest = review_model_eval.execute_evaluation(
                request, binary_override='codex.CMD')

            self.assertFalse(manifest['execution_success'])
            self.assertEqual(
                manifest['initialization']['status'], 'failed')
            self.assertEqual(
                manifest['production_acceptance']['status'],
                'not_evaluated_initialization_failed',
            )
            self.assertEqual(
                manifest['blind_review']['status'], 'not_ready')
            self.assertTrue((result_dir / 'manifest.json').is_file())
            self.assertFalse(
                (result_dir / 'manifest.partial.json').exists())

    def test_execution_acceptance_and_quality_are_independent(self) -> None:
        with tempfile.TemporaryDirectory(prefix='sts2-eval-test-') as root:
            base = Path(root)
            source = _source_repo(base)
            prompt = base / 'prompt.md'
            prompt.write_text('frozen', encoding='utf-8')

            def provider(_command, **_kwargs):
                return {'returncode': 0, 'timed_out': False}

            def failed_selfcheck(_command, **_kwargs):
                return {'returncode': 1, 'timed_out': False}

            def rejected_acceptance(**_kwargs):
                return {
                    'status': 'rejected',
                    'accepted_for_merge': False,
                }

            request = review_model_eval.EvalRequest(
                source_repo=source,
                baseline='HEAD',
                prompt_path=prompt,
                output_root=base / 'results',
                case_id='separated-outcomes',
                backend=review_model_eval.parse_backend_key(
                    'codex:gpt-5.6-luna@max:auto-review'),
            )
            _result_dir, manifest = review_model_eval.execute_evaluation(
                request,
                binary_override='codex.CMD',
                provider_executor=provider,
                selfcheck_executor=failed_selfcheck,
                acceptance_validator=rejected_acceptance,
            )
            self.assertTrue(manifest['execution_success'])
            self.assertFalse(
                manifest['production_acceptance']['accepted_for_merge'])
            self.assertEqual(
                manifest['blind_review']['status'], 'pending',
            )


class ValidatorSnapshotTests(unittest.TestCase):
    def test_snapshot_uses_fixed_revision_not_later_head(self) -> None:
        with tempfile.TemporaryDirectory(prefix='sts2-eval-test-') as root:
            base = Path(root)
            source = _source_repo(base)
            brain = source / 'sts2-ascend' / 'brain'
            brain.mkdir(parents=True)
            for name in (
                'llm_review.py', 'review_runners.py',
                'lifecycle.py', 'autogit.py',
            ):
                (brain / name).write_text(
                    'VALUE = "old"' + chr(10), encoding='utf-8')
            _git(source, 'add', '-A')
            _git(source, 'commit', '--quiet', '-m', 'validator old')
            frozen = _git(source, 'rev-parse', 'HEAD')
            (brain / 'llm_review.py').write_text(
                'VALUE = "new"' + chr(10), encoding='utf-8')
            _git(source, 'add', '-A')
            _git(source, 'commit', '--quiet', '-m', 'validator new')

            snapshot = base / 'validator' / 'repo'
            resolved = review_model_eval.create_validator_snapshot(
                source, frozen, snapshot)

            self.assertEqual(resolved, frozen)
            self.assertEqual(
                (
                    snapshot / 'sts2-ascend' / 'brain' / 'llm_review.py'
                ).read_text(encoding='utf-8'),
                'VALUE = "old"' + chr(10),
            )


class ProviderMetricsTests(unittest.TestCase):
    def test_raw_chunk_is_observed_before_completed_json_line(self) -> None:
        first = '{"type":'
        second = '"thread.started"}' + chr(10)
        code = (
            'import sys,time; '
            'sys.stdout.write(' + repr(first) + '); sys.stdout.flush(); '
            'time.sleep(0.4); '
            'sys.stdout.write(' + repr(second) + '); sys.stdout.flush()'
        )
        command = [sys.executable, '-u', '-c', code]
        with tempfile.TemporaryDirectory(prefix='sts2-eval-test-') as root:
            result = review_model_eval.run_provider(
                command,
                runner='codex',
                cwd=Path(root),
                output_dir=Path(root),
                timeout_sec=10,
                stall_timeout_sec=5,
                stdin_text=None,
                env=review_model_eval.evaluation_environment(),
            )
            self.assertEqual(result['returncode'], 0)
            self.assertGreaterEqual(result['raw_chunks'], 2)
            self.assertLess(
                result['first_raw_byte_after_sec'],
                result['first_output_after_sec'],
            )
            self.assertEqual(result['json_event_count'], 1)

    def test_raw_output_stall_terminates_before_overall_timeout(self) -> None:
        code = (
            'import sys,time; '
            'sys.stdout.write("x"); sys.stdout.flush(); time.sleep(5)'
        )
        command = [sys.executable, '-u', '-c', code]
        with tempfile.TemporaryDirectory(prefix='sts2-eval-test-') as root:
            result = review_model_eval.run_provider(
                command,
                runner='codex',
                cwd=Path(root),
                output_dir=Path(root),
                timeout_sec=10,
                stall_timeout_sec=0.5,
                stdin_text=None,
                env=review_model_eval.evaluation_environment(),
            )
            self.assertTrue(result['stalled'])
            self.assertFalse(result['timed_out'])
            self.assertEqual(
                result['termination_reason'], 'raw_output_stall')
            self.assertLess(result['duration_sec'], 4)
            self.assertEqual(
                (Path(root) / 'provider_events.jsonl').read_bytes(), b'x')

    def test_codex_jsonl_capture_records_usage_and_semantic_latency(self) -> None:
        events = [
            {'type': 'thread.started', 'thread_id': 't'},
            {
                'type': 'item.completed',
                'item': {'type': 'agent_message', 'text': 'done'},
            },
            {
                'type': 'turn.completed',
                'usage': {'input_tokens': 7, 'output_tokens': 3},
            },
        ]
        code = (
            'import json; events=' + repr(events) + '; '
            '[print(json.dumps(event), flush=True) for event in events]'
        )
        command = [sys.executable, '-u', '-c', code]
        with tempfile.TemporaryDirectory(prefix='sts2-eval-test-') as root:
            result = review_model_eval.run_provider(
                command,
                runner='codex',
                cwd=Path(root),
                output_dir=Path(root),
                timeout_sec=10,
                stdin_text=None,
                env=review_model_eval.evaluation_environment(),
            )
            self.assertEqual(result['returncode'], 0)
            self.assertEqual(result['usage']['output_tokens'], 3)
            self.assertIsNotNone(result['first_model_work_after_sec'])
            self.assertGreaterEqual(result['json_event_count'], 3)
            self.assertEqual(
                (Path(root) / 'final_response.md').read_text(encoding='utf-8'),
                'done',
            )


if __name__ == '__main__':
    unittest.main()
