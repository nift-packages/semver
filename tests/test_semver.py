#!/usr/bin/env python3
"""Black-box package, facade, limits, and restricted-runtime certification."""

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time


NIFT = Path(sys.argv[1] if len(sys.argv) > 1 else "nift").resolve()
PACKAGE = Path(__file__).resolve().parent.parent
TESTS = PACKAGE / "tests"
SOURCE = PACKAGE / "src" / "semver.f"


def run(args, cwd, timeout=30):
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [str(NIFT), *args], cwd=cwd, stdin=subprocess.DEVNULL,
        capture_output=True, text=True, timeout=timeout, check=False, env=env,
    )


def require(condition, message, result=None):
    if condition:
        return
    if result is not None:
        message += f"\nrc={result.returncode}\nstdout={result.stdout!r}\nstderr={result.stderr!r}"
    raise AssertionError(message)


manifest = json.loads((PACKAGE / "manifest.json").read_text(encoding="ascii"))
require(manifest == {
    "name": "semver",
    "version": "0.1.0",
    "entry": "src/semver.f",
    "description": "Resource-bounded SemVer parsing, precedence, and deterministic ranges",
}, f"unexpected manifest: {manifest!r}")

source = SOURCE.read_text(encoding="ascii")
exports = re.findall(r"^export\(([^)]+)\)$", source, re.MULTILINE)
public = re.findall(r"^    fn\(([A-Za-z_][A-Za-z0-9_]*)\(", source, re.MULTILINE)
private = re.findall(r"^    private fn\(([A-Za-z_][A-Za-z0-9_]*)\(", source, re.MULTILINE)
expected_public = [
    "parse", "valid", "compare", "eq", "lt", "lte", "gt", "gte",
    "valid_range", "satisfies",
]
require(exports == ["semver"], f"sole export differs: {exports!r}")
require(public == expected_public, f"public method inventory differs: {public!r}")
require(len(private) == len(set(private)) and len(private) >= 10, "private helper inventory invalid")
require("run(" not in source and "open(" not in source and "open_bytes(" not in source, "source uses process or resources")
require("dependencies" not in manifest and "resources" not in manifest, "manifest declares dependencies/resources")

work = Path(tempfile.mkdtemp(prefix=".semver-cert-", dir=TESTS))
try:
    direct = work / "direct"
    consumer = work / "consumer"
    direct.mkdir()
    (consumer / ".nift").mkdir(parents=True)
    shutil.copyfile(TESTS / "contract.f", direct / "contract.f")
    direct_source = (direct / "contract.f").read_text(encoding="ascii")
    (direct / "contract.f").write_text(
        '@import("../../../src/semver.f")\n' + direct_source.split("\n", 1)[1],
        encoding="ascii",
    )

    direct_result = run(["contract.f"], direct, 60)
    require(direct_result.returncode == 0 and direct_result.stdout.strip() == "PASS semver contract", "direct import contract failed", direct_result)

    added = run(["add", str(PACKAGE)], consumer)
    require(added.returncode == 0, "fresh nift add failed", added)
    shutil.copyfile(TESTS / "contract.f", consumer / "contract.f")
    installed = run(["contract.f"], consumer, 60)
    require(installed.returncode == 0 and installed.stdout.strip() == "PASS semver contract", "installed contract failed", installed)

    restricted = run(["contract.f", "--no-process"], consumer, 60)
    require(
        restricted.returncode == 0 and
        (restricted.stdout, restricted.stderr) == (installed.stdout, installed.stderr),
        "--no-process contract differs", restricted,
    )

    repeated = run(["contract.f"], consumer, 60)
    require(
        repeated.returncode == 0 and
        (repeated.stdout, repeated.stderr) == (installed.stdout, installed.stderr),
        "repeated execution differs", repeated,
    )

    version_256 = "1.2.3+" + "a" * 64 + "." + "b" * 64 + "." + "c" * 64 + "." + "d" * 55
    structural_tokens_32 = " ".join(["*"] * 32)
    benchmark_source = f'''@import("semver")
version := {json.dumps(version_256)}
range := {json.dumps(structural_tokens_32)}
i := 0
while(i < 250) {{
    if(!semver.valid(version) || !semver.valid_range(range) || !semver.satisfies(version, range)) {{ missing.value }}
    i += 1
}}
print("PASS worst admitted inputs")
'''
    (consumer / "benchmark.f").write_text(benchmark_source, encoding="ascii")
    benchmark_started = time.monotonic()
    benchmark = run(["benchmark.f", "--no-process"], consumer, 30)
    benchmark_seconds = time.monotonic() - benchmark_started
    require(
        benchmark.returncode == 0 and benchmark.stdout.strip() == "PASS worst admitted inputs",
        "worst-admitted-input benchmark failed", benchmark,
    )

    for helper in private:
        path = consumer / f"private-{helper}.f"
        path.write_text(f'@import("semver")\nprint(semver.{helper}("1.2.3"))\n', encoding="ascii")
        hidden = run([path.name], consumer)
        require(hidden.returncode != 0, f"private method exposed: {helper}", hidden)

    for name in ["failure", "allowed", "candidate", "parsed_range", "terms", "semver_parse"]:
        path = consumer / f"scope-{name}.f"
        path.write_text(f'@import("semver")\nprint({name})\n', encoding="ascii")
        hidden = run([path.name], consumer)
        require(hidden.returncode != 0, f"package binding exposed: {name}", hidden)

    malformed_calls = [
        "semver.parse()", "semver.parse(1, 2)", "semver.valid()",
        "semver.compare(\"1.0.0\")", "semver.eq(\"1.0.0\")",
        "semver.valid_range()", "semver.satisfies(\"1.0.0\")",
    ]
    for index, expression in enumerate(malformed_calls):
        path = consumer / f"arity-{index}.f"
        path.write_text(f'@import("semver")\nprint({expression})\n', encoding="ascii")
        rejected = run([path.name], consumer)
        require(rejected.returncode != 0, f"bad arity accepted: {expression}", rejected)

    print("PASS semver package certification")
    print("limits: version=256B range=1024B identifier=64B identifiers=32 structural_tokens=32")
    print(f"worst admitted benchmark: 250 parse/range/satisfies cycles in {benchmark_seconds:.3f}s")
finally:
    shutil.rmtree(work, ignore_errors=True)
