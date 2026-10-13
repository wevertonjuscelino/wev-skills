from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from wev_skills import i18n, schema
from wev_skills.core.errors import NotFound, ValidationError
from wev_skills.evaluation import configs as eval_configs
from wev_skills.evaluation import tasks as eval_tasks


def task_data(**overrides: Any) -> dict[str, Any]:
    """A minimal valid task document; ``overrides`` replace top-level keys."""
    data: dict[str, Any] = {
        "id": "sample",
        "title": "Sample task",
        "category": "simple-fix",
        "signals": {"objective": "Do a small thing", "files_touched_estimate": 1},
        "window_tokens": 4000,
        "acceptance_criteria": [{"id": "c1", "text": "The thing works."}],
        "subtasks": [{"id": "s"}],
        "script": [
            {"id": "read", "subtask": "s", "kind": "tool_output", "tokens": 100},
            {"id": "check", "subtask": "s", "kind": "verify", "signature": "t", "criteria": ["c1"]},
        ],
    }
    data.update(copy.deepcopy(overrides))
    return data


def with_step(step: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    """The minimal task with ``step`` inserted before its verify step."""
    base = task_data(**overrides)
    base["script"] = [base["script"][0], {"subtask": "s", **step}, base["script"][1]]
    return base


class SchemaTests(unittest.TestCase):
    def test_minimal_task_is_valid(self) -> None:
        task = eval_tasks.parse_task(task_data())
        self.assertEqual(task.id, "sample")
        self.assertEqual([step.id for step in task.steps_for("s")], ["read", "check"])
        self.assertEqual(task.script[0].conditions.pass_from_attempt, 1)

    def test_schema_rejects_malformed_documents(self) -> None:
        bad_step = {"id": "x", "subtask": "s", "kind": "think"}
        cases = {
            "missing script": {k: v for k, v in task_data().items() if k != "script"},
            "unknown category": task_data(category="refactor"),
            "extra key": task_data(surprise=True),
            "zero window": task_data(window_tokens=0),
            "empty criteria": task_data(acceptance_criteria=[]),
            "bad step kind": task_data(script=[bad_step]),
            "bad id": task_data(id="has space"),
            "bad tier": with_step(
                {"id": "n", "kind": "note", "tokens": 5, "conditions": {"min_tier": "huge"}}
            ),
            "signals without objective": task_data(signals={"unknowns": 1}),
        }
        for name, document in cases.items():
            with self.subTest(name), self.assertRaises(ValidationError) as caught:
                eval_tasks.parse_task(document)
            self.assertEqual(caught.exception.code, "schema_validation_failed", name)

    def test_schema_file_uses_only_supported_keywords(self) -> None:
        self.assertEqual(schema.validate(task_data(), schema.load("eval-task")), [])


class SemanticTests(unittest.TestCase):
    def setUp(self) -> None:
        english = i18n.use_language("en")
        english.__enter__()
        self.addCleanup(english.__exit__, None, None, None)

    def assert_problem(self, document: dict[str, Any], fragment: str) -> None:
        with self.assertRaises(ValidationError) as caught:
            eval_tasks.parse_task(document)
        self.assertEqual(caught.exception.code, "invalid_eval_task")
        errors = caught.exception.details["errors"]
        self.assertTrue(any(fragment in error for error in errors), errors)

    def test_each_step_rule(self) -> None:
        cases = {
            "needs a positive 'tokens'": {"id": "n", "kind": "note"},
            "needs a 'signature'": {"id": "n", "kind": "command"},
            "must name at least one criterion": {"id": "n", "kind": "verify", "signature": "x"},
            "only a verify step may": {"id": "n", "kind": "note", "tokens": 5, "criteria": ["c1"]},
            "needs 'from_agent' and 'to_agent'": {"id": "n", "kind": "handoff", "to_agent": "b"},
            "cannot declare a failing outcome": {"id": "n", "kind": "edit", "outcome": "fail"},
            "cannot repeat": {"id": "n", "kind": "note", "tokens": 5, "repeat": 2},
            "only a command step may": {"id": "n", "kind": "edit", "polling": True},
            "adds nothing to the context": {"id": "n", "kind": "edit", "needed_later": True},
            "names unknown criterion": {
                "id": "n",
                "kind": "verify",
                "signature": "x",
                "criteria": ["nope"],
            },
            "not an earlier 'needed_later' step": {
                "id": "n",
                "kind": "edit",
                "conditions": {"requires_verbatim": ["read"]},
            },
            "no later step of its subtask requires it": {
                "id": "n",
                "kind": "note",
                "tokens": 5,
                "needed_later": True,
            },
        }
        for fragment, step in cases.items():
            with self.subTest(fragment):
                self.assert_problem(with_step(step), fragment)

    def test_structure_rules(self) -> None:
        two = [{"id": "s"}, {"id": "other"}]
        cycle = [{"id": "s", "depends_on": ["other"]}, {"id": "other", "depends_on": ["s"]}]
        step = {"id": "more", "subtask": "other", "kind": "edit"}
        self.assert_problem(task_data(subtasks=two), "Subtask other has no step")
        stray = {"id": "n", "kind": "edit", "subtask": "ghost"}
        self.assert_problem(with_step(stray), "unknown subtask")
        self.assert_problem(with_step({"id": "read", "kind": "edit"}), "Duplicate step id(s): read")
        dangling = [{"id": "s", "depends_on": ["x"]}]
        self.assert_problem(task_data(subtasks=dangling), "unknown task x")
        document = task_data(subtasks=cycle)
        document["script"] = [*document["script"], step]
        self.assert_problem(document, "dependency cycle")
        criteria = [{"id": "c1", "text": "a"}, {"id": "c2", "text": "b"}]
        document = task_data(acceptance_criteria=criteria)
        self.assert_problem(document, "Criterion c2 is not supported")

    def test_requirement_on_a_needed_earlier_step_is_valid(self) -> None:
        document = task_data()
        document["script"][0]["needed_later"] = True
        document["script"][1]["conditions"] = {"requires_verbatim": ["read"]}
        task = eval_tasks.parse_task(document)
        self.assertEqual(task.script[1].conditions.requires_verbatim, ("read",))


class LoadingTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def test_shipped_tasks_cover_every_category(self) -> None:
        shipped = eval_tasks.load_tasks(eval_tasks.EVALS_DIR / eval_tasks.TASKS_SUBDIR)
        self.assertGreaterEqual(len(shipped), 6)
        self.assertEqual({task.category for task in shipped}, set(eval_tasks.CATEGORIES))

    def test_missing_unreadable_and_empty_sources(self) -> None:
        with self.assertRaises(NotFound):
            eval_tasks.load_task(self.root / "nope.json")
        (self.root / "bad.json").write_text("{not json")
        with self.assertRaises(ValidationError) as caught:
            eval_tasks.load_task(self.root / "bad.json")
        self.assertEqual(caught.exception.code, "invalid_json")
        with self.assertRaises(NotFound):
            eval_tasks.load_tasks(self.root / "missing-dir")
        empty = self.root / "empty"
        empty.mkdir()
        with self.assertRaises(NotFound) as none:
            eval_tasks.load_tasks(empty)
        self.assertEqual(none.exception.code, "no_eval_tasks")

    def test_duplicate_task_ids_across_files(self) -> None:
        for name in ("a.json", "b.json"):
            (self.root / name).write_text(json.dumps(task_data()))
        with self.assertRaises(ValidationError) as caught:
            eval_tasks.load_tasks(self.root)
        self.assertEqual(caught.exception.code, "duplicate_eval_task")

    def test_evals_dir_absent_is_not_found(self) -> None:
        with self.assertRaises(NotFound) as caught:
            eval_tasks.resolve_evals_dir(self.root / "no-evals")
        self.assertEqual(caught.exception.code, "evals_dir_not_found")
        self.assertEqual(eval_tasks.resolve_evals_dir(self.root), self.root)


class ConfigTests(unittest.TestCase):
    def test_defaults_merge_into_every_entry(self) -> None:
        loaded = eval_configs.parse_configs(
            {
                "defaults": {"max_attempts": 5, "guard": {"max_identical_commands": 9}},
                "configs": [{"id": "a"}, {"id": "b", "max_attempts": 1, "planning": "off"}],
            }
        )
        self.assertEqual([c.max_attempts for c in loaded], [5, 1])
        self.assertEqual(loaded[1].planning, "off")
        self.assertEqual(loaded[0].guard.max_identical_commands, 9)
        self.assertEqual(loaded[0].guard.budget_units, eval_configs.DEFAULT_SIMULATED_BUDGET)
        self.assertEqual(loaded[1].guard_limits().max_attempts, 1)

    def test_shipped_configs_realize_the_required_comparisons(self) -> None:
        path = eval_tasks.EVALS_DIR / eval_tasks.CONFIGS_FILE
        by_id = {config.id: config for config in eval_configs.load_configs(path)}
        self.assertEqual({c.planning for c in by_id.values()}, {"on", "off", "auto"})
        self.assertEqual(
            {c.context_policy for c in by_id.values()}, set(eval_configs.CONTEXT_POLICIES)
        )
        self.assertEqual({c.routing for c in by_id.values()}, {"policy", "fixed"})
        self.assertEqual({c.max_parallel for c in by_id.values()}, {1, 3})
        self.assertTrue({1, 2, 4} <= {c.max_attempts for c in by_id.values()})

    def test_invalid_configs(self) -> None:
        cases = {
            "planning": {"id": "x", "planning": "sometimes"},
            "policy": {"id": "x", "context_policy": "truncate"},
            "thresholds": {"id": "x", "elide_at": 0.9, "summarize_at": 0.5},
            "attempts": {"id": "x", "max_attempts": 0},
            "fixed without tier": {"id": "x", "routing": "fixed"},
            "policy with tier": {"id": "x", "fixed_tier": "premium"},
            "unknown tier": {"id": "x", "routing": "fixed", "fixed_tier": "huge"},
            "unknown key": {"id": "x", "temperature": 0},
            "bad id": {"id": "has space"},
        }
        for name, entry in cases.items():
            with self.subTest(name), self.assertRaises(ValidationError):
                eval_configs.parse_configs({"configs": [entry]})

    def test_invalid_file_shapes_and_duplicates(self) -> None:
        for shape in ([], {"configs": []}, {"configs": ["x"]}, {"configs": [{"id": "a"}], "x": 1}):
            with self.subTest(shape=shape), self.assertRaises(ValidationError) as caught:
                eval_configs.parse_configs(shape)
            self.assertEqual(caught.exception.code, "invalid_eval_configs")
        with self.assertRaises(ValidationError) as dup:
            eval_configs.parse_configs({"configs": [{"id": "a"}, {"id": "a"}]})
        self.assertEqual(dup.exception.code, "duplicate_eval_config")

    def test_stub_summarizer_truncates_and_says_it_is_a_stub(self) -> None:
        summary = eval_configs.StubSummarizer().summarize(["a" * 500, "b" * 500])
        self.assertIn("stub summary of 2 items", summary)
        self.assertLess(len(summary), 250)


if __name__ == "__main__":
    unittest.main()
