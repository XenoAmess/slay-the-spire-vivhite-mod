from __future__ import annotations

import math
import sys
import tempfile
import unittest
import wave
from array import array
from pathlib import Path


ASCEND_DIR = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = ASCEND_DIR / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import prepare_reference_voice as reference  # noqa: E402


class ReferenceVoicePreparationTests(unittest.TestCase):
    def test_tracked_reference_matches_the_reproducible_recipe(self) -> None:
        master_path = ASCEND_DIR / "tts" / "reference_voice.wav"
        output_path = ASCEND_DIR / "tts" / "reference_voice_15s.wav"
        source, sample_rate = reference.read_pcm16_mono(master_path)
        source = source[: round(sample_rate * 15)]
        spans = reference.detect_silence_spans(
            source,
            sample_rate,
            threshold_dbfs=-45,
            frame_ms=20,
            hop_ms=10,
            min_silence_ms=400,
        )
        expected = reference.compress_silence_spans(
            source,
            spans,
            sample_rate,
            keep_silence_ms=200,
            crossfade_ms=8,
        )
        actual, actual_rate = reference.read_pcm16_mono(output_path)

        self.assertEqual(actual_rate, 24_000)
        self.assertEqual(len(spans), 5)
        self.assertEqual(len(actual), 307_440)
        self.assertEqual(actual, expected)

    def test_long_internal_pauses_are_shortened_without_touching_speech(self) -> None:
        sample_rate = 8_000

        def tone(seconds: float, frequency: float) -> array:
            count = round(sample_rate * seconds)
            return array(
                "h",
                (
                    round(8_000 * math.sin(2 * math.pi * frequency * index / sample_rate))
                    for index in range(count)
                ),
            )

        speech_a = tone(0.5, 220)
        speech_b = tone(0.5, 330)
        speech_c = tone(0.5, 440)
        samples = array("h", speech_a)
        samples.extend(array("h", [0]) * round(sample_rate * 0.6))
        samples.extend(speech_b)
        samples.extend(array("h", [0]) * round(sample_rate * 0.2))
        samples.extend(speech_c)

        spans = reference.detect_silence_spans(
            samples,
            sample_rate,
            threshold_dbfs=-45,
            frame_ms=20,
            hop_ms=10,
            min_silence_ms=400,
        )
        self.assertEqual(len(spans), 1)
        processed = reference.compress_silence_spans(
            samples,
            spans,
            sample_rate,
            keep_silence_ms=200,
            crossfade_ms=8,
        )

        expected_removed = round(sample_rate * (0.6 - 0.2))
        self.assertAlmostEqual(len(samples) - len(processed), expected_removed, delta=sample_rate * 0.03)
        self.assertEqual(processed[: len(speech_a)], speech_a)
        self.assertEqual(processed[-len(speech_c) :], speech_c)

    def test_existing_output_is_content_addressed_backed_up_before_replace(self) -> None:
        sample_rate = 8_000
        with tempfile.TemporaryDirectory() as raw_dir:
            directory = Path(raw_dir)
            input_path = directory / "master.wav"
            output_path = directory / "reference.wav"
            backup_dir = directory / "backups"

            source = array("h", [4_000]) * round(sample_rate * 0.5)
            source.extend(array("h", [0]) * round(sample_rate * 0.6))
            source.extend(array("h", [-4_000]) * round(sample_rate * 0.5))
            reference.write_pcm16_mono(input_path, source, sample_rate)
            old_output = array("h", [1_234]) * sample_rate
            reference.write_pcm16_mono(output_path, old_output, sample_rate)
            old_sha256 = reference.sha256_file(output_path)

            result = reference.prepare_reference_voice(
                input_path,
                output_path,
                backup_dir,
                max_seconds=2,
            )

            self.assertTrue(result.changed)
            self.assertIsNotNone(result.backup_path)
            assert result.backup_path is not None
            self.assertTrue(result.backup_path.is_file())
            self.assertEqual(reference.sha256_file(result.backup_path), old_sha256)
            output_samples, output_rate = reference.read_pcm16_mono(output_path)
            self.assertEqual(output_rate, sample_rate)
            self.assertLess(len(output_samples), len(source))

    def test_exact_threshold_and_edge_silence_are_not_compressed(self) -> None:
        sample_rate = 8_000
        speech = array("h", [5_000]) * round(sample_rate * 0.5)
        exact_threshold = array("h", [0]) * round(sample_rate * 0.4)
        samples = array("h", exact_threshold)
        samples.extend(speech)
        samples.extend(exact_threshold)
        samples.extend(speech)
        samples.extend(exact_threshold)

        spans = reference.detect_silence_spans(
            samples,
            sample_rate,
            threshold_dbfs=-45,
            frame_ms=20,
            hop_ms=10,
            min_silence_ms=400,
        )
        self.assertEqual(spans, ())


if __name__ == "__main__":
    unittest.main()
