"""Selection and preservation checks for the evidenced OpenCode retry shape."""
from __future__ import annotations

import copy
import importlib.util
from pathlib import Path
import sys
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "repair_opencode_empty_step.py"
SPEC = importlib.util.spec_from_file_location("repair_opencode_empty_step", SCRIPT)
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


def retry_message():
    return {"info": {"id": "assistant", "role": "assistant"}, "parts": [
        {"id": "empty-start", "type": "step-start"},
        {"id": "empty-reasoning", "type": "reasoning", "text": ""},
        {"id": "good-start", "type": "step-start"},
        {"id": "good-reasoning", "type": "reasoning", "text": "kept reasoning"},
        {"id": "good-tool", "type": "tool", "state": {"status": "completed", "output": "kept"}},
        {"id": "good-finish", "type": "step-finish"},
    ]}


class EmptyRetrySelectionTests(unittest.TestCase):
    def test_selects_only_empty_prefix_and_preserves_useful_step_and_error_message(self):
        rows = [retry_message(), {"info": {"id": "error", "role": "assistant",
                                         "error": {"name": "APIError"}}, "parts": []}]
        original = copy.deepcopy(rows)
        selected = module.select_empty_retry_parts(rows)
        self.assertEqual(selected, [{"message_id": "assistant",
                                     "part_ids": ["empty-start", "empty-reasoning"]}])
        after = copy.deepcopy(rows)
        after[0]["parts"] = after[0]["parts"][2:]
        module.verify_only_selected_removed(rows, after, selected)
        self.assertEqual(rows, original)
        self.assertEqual(after[1], rows[1])
        self.assertEqual(module.select_empty_retry_parts(after), [])

    def test_normal_whitespace_text_tool_or_unfinished_prefix_is_not_selected(self):
        variants = []
        for text in ("useful", " "):
            row = retry_message()
            row["parts"][1]["text"] = text
            variants.append(row)
        row = retry_message()
        row["parts"].insert(2, {"id": "text", "type": "text", "text": ""})
        variants.append(row)
        row = retry_message()
        row["parts"][1] = {"id": "tool", "type": "tool", "state": {"status": "completed"}}
        variants.append(row)
        row = retry_message()
        row["parts"] = row["parts"][:-1]
        variants.append(row)
        for row in variants:
            with self.subTest(parts=row["parts"]):
                self.assertEqual(module.select_empty_retry_parts([row]), [])

    def test_surviving_part_changes_or_extra_deletions_fail_verification(self):
        before = [retry_message()]
        selected = module.select_empty_retry_parts(before)
        for change in ("changed", "deleted"):
            after = copy.deepcopy(before)
            after[0]["parts"] = after[0]["parts"][2:]
            if change == "changed":
                after[0]["parts"][1]["text"] = "changed"
            else:
                after[0]["parts"].pop()
            with self.subTest(change=change), self.assertRaises(RuntimeError):
                module.verify_only_selected_removed(before, after, selected)

    def test_transport_targets_match_while_each_transport_preserves_its_own_content(self):
        exported = [retry_message()]
        exported[0]["parts"][4]["state"]["raw"] = {"transport_only": True}
        api = copy.deepcopy(exported)
        del api[0]["parts"][4]["state"]["raw"]
        selected = module.select_empty_retry_parts(exported)
        module.verify_selected_identity(exported, api, selected)
        after = copy.deepcopy(api)
        after[0]["parts"] = list(reversed(after[0]["parts"][2:]))
        module.verify_only_selected_removed(api, after, selected)
        wrong_target = copy.deepcopy(api)
        wrong_target[0]["parts"][1]["text"] = "changed"
        with self.assertRaises(RuntimeError):
            module.verify_selected_identity(exported, wrong_target, selected)
        after[0]["info"]["role"] = "user"
        with self.assertRaises(RuntimeError):
            module.verify_only_selected_removed(api, after, selected)


if __name__ == "__main__":
    unittest.main()
