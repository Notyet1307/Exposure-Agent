import assert from "node:assert/strict"
import { spawnSync } from "node:child_process"
import { createHash } from "node:crypto"
import { lstatSync, readFileSync, realpathSync, writeFileSync } from "node:fs"
import { dirname, join, resolve } from "node:path"
import { fileURLToPath } from "node:url"

export const sourcePaths = [
  ".github/workflows/fde-frontend.yml",
  "scripts/fde-frontend-ci.mts",
  "scripts/fde-frontend-ci.test.mts",
  "frontend/playwright.config.ts",
] as const

export const minimumTests = 286
const jobName = "FDE frontend"
const checkNames = [
  "adapter-tests",
  "adapter-types",
  "whitespace",
  "frontend-build",
]
type Counts = {
  name: string
  kind: "tests"
  tests: number
  failures: number
  errors: number
  skipped: number
  expected_failures: number
  unexpected_successes: number
}
type Check = { name: string; kind: "check"; conclusion: "success" | "failure" }
type Source = { path: string; mode: string; oid: string; sha256: string }

function object(value: unknown): Record<string, unknown> {
  assert(
    value !== null && typeof value === "object" && !Array.isArray(value),
    "object required",
  )
  return value as Record<string, unknown>
}

function array(value: unknown): unknown[] {
  assert(Array.isArray(value), "array required")
  return value
}

function integer(value: unknown): number {
  assert(
    typeof value === "number" && Number.isSafeInteger(value) && value >= 0,
    "nonnegative integer required",
  )
  return value
}

export function playwrightCounts(raw: unknown, exitCode: number): Counts {
  const report = object(raw)
  assert.equal(array(report.errors).length, 0, "Playwright global errors")
  const counts: Counts = {
    name: "component",
    kind: "tests",
    tests: 0,
    failures: 0,
    errors: 0,
    skipped: 0,
    expected_failures: 0,
    unexpected_successes: 0,
  }
  function visit(suites: unknown): void {
    for (const item of array(suites)) {
      const suite = object(item)
      for (const value of array(suite.specs)) {
        const tests = array(object(value).tests)
        assert(tests.length > 0, "empty test spec")
        for (const item of tests) {
          const test = object(item)
          assert.equal(
            test.projectName,
            "component",
            "unexpected Playwright project",
          )
          assert.equal(
            test.expectedStatus,
            "passed",
            "skipped or expected-failure test",
          )
          const results = array(test.results)
          assert.equal(results.length, 1, "missing result or retry/flaky test")
          const result = object(results[0])
          assert.equal(result.retry, 0, "retried test")
          assert(
            ["passed", "failed", "timedOut", "interrupted"].includes(
              String(result.status),
            ),
            "skipped or invalid result",
          )
          assert.equal(
            test.status,
            result.status === "passed" ? "expected" : "unexpected",
            "inconsistent test status",
          )
          counts.tests++
          if (result.status === "failed" || result.status === "timedOut")
            counts.failures++
          if (result.status === "interrupted") counts.errors++
        }
      }
      if (suite.suites !== undefined) visit(suite.suites)
    }
  }
  visit(report.suites)
  assert(
    counts.tests >= minimumTests,
    "zero tests or below fixed component baseline",
  )
  const stats = object(report.stats)
  assert.equal(integer(stats.skipped), 0, "skipped tests")
  assert.equal(integer(stats.flaky), 0, "flaky tests")
  assert.equal(
    integer(stats.unexpected),
    counts.failures + counts.errors,
    "unexpected count mismatch",
  )
  assert.equal(
    integer(stats.expected),
    counts.tests - counts.failures - counts.errors,
    "expected count mismatch",
  )
  assert.equal(
    exitCode,
    counts.failures + counts.errors > 0 ? 1 : 0,
    "test exit status disagrees with results",
  )
  return counts
}

function git(repo: string, ...args: string[]): Buffer {
  const env = {
    ...process.env,
    GIT_OPTIONAL_LOCKS: "0",
    GIT_NO_REPLACE_OBJECTS: "1",
    GIT_NO_LAZY_FETCH: "1",
  }
  for (const key of Object.keys(env))
    if (
      key.startsWith("GIT_") &&
      ![
        "GIT_OPTIONAL_LOCKS",
        "GIT_NO_REPLACE_OBJECTS",
        "GIT_NO_LAZY_FETCH",
      ].includes(key)
    )
      delete env[key as keyof typeof env]
  const result = spawnSync("git", ["-C", repo, ...args], {
    env,
    maxBuffer: 4 * 1024 * 1024,
    timeout: 10_000,
  })
  assert.equal(result.status, 0, `Git read failed: ${args[0]}`)
  return result.stdout
}

export function sources(
  trusted: string,
  candidate: string,
  sourceSha: string,
  headSha: string,
): Source[] {
  for (const sha of [sourceSha, headSha])
    assert.match(sha, /^[0-9a-f]{40}$/, "full SHA required")
  assert.equal(
    git(trusted, "rev-parse", "HEAD").toString().trim(),
    sourceSha,
    "CI checkout SHA mismatch",
  )
  assert.equal(
    git(candidate, "rev-parse", "HEAD").toString().trim(),
    headSha,
    "candidate SHA mismatch",
  )
  return sourcePaths.map((path) => {
    const entry = git(trusted, "ls-tree", "HEAD", "--", path).toString().trim()
    const match = /^(100644|100755) blob ([0-9a-f]{40})\t(.+)$/.exec(entry)
    assert(match && match[3] === path, `ordinary CI blob required: ${path}`)
    const [, mode, oid] = match
    const content = git(trusted, "cat-file", "blob", oid)
    assert.equal(
      createHash("sha1")
        .update(`blob ${content.length}\0`)
        .update(content)
        .digest("hex"),
      oid,
    )
    for (const repo of [trusted, candidate]) {
      assert.equal(
        git(repo, "ls-tree", "HEAD", "--", path).toString().trim(),
        entry,
        "CI tree drift",
      )
      let current = repo
      for (const part of path.split("/")) {
        current = join(current, part)
        assert(!lstatSync(current).isSymbolicLink(), "symlink CI source")
      }
      const stat = lstatSync(current)
      assert(
        stat.isFile() && stat.size <= 1024 * 1024,
        "ordinary bounded CI file required",
      )
      assert.equal(
        stat.mode & 0o111 ? "100755" : "100644",
        mode,
        "CI mode drift",
      )
      assert(readFileSync(current).equals(content), "CI bytes drift")
    }
    return {
      path,
      mode,
      oid,
      sha256: createHash("sha256").update(content).digest("hex"),
    }
  })
}

function required(name: string): string {
  const value = process.env[name]
  assert(value, `missing ${name}`)
  return value
}

function identity(trusted: string, candidate: string) {
  const source = required("FDE_SOURCE_SHA")
  const head = required("FDE_HEAD_SHA")
  const workflow = required("GITHUB_WORKFLOW_SHA")
  assert.match(workflow, /^[0-9a-f]{40}$/, "workflow SHA required")
  const positive = (name: string) => {
    const value = required(name)
    assert.match(value, /^[1-9][0-9]*$/)
    return integer(Number(value))
  }
  return {
    schema_version: 1,
    run_id: positive("GITHUB_RUN_ID"),
    run_attempt: positive("GITHUB_RUN_ATTEMPT"),
    job_name: jobName,
    tested_sha: head,
    source_sha: source,
    workflow_sha: workflow,
    sources: sources(trusted, candidate, source, head),
  }
}

export function validateResult(
  raw: unknown,
  expected: ReturnType<typeof identity>,
) {
  const result = object(raw)
  const checks = array(result.checks)
  const { checks: _checks, ...actual } = result
  assert.deepEqual(actual, expected, "report identity/source drift")
  assert.equal(checks.length, checkNames.length + 1, "exact check set required")
  for (const [index, name] of checkNames.entries()) {
    const check = object(checks[index])
    assert.deepEqual(Object.keys(check).sort(), ["conclusion", "kind", "name"])
    assert.equal(check.name, name)
    assert.equal(check.kind, "check")
    assert(["success", "failure"].includes(String(check.conclusion)))
  }
  const tests = object(checks.at(-1))
  assert.deepEqual(Object.keys(tests).sort(), [
    "errors",
    "expected_failures",
    "failures",
    "kind",
    "name",
    "skipped",
    "tests",
    "unexpected_successes",
  ])
  assert.equal(tests.name, "component")
  assert.equal(tests.kind, "tests")
  for (const key of [
    "tests",
    "failures",
    "errors",
    "skipped",
    "expected_failures",
    "unexpected_successes",
  ])
    integer(tests[key])
  assert(
    (tests.tests as number) >= minimumTests &&
      (tests.failures as number) + (tests.errors as number) <=
        (tests.tests as number),
  )
  for (const key of ["skipped", "expected_failures", "unexpected_successes"])
    assert.equal(tests[key], 0)
  return result
}

function runChecks(trusted: string, candidate: string, output: string): number {
  const before = identity(trusted, candidate)
  const base = required("FDE_BASE_SHA")
  assert.match(base, /^[0-9a-f]{40}$/)
  const checks: (Check | Counts)[] = []
  function run(name: string, command: string, args: string[], cwd: string) {
    const execution = spawnSync(command, args, {
      cwd,
      stdio: "inherit",
      env: { ...process.env, NODE_OPTIONS: "", CI: "true" },
      timeout: 600_000,
    })
    const conclusion = execution.status === 0 ? "success" : "failure"
    checks.push({ name, kind: "check", conclusion })
  }
  run(
    "adapter-tests",
    process.execPath,
    [
      "--experimental-strip-types",
      "--test",
      join(trusted, "scripts/fde-frontend-ci.test.mts"),
    ],
    trusted,
  )
  run(
    "adapter-types",
    join(candidate, "node_modules/.bin/tsc"),
    [
      "--noEmit",
      "--strict",
      "--allowImportingTsExtensions",
      "--module",
      "nodenext",
      "--target",
      "es2022",
      "--skipLibCheck",
      "--types",
      "node",
      "--typeRoots",
      join(candidate, "node_modules/@types"),
      ...sourcePaths
        .filter((p) => p.endsWith(".mts"))
        .map((p) => join(trusted, p)),
    ],
    candidate,
  )
  run(
    "whitespace",
    "git",
    ["diff", "--check", base, before.tested_sha],
    candidate,
  )
  run("frontend-build", "bun", ["run", "build"], join(candidate, "frontend"))
  const execution = spawnSync(
    "bunx",
    [
      "playwright",
      "test",
      "--project=component",
      "--workers=1",
      "--retries=0",
      "--fail-on-flaky-tests",
      "--reporter=json",
    ],
    {
      cwd: join(candidate, "frontend"),
      encoding: "utf8",
      maxBuffer: 16 * 1024 * 1024,
      timeout: 600_000,
      env: {
        ...process.env,
        CI: "true",
        NODE_OPTIONS: "",
        PLAYWRIGHT_JSON_OUTPUT_FILE: "",
        PLAYWRIGHT_JSON_OUTPUT_NAME: "",
        PLAYWRIGHT_JSON_OUTPUT_DIR: "",
      },
    },
  )
  process.stderr.write(execution.stderr ?? "")
  assert(execution.status !== null, "Playwright did not complete")
  checks.push(playwrightCounts(JSON.parse(execution.stdout), execution.status))
  assert.deepEqual(
    identity(trusted, candidate),
    before,
    "sources changed during checks",
  )
  const result = validateResult({ ...before, checks }, before)
  writeFileSync(output, JSON.stringify(result))
  return checks.some((check) =>
    check.kind === "tests"
      ? check.failures + check.errors > 0
      : check.conclusion !== "success",
  )
    ? 1
    : 0
}

function main(): void {
  const [mode, candidatePath, output] = process.argv.slice(2)
  assert(
    ["checks", "report"].includes(mode) && candidatePath && output,
    "checks|report CANDIDATE RESULT required",
  )
  const trusted = realpathSync(
    resolve(dirname(fileURLToPath(import.meta.url)), ".."),
  )
  const candidate = realpathSync(resolve(candidatePath))
  if (mode === "checks")
    process.exitCode = runChecks(trusted, candidate, output)
  else {
    const report = validateResult(
      JSON.parse(readFileSync(output, "utf8")),
      identity(trusted, candidate),
    )
    console.log(`FDE_CI_REPORT_V1 ${JSON.stringify(report)}`)
  }
}

if (
  process.argv[1] &&
  fileURLToPath(import.meta.url) === realpathSync(process.argv[1])
) {
  try {
    main()
  } catch (error) {
    console.error(
      `FDE frontend blocked: ${error instanceof Error ? error.message : String(error)}`,
    )
    process.exitCode = 1
  }
}
