import assert from "node:assert/strict"
import { spawnSync } from "node:child_process"
import {
  chmodSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  symlinkSync,
  writeFileSync,
} from "node:fs"
import { tmpdir } from "node:os"
import { dirname, join } from "node:path"
import { type TestContext, test } from "node:test"
import { fileURLToPath } from "node:url"
import {
  minimumTests,
  playwrightCounts,
  sourcePaths,
  sources,
  validateResult,
} from "./fde-frontend-ci.mts"

function result() {
  return {
    errors: [],
    stats: { expected: minimumTests, unexpected: 0, skipped: 0, flaky: 0 },
    suites: [
      {
        specs: Array.from({ length: minimumTests }, () => ({
          tests: [
            {
              projectName: "component",
              expectedStatus: "passed",
              status: "expected",
              results: [{ status: "passed", retry: 0 }],
            },
          ],
        })),
      },
    ],
  }
}

test("uses actual nested component results and exact counts", () => {
  const report = result()
  const nested = { ...report, suites: [{ specs: [], suites: report.suites }] }
  assert.deepEqual(playwrightCounts(nested, 0), {
    name: "component",
    kind: "tests",
    tests: minimumTests,
    failures: 0,
    errors: 0,
    skipped: 0,
    expected_failures: 0,
    unexpected_successes: 0,
  })
})

test("retains a real failure for native failed-job evidence", () => {
  const report = result()
  report.suites[0].specs[0].tests[0].results[0].status = "failed"
  report.suites[0].specs[0].tests[0].status = "unexpected"
  report.stats.expected--
  report.stats.unexpected++
  assert.equal(playwrightCounts(report, 1).failures, 1)
  assert.throws(() => playwrightCounts(report, 0), /exit status/)
})

for (const [label, change] of [
  [
    "zero tests",
    (r: ReturnType<typeof result>) => {
      r.suites = []
      r.stats.expected = 0
    },
  ],
  [
    "below baseline",
    (r: ReturnType<typeof result>) => {
      r.suites[0].specs.pop()
      r.stats.expected--
    },
  ],
  [
    "skip",
    (r: ReturnType<typeof result>) => {
      r.suites[0].specs[0].tests[0].results[0].status = "skipped"
    },
  ],
  [
    "expected failure",
    (r: ReturnType<typeof result>) => {
      r.suites[0].specs[0].tests[0].expectedStatus = "failed"
    },
  ],
  [
    "flaky",
    (r: ReturnType<typeof result>) => {
      r.stats.flaky = 1
    },
  ],
  [
    "retry",
    (r: ReturnType<typeof result>) => {
      r.suites[0].specs[0].tests[0].results[0].retry = 1
    },
  ],
  [
    "multiple attempts",
    (r: ReturnType<typeof result>) => {
      r.suites[0].specs[0].tests[0].results.push({ status: "passed", retry: 1 })
    },
  ],
  [
    "missing result",
    (r: ReturnType<typeof result>) => {
      r.suites[0].specs[0].tests[0].results = []
    },
  ],
  [
    "wrong project",
    (r: ReturnType<typeof result>) => {
      r.suites[0].specs[0].tests[0].projectName = "chromium"
    },
  ],
  [
    "inconsistent totals",
    (r: ReturnType<typeof result>) => {
      r.stats.expected++
    },
  ],
  [
    "invalid status",
    (r: ReturnType<typeof result>) => {
      r.suites[0].specs[0].tests[0].results[0].status = "unknown"
    },
  ],
] as const) {
  test(`rejects ${label}`, () => {
    const r = result()
    change(r)
    assert.throws(() => playwrightCounts(r, 0))
  })
}

test("rejects incomplete, global-error and non-JSON reports", () => {
  for (const raw of [
    null,
    {},
    { ...result(), errors: [{ message: "worker crashed" }] },
    { ...result(), stats: {} },
  ]) {
    assert.throws(() => playwrightCounts(raw, 0))
  }
  assert.throws(() => JSON.parse("incomplete report"))
  assert.throws(() => playwrightCounts(result(), 1), /exit status/)
})

function git(repo: string, ...args: string[]) {
  const r = spawnSync("git", ["-C", repo, ...args], { encoding: "utf8" })
  assert.equal(r.status, 0, r.stderr)
  return r.stdout.trim()
}

function fixture(t: TestContext) {
  const root = mkdtempSync(join(tmpdir(), "fde-frontend-test-"))
  t.after(() => rmSync(root, { recursive: true, force: true }))
  const trusted = join(root, "approved-ci")
  const candidate = join(root, "candidate")
  mkdirSync(trusted)
  git(trusted, "init", "-q")
  git(trusted, "config", "user.email", "ci@example.invalid")
  git(trusted, "config", "user.name", "CI fixture")
  git(
    trusted,
    "-c",
    "commit.gpgsign=false",
    "commit",
    "--allow-empty",
    "-qm",
    "Before CI",
  )
  const bootstrapBase = git(trusted, "rev-parse", "HEAD")
  const original = join(dirname(fileURLToPath(import.meta.url)), "..")
  for (const path of sourcePaths) {
    mkdirSync(dirname(join(trusted, path)), { recursive: true })
    writeFileSync(join(trusted, path), readFileSync(join(original, path)))
  }
  git(trusted, "add", ".")
  git(trusted, "-c", "commit.gpgsign=false", "commit", "-qm", "CI source")
  git(root, "clone", "-q", "--no-hardlinks", trusted, candidate)
  const sha = git(trusted, "rev-parse", "HEAD")
  const identity = {
    schema_version: 1,
    run_id: 12,
    run_attempt: 1,
    job_name: "FDE frontend",
    tested_sha: sha,
    source_sha: sha,
    workflow_sha: sha,
    sources: sources(trusted, candidate, sha, sha),
  }
  const report = {
    ...identity,
    checks: [
      ...["adapter-tests", "adapter-types", "whitespace", "frontend-build"].map(
        (name) => ({ name, kind: "check", conclusion: "success" }),
      ),
      playwrightCounts(result(), 0),
    ],
  }
  return { root, trusted, candidate, sha, bootstrapBase, identity, report }
}

test("binds raw bytes, mode and Git blob identity at both checkouts", (t) => {
  const f = fixture(t)
  assert.equal(f.identity.sources.length, sourcePaths.length)
  assert(f.identity.sources.every((s) => /^[0-9a-f]{64}$/.test(s.sha256)))
  assert.throws(
    () => sources(f.trusted, f.candidate, "a".repeat(40), f.sha),
    /CI checkout SHA/,
  )
  assert.throws(
    () => sources(f.trusted, f.candidate, f.sha, "b".repeat(40)),
    /candidate SHA/,
  )
})

for (const target of ["trusted", "candidate"] as const) {
  test(`rejects dirty ${target} source`, (t) => {
    const f = fixture(t)
    writeFileSync(join(f[target], sourcePaths[1]), "changed")
    assert.throws(
      () => sources(f.trusted, f.candidate, f.sha, f.sha),
      /bytes drift/,
    )
  })
}

test("rejects symlink, missing file and mode changes", (t) => {
  const f = fixture(t)
  const path = join(f.candidate, sourcePaths[1])
  const raw = readFileSync(path)
  rmSync(path)
  assert.throws(() => sources(f.trusted, f.candidate, f.sha, f.sha))
  symlinkSync(join(f.trusted, sourcePaths[1]), path)
  assert.throws(() => sources(f.trusted, f.candidate, f.sha, f.sha), /symlink/)
  rmSync(path)
  writeFileSync(path, raw)
  chmodSync(path, 0o755)
  assert.throws(
    () => sources(f.trusted, f.candidate, f.sha, f.sha),
    /mode drift/,
  )
})

test("requires exact report identity, checks and zero-skip counters", (t) => {
  const f = fixture(t)
  assert.deepEqual(validateResult(f.report, f.identity), f.report)
  for (const key of [
    "tested_sha",
    "source_sha",
    "workflow_sha",
    "run_id",
    "run_attempt",
    "sources",
  ]) {
    assert.throws(() =>
      validateResult({ ...f.report, [key]: null }, f.identity),
    )
  }
  assert.throws(() => validateResult({ ...f.report, checks: [] }, f.identity))
  assert.throws(() =>
    validateResult(
      { ...f.report, checks: [...f.report.checks, f.report.checks[0]] },
      f.identity,
    ),
  )
  for (const key of ["skipped", "expected_failures", "unexpected_successes"]) {
    const checks = [
      ...f.report.checks.slice(0, -1),
      { ...f.report.checks.at(-1), [key]: 1 },
    ]
    assert.throws(() => validateResult({ ...f.report, checks }, f.identity))
  }
})

test("independent report step fails on missing result and rechecks source drift", (t) => {
  const f = fixture(t)
  const output = join(f.root, "result.json")
  const report = () =>
    spawnSync(
      process.execPath,
      [
        "--experimental-strip-types",
        join(f.trusted, sourcePaths[1]),
        "report",
        f.candidate,
        output,
      ],
      {
        encoding: "utf8",
        env: {
          ...process.env,
          FDE_SOURCE_SHA: f.sha,
          FDE_HEAD_SHA: f.sha,
          GITHUB_RUN_ID: "12",
          GITHUB_RUN_ATTEMPT: "1",
          GITHUB_WORKFLOW_SHA: f.sha,
        },
      },
    )
  assert.equal(report().status, 1)
  writeFileSync(output, "broken JSON")
  assert.equal(report().status, 1)
  writeFileSync(output, JSON.stringify(f.report))
  const valid = report()
  assert.equal(valid.status, 0, valid.stderr)
  assert.equal(valid.stdout.split("FDE_CI_REPORT_V1 ").length, 2)
  assert.deepEqual(
    JSON.parse(valid.stdout.trim().slice("FDE_CI_REPORT_V1 ".length)),
    f.report,
  )
  writeFileSync(join(f.candidate, sourcePaths[3]), "changed after checks")
  assert.equal(report().status, 1)
  assert(!report().stdout.includes("FDE_CI_REPORT_V1 "))
})

test("selects base for feature changes and labels CI changes as head-source self-checks", (t) => {
  const f = fixture(t)
  const workflow = readFileSync(join(f.trusted, sourcePaths[0]), "utf8")
  const script = workflow.split("run: |\n")[1].split("      - name:")[0]
  const output = join(f.root, "source-output")
  const select = (base: string, head: string) => {
    writeFileSync(output, "")
    const r = spawnSync("bash", ["-e", "-c", script], {
      cwd: f.root,
      encoding: "utf8",
      env: {
        ...process.env,
        BASE_SHA: base,
        HEAD_SHA: head,
        GITHUB_OUTPUT: output,
      },
    })
    return { ...r, selected: readFileSync(output, "utf8").trim() }
  }
  assert.equal(select(f.bootstrapBase, f.sha).selected, `sha=${f.sha}`)
  writeFileSync(join(f.candidate, "feature.txt"), "feature")
  const commit = () => {
    git(f.candidate, "add", ".")
    git(
      f.candidate,
      "-c",
      "user.name=CI fixture",
      "-c",
      "user.email=ci@example.invalid",
      "-c",
      "commit.gpgsign=false",
      "commit",
      "-qm",
      "Candidate",
    )
    return git(f.candidate, "rev-parse", "HEAD")
  }
  const feature = commit()
  assert.equal(select(f.sha, feature).selected, `sha=${f.sha}`)
  assert.deepEqual(
    sources(f.trusted, f.candidate, f.sha, feature),
    f.identity.sources,
  )
  writeFileSync(join(f.candidate, sourcePaths[0]), `${workflow}\n`)
  const changed = commit()
  assert.equal(select(f.sha, changed).selected, `sha=${changed}`)
  assert.throws(
    () => sources(f.trusted, f.candidate, f.sha, changed),
    /CI tree drift/,
  )
  assert.notEqual(select("a".repeat(40), changed).status, 0)
})

test("workflow has one static job, unique safe steps and an independent final report", () => {
  const workflow = readFileSync(
    join(
      dirname(fileURLToPath(import.meta.url)),
      "../.github/workflows/fde-frontend.yml",
    ),
    "utf8",
  )
  const names = [...workflow.matchAll(/^ {6}- name: (.+)$/gm)].map((m) => m[1])
  assert.equal(names.length, 9)
  assert.equal(new Set(names).size, names.length)
  assert(names.every((name) => !/[\\/]/.test(name)))
  assert.equal(names.at(-1), "Project report")
  assert.match(workflow, /- name: Project report\n {8}if: always\(\)/)
  for (const path of sourcePaths) assert(workflow.includes(path))
})
