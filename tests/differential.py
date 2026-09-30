#!/usr/bin/env python3
"""Differential checks against test-only Node semver 7.6.1."""

import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import tempfile


NIFT = Path(sys.argv[1] if len(sys.argv) > 1 else "nift").resolve()
PACKAGE = Path(__file__).resolve().parent.parent
TESTS = PACKAGE / "tests"
RANDOM = random.Random(761)


def invoke(command, cwd, *, input_text=None, timeout=60):
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        command, cwd=cwd, input=input_text, stdin=None if input_text is not None else subprocess.DEVNULL,
        capture_output=True, text=True, timeout=timeout, check=False, env=env,
    )


def nift_string(value):
    pieces = []
    current = ""
    for character in value:
        if ord(character) in (11, 12):
            if current:
                pieces.append(json.dumps(current, ensure_ascii=False))
                current = ""
            pieces.append(f'bytes([{ord(character)}]).decode("utf-8")')
        else:
            current += character
    if current or not pieces:
        pieces.append(json.dumps(current, ensure_ascii=False))
    return "(" + " + ".join(pieces) + ")"


oracle_version = invoke(
    ["node", "-e", "console.log(require('semver/package.json').version)"], TESTS,
)
if oracle_version.returncode != 0 or oracle_version.stdout.strip() != "7.6.1":
    raise AssertionError(f"requires Node semver 7.6.1: {oracle_version.stdout!r} {oracle_version.stderr!r}")
print("oracle: node semver " + oracle_version.stdout.strip())

versions = [
    "0.0.0", "1.0.0", "1.2.3", "1.2.3-alpha", "1.2.3-alpha.1", "1.2.3+build.01",
    "1.2.3-alpha+build", "2147483647.0.0", "01.2.3", "1.02.3", "1.2",
    "1.2.3-01", "1.2.3-a_b", "1.2.3+", "1.2.3-", "1.2.3-\u00e9",
]
labels = ["alpha", "beta", "rc", "dev", "a-b", "z"]
for _ in range(350):
    major = RANDOM.randrange(0, 10000)
    minor = RANDOM.randrange(0, 10000)
    patch = RANDOM.randrange(0, 10000)
    value = f"{major}.{minor}.{patch}"
    if RANDOM.randrange(3) == 0:
        identifiers = [RANDOM.choice(labels), str(RANDOM.randrange(0, 1000))]
        value += "-" + ".".join(identifiers[: RANDOM.randrange(1, 3)])
    if RANDOM.randrange(4) == 0:
        value += "+build." + str(RANDOM.randrange(0, 1000)).zfill(3)
    versions.append(value)
    if RANDOM.randrange(5) == 0:
        versions.append("0" + value)

valid_for_compare = [value for value in versions if len(value.encode("utf-8")) <= 256]
pairs = []
for _ in range(500):
    pairs.append([RANDOM.choice(valid_for_compare), RANDOM.choice(valid_for_compare)])

ranges = [
    "*", "x", "X", "1.x", "1.2.x", "~1.2", "~1.2.3", "^1.2.3", "^0.2.3", "^0.0.3",
    "1.2.3", "=1.2.3", ">1.2.3", ">=1.2.3 <2.0.0", "1.2.3 - 2.3.4",
    ">=1.2.3\v<2.0.0", ">=1.2.3\f<2.0.0",
    ">2.0.0 <1.0.0", "=1.2.3-alpha", ">=1.2.3-alpha <1.2.3",
    "not-a-range", "1.2.3-", "(1.2.3)",
]
for _ in range(140):
    a = RANDOM.randrange(0, 20)
    b = RANDOM.randrange(0, 20)
    c = RANDOM.randrange(0, 20)
    choice = RANDOM.randrange(8)
    if choice == 0:
        ranges.append(f">={a}.{b}.{c} <{a + 1}.0.0")
    elif choice == 1:
        ranges.append(f"~{a}.{b}.{c}")
    elif choice == 2:
        ranges.append(f"~{a}.{b}")
    elif choice == 3:
        ranges.append(f"^{a}.{b}.{c}")
    elif choice == 4:
        ranges.append(f"{a}.x")
    elif choice == 5:
        ranges.append(f"{a}.{b}.x")
    elif choice == 6:
        ranges.append(f"{a}.{b}.{c} - {a + 1}.{b}.{c}")
    else:
        ranges.append(f"={a}.{b}.{c}")

candidates = [value for value in versions if not value.startswith("0") or value.startswith("0.")]
candidates = candidates[:180]
cases = []
for range_text in ranges:
    for version in RANDOM.sample(candidates, min(30, len(candidates))):
        cases.append([version, range_text])

payload = {"versions": versions, "pairs": pairs, "ranges": ranges, "cases": cases}
node_program = r'''
const semver = require("semver");
let input = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", chunk => input += chunk);
process.stdin.on("end", () => {
  const p = JSON.parse(input);
  const out = {
    valid: p.versions.map(v => semver.valid(v, {loose:false}) !== null),
    compare: p.pairs.map(([a,b]) => {
      if (semver.valid(a) === null || semver.valid(b) === null) return null;
      return semver.compare(a,b);
    }),
    ranges: p.ranges.map(r => {
      try { return semver.validRange(r, {loose:false}) !== null; } catch (_) { return false; }
    }),
    satisfies: p.cases.map(([v,r]) => {
      try { return semver.satisfies(v,r,{loose:false}); } catch (_) { return false; }
    })
  };
  process.stdout.write(JSON.stringify(out));
});
'''
oracle = invoke(["node", "-e", node_program], TESTS, input_text=json.dumps(payload), timeout=90)
if oracle.returncode != 0:
    raise AssertionError(f"oracle failed: {oracle.stdout!r} {oracle.stderr!r}")
expected = json.loads(oracle.stdout)

work = Path(tempfile.mkdtemp(prefix=".semver-diff-", dir=TESTS))
try:
    lines = ['@import("../../src/semver.f")', "out := []", "values := []"]
    for value in versions:
        lines.append(f"values.push(semver.valid({nift_string(value)}))")
    lines.append("out.push(values)")
    lines.append("values = []")
    for left, right in pairs:
        lines.append(f"values.push(semver.compare({nift_string(left)}, {nift_string(right)}))")
    lines.append("out.push(values)")
    lines.append("values = []")
    for range_text in ranges:
        lines.append(f"values.push(semver.valid_range({nift_string(range_text)}))")
    lines.append("out.push(values)")
    lines.append("values = []")
    for version, range_text in cases:
        lines.append(f"values.push(semver.satisfies({nift_string(version)}, {nift_string(range_text)}))")
    lines.extend(["out.push(values)", "print(out.stringify())"])
    script = work / "corpus.f"
    script.write_text("\n".join(lines) + "\n", encoding="utf-8")
    actual_process = invoke([str(NIFT), script.name, "--no-process"], work, timeout=120)
    if actual_process.returncode != 0:
        raise AssertionError(f"Nift corpus failed: {actual_process.stdout!r} {actual_process.stderr!r}")
    raw_actual = json.loads(actual_process.stdout)
    actual = dict(zip(("valid", "compare", "ranges", "satisfies"), raw_actual))

    # Node accepts larger safe integers than this package. The generated overlap
    # remains <= 10000; explicit package-only int32 and length limits are covered
    # by the native suite and are intentionally excluded from differential claims.
    for key in ("valid", "compare", "ranges", "satisfies"):
        if actual[key] != expected[key]:
            for index, (got, want) in enumerate(zip(actual[key], expected[key])):
                if got != want:
                    source = {"valid": versions, "compare": pairs, "ranges": ranges, "satisfies": cases}[key][index]
                    raise AssertionError(f"{key} mismatch at {index}: {source!r}: got {got!r}, oracle {want!r}")
            raise AssertionError(f"{key} result length differs")

    repeat = invoke([str(NIFT), script.name, "--no-process"], work, timeout=120)
    if repeat.returncode != 0 or (repeat.stdout, repeat.stderr) != (actual_process.stdout, actual_process.stderr):
        raise AssertionError("differential corpus was not deterministic on repetition")

    print(
        "PASS differential: "
        f"versions={len(versions)} comparisons={len(pairs)} ranges={len(ranges)} "
        f"satisfies={len(cases)}"
    )
finally:
    shutil.rmtree(work, ignore_errors=True)
