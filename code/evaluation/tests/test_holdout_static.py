"""Static proof that nothing else can unlock the holdout (T96, proposal "Tests" 1).

An AST scan over ``code/`` (every ``tests`` directory excluded). Only the three files in
:data:`UNLOCKERS` may:

* reference ``UNLOCK_PHRASE`` (a name, an attribute, an import, or the string, as in ``getattr``);
* hold the phrase as a string literal (docstrings excepted; matched with case, spaces and
  punctuation removed, so "holdout evaluation run" counts);
* pass ``holdout=`` (anything but False/None), ``holdout_unlock=`` or ``unlock_phrase=``
  (anything but None) to a call, or a true first argument to ``check_unlock``;
* splat keywords (``**``) into ``load_gold``, ``check_unlock``, ``read_output`` or ``run``,
  or import ``check_unlock``/``load_gold`` under another name.

One forwarder is allowed, narrowly: ``evaluation/outputs.py`` may call
``check_unlock(True, unlock_phrase, ...)`` where ``unlock_phrase`` is its own parameter (T47
B1's gold-identity guard). The keyword rule still stops every caller from handing it a phrase.

In ``holdout_run.py`` the phrase reaches the unlock only from argv: no environment access, no
``input``/``stdin``, every unlock value is the keyword-only parameter ``phrase``, ``phrase`` is
never assigned, and it is fed only from ``args.unlock`` where ``args`` comes from
``parse_args``; ``--unlock`` has no default, type or action, and the parser reads no ``@file``.

Each rule is shown to fire on a planted violation in a temporary copy of ``code/``.
"""
from __future__ import annotations

import ast
import re
import shutil
import tempfile
import unittest
from collections.abc import Iterator
from pathlib import Path

CODE = Path(__file__).resolve().parents[2]
UNLOCKERS: frozenset[str] = frozenset({"evaluation/gold.py", "deletion_audit/pipeline.py",
                                       "evaluation/holdout_run.py"})
FORWARDER = "evaluation/outputs.py"
HOLDOUT_RUN = "evaluation/holdout_run.py"
PHRASE_KEY = "HOLDOUTEVALUATIONRUN"
GUARDED_CALLS = frozenset({"load_gold", "check_unlock", "read_output", "run"})
GUARDED_NAMES = frozenset({"UNLOCK_PHRASE", "check_unlock", "holdout_unlock"})
ENV_NAMES = frozenset({"environ", "environb", "getenv", "putenv", "stdin"})


def _norm(s: str) -> str:
    return re.sub(r"[^A-Z]", "", s.upper())


def _docstring_ids(tree: ast.AST) -> set[int]:
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and n.body:
            first = n.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and \
                    isinstance(first.value.value, str):
                out.add(id(first.value))
    return out


def _func_name(call: ast.Call) -> str | None:
    f = call.func
    return f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None


def _is_const(node: ast.AST, *values: object) -> bool:
    return isinstance(node, ast.Constant) and any(type(node.value) is type(v) and node.value == v for v in values)


def source_files(root: Path) -> Iterator[tuple[str, Path]]:
    """(path relative to ``root``, path) for every .py file outside a ``tests`` directory."""
    for p in sorted(root.rglob("*.py")):
        rel = p.relative_to(root)
        if "tests" in rel.parts[:-1] or "__pycache__" in rel.parts or ".venv" in rel.parts:
            continue
        yield rel.as_posix(), p


def unlock_findings(root: Path) -> list[str]:
    """Every unlock-related reference outside the allowed files, as ``path:line: rule``."""
    bad: list[str] = []
    for rel, p in source_files(root):
        tree = ast.parse(p.read_text(encoding="utf-8"))
        docs = _docstring_ids(tree)
        hits: list[tuple[int, str]] = []
        for n in ast.walk(tree):
            line = getattr(n, "lineno", 0)
            if isinstance(n, ast.Name) and n.id == "UNLOCK_PHRASE" or \
                    isinstance(n, ast.Attribute) and n.attr == "UNLOCK_PHRASE":
                hits.append((line, "references UNLOCK_PHRASE"))
            elif isinstance(n, ast.ImportFrom):
                for a in n.names:
                    if a.name == "UNLOCK_PHRASE":
                        hits.append((line, "imports UNLOCK_PHRASE"))
                    if a.name in ("check_unlock", "load_gold") and a.asname not in (None, a.name):
                        hits.append((line, f"imports {a.name} under another name"))
            elif isinstance(n, ast.Constant) and id(n) not in docs and isinstance(n.value, (str, bytes)):
                text = n.value.decode("latin-1") if isinstance(n.value, bytes) else n.value
                if PHRASE_KEY in _norm(text):
                    hits.append((line, "holds the phrase as a literal"))
                if text in GUARDED_NAMES:
                    hits.append((line, f"names {text} in a string"))
            elif isinstance(n, ast.Call):
                name = _func_name(n)
                for kw in n.keywords:
                    if kw.arg == "holdout" and not _is_const(kw.value, False, None):
                        hits.append((line, "passes holdout="))
                    elif kw.arg in ("holdout_unlock", "unlock_phrase") and not _is_const(kw.value, None):
                        hits.append((line, f"passes {kw.arg}="))
                    elif kw.arg is None and name in GUARDED_CALLS:
                        hits.append((line, f"splats keywords into {name}"))
                if name == "check_unlock" and n.args and not _is_const(n.args[0], False, None):
                    forwarded = rel == FORWARDER and len(n.args) > 1 and isinstance(n.args[1], ast.Name) \
                        and n.args[1].id == "unlock_phrase"
                    if not forwarded:
                        hits.append((line, "calls check_unlock with holdout true"))
        if rel not in UNLOCKERS:
            bad += [f"{rel}:{ln}: {why}" for ln, why in hits]
    return sorted(bad)


def phrase_source_findings(path: Path) -> list[str]:
    """Ways the phrase could reach the unlock in ``holdout_run.py`` other than from argv."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    bad: list[str] = []
    unlock_args = 0
    parse_targets = {id(n.targets[0]) for n in ast.walk(tree) if isinstance(n, ast.Assign) and len(n.targets) == 1
                     and isinstance(n.targets[0], ast.Name) and n.targets[0].id == "args"
                     and isinstance(n.value, ast.Call) and _func_name(n.value) == "parse_args"}
    if len(parse_targets) != 1:
        bad.append(f"0: expected exactly one args = ....parse_args(...), found {len(parse_targets)}")
    for n in ast.walk(tree):
        line = getattr(n, "lineno", 0)
        if isinstance(n, ast.Name) and n.id in ENV_NAMES or isinstance(n, ast.Attribute) and n.attr in ENV_NAMES:
            bad.append(f"{line}: environment or stdin access")
        if isinstance(n, ast.Call) and _func_name(n) in ("input", "setattr", "eval", "exec"):
            bad.append(f"{line}: calls {_func_name(n)}")
        if isinstance(n, ast.Call) and _func_name(n) == "vars" and any(
                isinstance(a, ast.Name) and a.id == "args" for a in n.args):
            bad.append(f"{line}: calls vars(args)")
        if isinstance(n, ast.Name) and n.id == "phrase" and isinstance(n.ctx, (ast.Store, ast.Del)):
            bad.append(f"{line}: assigns phrase")
        if isinstance(n, (ast.Global, ast.Nonlocal)) and "phrase" in n.names:
            bad.append(f"{line}: global phrase")
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            positional = [a.arg for a in [*n.args.posonlyargs, *n.args.args]]
            if "phrase" in positional or (n.args.vararg and n.args.vararg.arg == "phrase") or \
                    (n.args.kwarg and n.args.kwarg.arg == "phrase"):
                bad.append(f"{line}: phrase is not a keyword-only parameter")
        if isinstance(n, ast.Name) and n.id == "args" and isinstance(n.ctx, ast.Store) and id(n) not in parse_targets:
            bad.append(f"{line}: assigns args outside an args = ....parse_args(...) statement")
        if isinstance(n, ast.Attribute) and n.attr == "unlock" and isinstance(n.ctx, (ast.Store, ast.Del)):
            bad.append(f"{line}: assigns .unlock")
        if isinstance(n, ast.Call):
            name = _func_name(n)
            values = [kw.value for kw in n.keywords if kw.arg in ("unlock_phrase", "holdout_unlock")]
            if name == "check_unlock" and len(n.args) > 1:
                values.append(n.args[1])
            for v in values:
                if not (isinstance(v, ast.Name) and v.id == "phrase"):
                    bad.append(f"{line}: an unlock value that is not the parameter phrase")
            for kw in n.keywords:
                if kw.arg == "phrase" and not (
                        isinstance(kw.value, ast.Name) and kw.value.id == "phrase"
                        or isinstance(kw.value, ast.Attribute) and kw.value.attr == "unlock"
                        and isinstance(kw.value.value, ast.Name) and kw.value.value.id == "args"):
                    bad.append(f"{line}: phrase= fed from something other than args.unlock")
            if name == "add_argument" and any(_is_const(a, "--unlock") for a in n.args):
                unlock_args += 1
                for kw in n.keywords:
                    if kw.arg in ("default", "type", "action", "nargs", "const", "dest"):
                        bad.append(f"{line}: --unlock has {kw.arg}=")
            if name == "ArgumentParser":
                for kw in n.keywords:
                    if kw.arg in ("fromfile_prefix_chars", "argument_default", "parents"):
                        bad.append(f"{line}: ArgumentParser {kw.arg}=")
                    if kw.arg == "allow_abbrev" and not _is_const(kw.value, False):
                        bad.append(f"{line}: ArgumentParser allows abbreviations")
        if isinstance(n, ast.Compare):
            sides = [n.left, *n.comparators]
            if any(isinstance(s, ast.Name) and s.id == "UNLOCK_PHRASE" for s in sides):
                others = [s for s in sides if not (isinstance(s, ast.Name) and s.id == "UNLOCK_PHRASE")]
                if not all(isinstance(s, ast.Name) and s.id == "phrase" for s in others):
                    bad.append(f"{line}: compares UNLOCK_PHRASE with something other than phrase")
    if unlock_args != 1:
        bad.append(f"0: expected exactly one add_argument('--unlock'), found {unlock_args}")
    return bad


class TestRealTree(unittest.TestCase):
    def test_only_the_three_files_unlock(self) -> None:
        self.assertEqual(unlock_findings(CODE), [])

    def test_holdout_run_takes_the_phrase_from_argv_only(self) -> None:
        self.assertEqual(phrase_source_findings(CODE / HOLDOUT_RUN), [])

    def test_the_scan_covers_the_tree(self) -> None:
        rels = {rel for rel, _ in source_files(CODE)}
        self.assertTrue({"evaluation/gold.py", "evaluation/outputs.py", "evaluation/holdout_run.py",
                         "deletion_audit/pipeline.py", "deletion_audit/__main__.py"} <= rels)
        self.assertFalse(any("/tests/" in f"/{r}" for r in rels))


class TestPlantedViolations(unittest.TestCase):
    """A temporary copy of code/ with one violation planted per test: the scan must catch it."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "code"
        shutil.copytree(CODE, self.root, ignore=self._only_py)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    @staticmethod
    def _only_py(directory: str, names: list[str]) -> list[str]:
        return [n for n in names if n in ("__pycache__", ".venv") or
                (not (Path(directory) / n).is_dir() and not n.endswith(".py"))]

    def plant(self, rel: str, text: str) -> list[str]:
        p = self.root / rel
        p.write_text((p.read_text(encoding="utf-8") if p.exists() else "") + "\n" + text + "\n", encoding="utf-8")
        return unlock_findings(self.root)

    def test_copy_starts_clean(self) -> None:
        self.assertEqual(unlock_findings(self.root), [])

    def test_second_caller_of_load_gold(self) -> None:
        bad = self.plant("deletion_audit/sneaky.py",
                         "from evaluation.gold import load_gold\n\ndef f(p):\n    return load_gold(holdout=True, "
                         "unlock_phrase=p)")
        self.assertTrue(any(b.startswith("deletion_audit/sneaky.py:") and b.endswith("passes holdout=") for b in bad))
        self.assertTrue(any(b.startswith("deletion_audit/sneaky.py:") and b.endswith("passes unlock_phrase=")
                            for b in bad))

    def test_import_of_the_constant(self) -> None:
        bad = self.plant("evaluation/drift.py", "from .gold import UNLOCK_PHRASE as _P")
        self.assertTrue(any("evaluation/drift.py" in b and "imports UNLOCK_PHRASE" in b for b in bad), bad)

    def test_attribute_and_getattr(self) -> None:
        bad = self.plant("evaluation/runs.py", "from . import gold as _g\nP1 = _g.UNLOCK_PHRASE\n"
                         "P2 = vars(_g)['UNLOCK_PHRASE']")
        self.assertTrue(any("references UNLOCK_PHRASE" in b for b in bad), bad)
        self.assertTrue(any("names UNLOCK_PHRASE in a string" in b for b in bad), bad)

    def test_literal_phrase_any_case(self) -> None:
        bad = self.plant("deletion_audit/config.py", "_X = 'holdout  evaluation-run'")
        self.assertTrue(any("deletion_audit/config.py" in b and "literal" in b for b in bad), bad)

    def test_literal_phrase_in_an_f_string_part(self) -> None:
        bad = self.plant("deletion_audit/config.py", "_N = 1\n_Y = f'HOLDOUT EVALUATION RUN{_N}'")
        self.assertTrue(any("literal" in b for b in bad), bad)

    def test_engine_unlock_from_another_file(self) -> None:
        bad = self.plant("deletion_audit/__main__.py",
                         "def _g(p):\n    return run(Path('.'), run_id='x', cases=[], holdout_unlock=p)")
        self.assertTrue(any("deletion_audit/__main__.py" in b and "holdout_unlock=" in b for b in bad), bad)

    def test_check_unlock_true_elsewhere(self) -> None:
        bad = self.plant("evaluation/numbers_md.py",
                         "from .gold import check_unlock\n\ndef _u(p):\n    check_unlock(True, p, 'gold', None)")
        self.assertTrue(any("numbers_md.py" in b and "check_unlock with holdout true" in b for b in bad), bad)

    def test_forwarder_with_another_value_is_caught(self) -> None:
        bad = self.plant(FORWARDER, "def _u2(p):\n    check_unlock(True, p, 'gold', None)")
        self.assertTrue(any(FORWARDER in b and "check_unlock with holdout true" in b for b in bad), bad)

    def test_read_output_with_a_phrase(self) -> None:
        bad = self.plant("evaluation/evaluate.py", "def _r(p, x):\n    return read_output(p, unlock_phrase=x)")
        self.assertTrue(any("evaluate.py" in b and "unlock_phrase=" in b for b in bad), bad)

    def test_splat_and_alias(self) -> None:
        bad = self.plant("evaluation/drift.py", "from .gold import load_gold as _lg\n\ndef _s(kw):\n"
                         "    return _lg(**kw)")
        self.assertTrue(any("under another name" in b for b in bad), bad)
        bad = self.plant("evaluation/drift.py", "def _s2(kw):\n    return load_gold(**kw)")
        self.assertTrue(any("splats keywords into load_gold" in b for b in bad), bad)

    def test_tests_are_excluded(self) -> None:
        bad = self.plant("evaluation/tests/test_x.py", "P = 'HOLDOUT EVALUATION RUN'")
        self.assertEqual(bad, [])


class TestPlantedPhraseSources(unittest.TestCase):
    """A temporary copy of holdout_run.py with one other phrase source planted per test."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.src = (CODE / HOLDOUT_RUN).read_text(encoding="utf-8")
        self.path = Path(self._tmp.name) / "holdout_run.py"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def mutate(self, old: str, new: str) -> list[str]:
        self.assertEqual(self.src.count(old), 1, f"anchor not unique: {old!r}")
        self.path.write_text(self.src.replace(old, new), encoding="utf-8")
        return phrase_source_findings(self.path)

    def test_copy_starts_clean(self) -> None:
        self.path.write_text(self.src, encoding="utf-8")
        self.assertEqual(phrase_source_findings(self.path), [])

    def test_environment_variable(self) -> None:
        bad = self.mutate("ctx = run_checks(inv, phrase=args.unlock,",
                          "import os\n        ctx = run_checks(inv, phrase=os.environ.get('P'),")
        self.assertTrue(any("environment" in b for b in bad), bad)
        self.assertTrue(any("other than args.unlock" in b for b in bad), bad)

    def test_file_read(self) -> None:
        bad = self.mutate("rec = execute(ctx, phrase=args.unlock,", "rec = execute(ctx, phrase=Path('p').read_text(),")
        self.assertTrue(any("other than args.unlock" in b for b in bad), bad)

    def test_reassigned_phrase(self) -> None:
        bad = self.mutate('    """Refuse unless ``phrase`` is exactly',
                          '    phrase = Path("p").read_text()\n    """Refuse unless ``phrase`` is exactly')
        self.assertTrue(any("assigns phrase" in b for b in bad), bad)

    def test_unlock_value_not_the_parameter(self) -> None:
        bad = self.mutate("unlock_phrase=phrase,", "unlock_phrase=UNLOCK_PHRASE,")
        self.assertTrue(any("not the parameter phrase" in b for b in bad), bad)

    def test_default_on_unlock(self) -> None:
        bad = self.mutate('ap.add_argument("--unlock", help=', 'ap.add_argument("--unlock", default="x", help=')
        self.assertTrue(any("--unlock has default=" in b for b in bad), bad)

    def test_fromfile_prefix(self) -> None:
        bad = self.mutate("allow_abbrev=False,", "allow_abbrev=False, fromfile_prefix_chars='@',")
        self.assertTrue(any("fromfile_prefix_chars" in b for b in bad), bad)

    def test_args_from_elsewhere(self) -> None:
        bad = self.mutate("args = build_parser().parse_args(arg_list)",
                          "args = build_parser().parse_args(arg_list)\n    args = load(arg_list)")
        self.assertTrue(any("assigns args" in b for b in bad), bad)

    def test_positional_phrase_parameter(self) -> None:
        bad = self.mutate("def check_phrase(*, phrase: str | None)", "def check_phrase(phrase: str | None)")
        self.assertTrue(any("keyword-only" in b for b in bad), bad)


if __name__ == "__main__":
    unittest.main()
