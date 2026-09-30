# semver

Strict, deterministic parsing and precedence for a resource-bounded SemVer
2.0.0 syntax subset, plus a deliberately narrow range language for Nift. The
numeric and length limits documented below intentionally make this a subset of
the otherwise unbounded SemVer 2.0.0 syntax. The package has no dependencies,
resources, filesystem access, or process use.

## API

Import the sole `semver` facade:

```f
@import("semver")

parsed := semver.parse("1.2.3-alpha.1+build.7")
print(semver.valid("1.2.3"))
print(semver.compare("1.2.3", "2.0.0"))
print(semver.satisfies("1.5.0", ">=1.2.3 <2.0.0"))
```

Public methods are exactly:

- `parse(text)`
- `valid(text)`
- `compare(a, b)`
- `eq(a, b)`, `lt(a, b)`, `lte(a, b)`, `gt(a, b)`, `gte(a, b)`
- `valid_range(range)`
- `satisfies(version, range)`

`parse` always returns an object with this stable shape:

```text
valid, error, error_code, major, minor, patch, prerelease, build, raw
```

On success, `error` and `error_code` are `null`. On failure, numeric fields are
`null`, identifier arrays are empty, and `raw` is the supplied string (or
`null` for a non-string input). Failures are deterministic. `compare` returns
`-1`, `0`, or `1`, and returns `null` if either argument is not a valid version
string. Predicate methods return `false` on invalid input. Build metadata is
ignored by precedence and equality.

## Version Grammar

Versions implement SemVer 2.0.0 syntax subject to the documented numeric and
length limits:

```text
version = major "." minor "." patch [ "-" prerelease ] [ "+" build ]
identifier = 1*( ASCII digit / ASCII letter / "-" )
```

Core components are decimal integers from `0` through `2147483647`, with no
leading zero. Prerelease numeric identifiers also reject leading zeros. Build
numeric identifiers may contain leading zeros. Loose `v` prefixes, whitespace,
Unicode letters/digits, and partial versions are rejected.

Defensive limits are measured in UTF-8 bytes: 256 bytes per version, 64 bytes
per prerelease/build identifier, and 32 prerelease/build identifiers combined.

## Range Grammar v0.1

A range is one ASCII-whitespace-separated AND comparator set. Supported forms:

```text
1.2.3
=1.2.3
>1.2.3  >=1.2.3  <2.0.0  <=2.0.0
*  x  X
1.x  1.X  1.*
1.2.x  1.2.X  1.2.*
~1.2  ~1.2.3
^1.2.3
1.2.3 - 2.3.4
>=1.2.3 <2.0.0
```

Every full version in a range uses the strict version grammar and may include
prerelease/build metadata. Bare partials such as `1` and `1.2` are rejected.
There is no `||`, comma, tag, parenthesis, loose `v`, spaced comparator, or
other npm shorthand support. A hyphen range is the whole range and requires
full versions at both ends.

Syntactically valid contradictory intersections, such as `>2.0.0 <1.0.0`, are
valid ranges that satisfy no version. `valid_range` checks grammar, limits, and
version validity; it does not solve comparator intersections.

Prerelease gating follows npm AND-set behavior: a prerelease candidate is
eligible only if at least one comparator in the set contains a prerelease
version with the identical major, minor, and patch tuple. Thus an exact
prerelease range works while ordinary stable ranges exclude prereleases.

Ranges are limited to 1,024 UTF-8 bytes and 32 structural tokens in an ordinary
AND set. The fixed full-version hyphen form consists of exactly three tokens
and is handled as its own grammar production. The token cap is not an expanded
comparator count.

## Test

```sh
PYTHONDONTWRITEBYTECODE=1 python3 tests/test_semver.py /tmp/opencode/nift-package-baseline-bed5d1f/nift
PYTHONDONTWRITEBYTECODE=1 python3 tests/differential.py /tmp/opencode/nift-package-baseline-bed5d1f/nift
```

The differential suite requires test-only Node `semver` 7.6.1. Node is never
used by the package at runtime.
