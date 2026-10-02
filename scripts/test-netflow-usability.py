#!/usr/bin/env python3
"""Disposable real NetFlow usability runtime harness."""

from __future__ import annotations
import argparse, json, os, secrets, shutil, socket, subprocess, sys, tempfile, time
from pathlib import Path

DEFAULT_REPO = Path(__file__).resolve().parents[1]
CONTROLLER = "chaitin/agent-compose@sha256:092f8c4fbf7254ddd200a36d99ae6583cd08f5ddeda9cafd559b3636890c9670"


def port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def env(values):
    # No customer, model, proxy or application configuration is inherited.
    system_keys = (
        "PATH",
        "HOME",
        "USER",
        "SHELL",
        "TMPDIR",
        "DOCKER_HOST",
        "DOCKER_CONTEXT",
        "DOCKER_CONFIG",
    )
    return {
        **{key: os.environ[key] for key in system_keys if key in os.environ},
        **values,
    }


class Run:
    def __init__(self, repo, evidence, keep):
        self.repo, self.evidence, self.keep = repo.resolve(), evidence.resolve(), keep
        self.artifacts, self.data = (
            self.evidence / "artifacts",
            self.evidence / "controller-data",
        )
        self.log, self.names, self.procs = self.evidence / "harness.log", [], []
        self.ident = secrets.token_hex(5)
        self.network = f"nf-usability-{self.ident}"
        self.host_cwd = self.evidence / "host"
        self.ui_cwd = self.evidence / "ui"
        self.sha = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=self.repo, text=True
        ).strip()
        self.ports = {x: port() for x in ("db", "controller", "octobus", "api", "ui")}
        self.v = {
            "POSTGRES_DB": f"nf_{self.ident}",
            "POSTGRES_USER": "netflow",
            "POSTGRES_PASSWORD": secrets.token_hex(24),
            "SECRET_KEY": secrets.token_hex(32),
            "FIRST_SUPERUSER": f"netflow-{self.ident}@example.com",
            "FIRST_SUPERUSER_PASSWORD": secrets.token_urlsafe(24),
            "PROJECT_NAME": "NetFlow usability isolated test",
            "AGENT_COMPOSE_AUTH_TOKEN": secrets.token_urlsafe(24),
            "CLOUDATLAS_ASSETS_CAPSET_TOKEN": secrets.token_urlsafe(24),
            "FIXTURE_CLOUDATLAS_TOKEN": secrets.token_urlsafe(24),
            "RUNNER_IMAGE": f"nf-usability-runner:{self.sha}",
            "OCTOBUS_IMAGE": f"nf-usability-octobus:{self.sha}",
            "RUNNER_BUILD_VERSION": self.sha,
            "NETFLOW_MAX_BYTES": "52428800",
            **{f"{x.upper()}_PORT": str(y) for x, y in self.ports.items()},
            "ARTIFACT_ROOT": str(self.artifacts),
            "DATA_ROOT": str(self.data),
        }
        self.environment = env(self.v)

    def run(self, cmd, cwd=None, environment=None):
        with self.log.open("ab") as out:
            out.write(("$ " + cmd[0] + " [arguments redacted]\n").encode())
            out.flush()
            r = subprocess.run(
                cmd,
                cwd=cwd or self.repo,
                env=environment or self.environment,
                stdout=out,
                stderr=subprocess.STDOUT,
            )
        if r.returncode:
            raise RuntimeError(f"failed ({r.returncode}): {cmd[0]}; see {self.log}")

    def docker(self, *args):
        self.run(["docker", *args])

    def start(self, cmd, cwd, logfile, environment):
        with logfile.open("wb") as out:
            self.procs.append(
                subprocess.Popen(
                    cmd, cwd=cwd, env=environment, stdout=out, stderr=subprocess.STDOUT
                )
            )

    def wait(self, url, seconds=60):
        import urllib.request

        until = time.monotonic() + seconds
        while time.monotonic() < until:
            try:
                if urllib.request.urlopen(url, timeout=2).status < 500:
                    return
            except OSError:
                pass
            time.sleep(1)
        raise RuntimeError(f"timeout: {url}; see {self.log}")

    def prep(self):
        for p in (self.evidence, self.artifacts, self.data, self.host_cwd, self.ui_cwd):
            p.mkdir(parents=True, exist_ok=True)
            p.chmod(0o700)
        secret = self.evidence / "e2e-env.json"
        secret.write_text(json.dumps(self.v, indent=2) + "\n")
        secret.chmod(0o600)
        (self.evidence / "ui-port").write_text(self.v["UI_PORT"] + "\n")
        (self.evidence / "upstream.py").write_text(
            (self.repo / "scripts/fixtures/netflow_usability_upstream.py").read_text()
        )
        # Keep Vite's dotenv lookup inside our empty, private UI directory.
        for name in (
            "src",
            "public",
            "index.html",
            "package.json",
            "tsconfig.json",
            "tsconfig.build.json",
            "vite.config.ts",
        ):
            target = self.repo / "frontend" / name
            if target.exists():
                if name == "vite.config.ts":
                    (self.ui_cwd / name).write_text(target.read_text())
                else:
                    (self.ui_cwd / name).symlink_to(
                        target, target_is_directory=target.is_dir()
                    )
        (self.ui_cwd / "node_modules").symlink_to(
            self.repo / "node_modules", target_is_directory=True
        )
        init = self.evidence / "init-octobus.sh"
        init.write_text("""#!/bin/sh
set -eu
octobus --addr http://octobus:9000 service import cloudatlas-assets /opt/exposure-agent/service-packages/cloudatlas-assets >/dev/null
printf '{"token":"%s"}' "$FIXTURE_CLOUDATLAS_TOKEN" | octobus --addr http://octobus:9000 instance create nu279-assets --service cloudatlas-assets --config-json '{"baseUrl":"https://upstream:8443/openapi/","spaceId":"279"}' --secret - >/dev/null
octobus --addr http://octobus:9000 capset create nu279-assets --name UsabilitySynthetic >/dev/null
octobus --addr http://octobus:9000 capset add-instance nu279-assets nu279-assets --no-all-methods >/dev/null
for method in ListIPAssets ListPortServices; do octobus --addr http://octobus:9000 capset select-method nu279-assets nu279-assets "/cloudatlas.assets.v1.CloudAtlasAssetsService/$method" >/dev/null; done
printf '%s' "$CLOUDATLAS_ASSETS_CAPSET_TOKEN" | octobus --addr http://octobus:9000 capset add-token nu279-assets fixture --name usability --token-stdin
""")
        init.chmod(0o700)
        self.agents()
        (self.evidence / "agents.yml").chmod(0o600)
        tls = self.evidence / "tls"
        tls.mkdir()
        self.run(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-days",
                "1",
                "-subj",
                "/CN=upstream",
                "-addext",
                "subjectAltName=DNS:upstream",
                "-keyout",
                str(tls / "key.pem"),
                "-out",
                str(tls / "cert.pem"),
            ],
            self.evidence,
        )

    def agents(self):
        v = self.v
        common = f"""      SECRET_KEY:
        value: {v["SECRET_KEY"]}
        secret: true
      FIRST_SUPERUSER: {v["FIRST_SUPERUSER"]}
      FIRST_SUPERUSER_PASSWORD:
        value: {v["FIRST_SUPERUSER_PASSWORD"]}
        secret: true
      POSTGRES_SERVER: host.docker.internal
      POSTGRES_PORT: '{v["DB_PORT"]}'
      POSTGRES_DB: {v["POSTGRES_DB"]}
      POSTGRES_USER: {v["POSTGRES_USER"]}
      POSTGRES_PASSWORD:
        value: {v["POSTGRES_PASSWORD"]}
        secret: true
      AGENT_COMPOSE_URL: http://host.docker.internal:{v["CONTROLLER_PORT"]}
      AGENT_COMPOSE_AUTH_TOKEN:
        value: {v["AGENT_COMPOSE_AUTH_TOKEN"]}
        secret: true
      AGENT_COMPOSE_PROJECT_NAME: nf-usability
      RUNNER_BUILD_VERSION: {self.sha}
      NETFLOW_MAX_BYTES: 52428800
"""
        (self.evidence / "agents.yml").write_text(f"""name: nf-usability
agents:
  cloudatlas-sync:
    provider: codex
    image: {v["RUNNER_IMAGE"]}
    driver: {{docker: {{}}}}
    env:
      PROJECT_NAME: NetFlow usability isolated test
      ENVIRONMENT: local
      OCTOBUS_URL: http://host.docker.internal:{v["OCTOBUS_PORT"]}
      CLOUDATLAS_ASSETS_CAPSET_TOKEN:
        value: {v["CLOUDATLAS_ASSETS_CAPSET_TOKEN"]}
        secret: true
{common}  netflow-processor:
    provider: codex
    image: {v["RUNNER_IMAGE"]}
    driver: {{docker: {{}}}}
    env:
      PROJECT_NAME: NetFlow usability isolated test
      ENVIRONMENT: local
      ARTIFACT_ROOT: /app/artifacts
      NETFLOW_ALLOW_TEST_FIXTURES: 'true'
{common}    volumes:
    - type: bind
      source: {self.artifacts}
      target: /app/artifacts
""")

    def infra(self):
        v = self.v
        self.docker(
            "build",
            "--pull=false",
            "-f",
            "backend/Dockerfile.runner",
            "--build-arg",
            f"RUNNER_BUILD_VERSION={self.sha}",
            "-t",
            v["RUNNER_IMAGE"],
            ".",
        )
        self.docker(
            "build",
            "--pull=false",
            "-f",
            "octobus/Dockerfile",
            "-t",
            v["OCTOBUS_IMAGE"],
            ".",
        )
        self.docker("network", "create", self.network)
        self.docker(
            "run",
            "-d",
            "--name",
            f"{self.network}-db",
            "--network",
            self.network,
            "--network-alias",
            "db",
            "-p",
            f"127.0.0.1:{v['DB_PORT']}:5432",
            "-e",
            f"POSTGRES_DB={v['POSTGRES_DB']}",
            "-e",
            f"POSTGRES_USER={v['POSTGRES_USER']}",
            "-e",
            f"POSTGRES_PASSWORD={v['POSTGRES_PASSWORD']}",
            "postgres:18",
        )
        self.names += [f"{self.network}-db"]
        time.sleep(3)
        self.docker(
            "run",
            "-d",
            "--name",
            f"{self.network}-controller",
            "--network",
            self.network,
            "--network-alias",
            "agent-compose",
            "-p",
            f"127.0.0.1:{v['CONTROLLER_PORT']}:7410",
            "-v",
            "/var/run/docker.sock:/var/run/docker.sock",
            "-v",
            f"{self.data}:{self.data}",
            "-v",
            f"{self.artifacts}:{self.artifacts}",
            "-e",
            f"DATA_ROOT={self.data}",
            "-e",
            f"AGENT_COMPOSE_AUTH_TOKEN={v['AGENT_COMPOSE_AUTH_TOKEN']}",
            CONTROLLER,
            "daemon",
        )
        self.names += [f"{self.network}-controller"]
        self.docker(
            "run",
            "-d",
            "--name",
            f"{self.network}-upstream",
            "--network",
            self.network,
            "--network-alias",
            "upstream",
            "-v",
            f"{self.evidence / 'tls'}:/tls:ro",
            "-v",
            f"{self.evidence / 'upstream.py'}:/upstream.py:ro",
            "-e",
            f"FIXTURE_CLOUDATLAS_TOKEN={v['FIXTURE_CLOUDATLAS_TOKEN']}",
            v["RUNNER_IMAGE"],
            "/usr/local/bin/python",
            "/upstream.py",
        )
        self.names += [f"{self.network}-upstream"]
        self.docker(
            "run",
            "-d",
            "--name",
            f"{self.network}-octobus",
            "--network",
            self.network,
            "--network-alias",
            "octobus",
            "-p",
            f"127.0.0.1:{v['OCTOBUS_PORT']}:9000",
            "-v",
            f"{self.evidence / 'tls/cert.pem'}:/fixture/ca.pem:ro",
            "-e",
            "NODE_EXTRA_CA_CERTS=/fixture/ca.pem",
            v["OCTOBUS_IMAGE"],
            "serve",
            "--data-dir",
            "/var/lib/octobus",
            "--addr",
            "0.0.0.0:9000",
        )
        self.names += [f"{self.network}-octobus"]
        self.wait(f"http://127.0.0.1:{v['OCTOBUS_PORT']}/admin/v1/status")
        self.docker(
            "run",
            "--rm",
            "--entrypoint",
            "/bin/sh",
            "--network",
            self.network,
            "-v",
            f"{self.evidence / 'init-octobus.sh'}:/init.sh:ro",
            "-e",
            f"FIXTURE_CLOUDATLAS_TOKEN={v['FIXTURE_CLOUDATLAS_TOKEN']}",
            "-e",
            f"CLOUDATLAS_ASSETS_CAPSET_TOKEN={v['CLOUDATLAS_ASSETS_CAPSET_TOKEN']}",
            v["OCTOBUS_IMAGE"],
            "/init.sh",
        )
        self.docker(
            "run",
            "--rm",
            "--entrypoint",
            "/bin/sh",
            "--network",
            self.network,
            "-v",
            f"{self.evidence / 'agents.yml'}:/agents.yml:ro",
            "-e",
            f"AGENT_COMPOSE_AUTH_TOKEN={v['AGENT_COMPOSE_AUTH_TOKEN']}",
            CONTROLLER,
            "-ec",
            'agent-compose --host http://agent-compose:7410 auth login --token "$AGENT_COMPOSE_AUTH_TOKEN" >/dev/null && exec agent-compose --host http://agent-compose:7410 --file /agents.yml up --json',
        )

    def host(self):
        v = self.v
        h = env(
            {
                **v,
                "POSTGRES_SERVER": "127.0.0.1",
                "POSTGRES_PORT": v["DB_PORT"],
                "OCTOBUS_URL": f"http://127.0.0.1:{v['OCTOBUS_PORT']}",
                "AGENT_COMPOSE_URL": f"http://127.0.0.1:{v['CONTROLLER_PORT']}",
                "AGENT_COMPOSE_PROJECT_NAME": "nf-usability",
                "GOVERNANCE_RUNNER_BUILD_VERSION": self.sha,
                "NETFLOW_ALLOW_TEST_FIXTURES": "true",
                "ENVIRONMENT": "local",
                "PYTHONPATH": str(self.repo / "backend"),
            }
        )
        py = self.repo / "backend/.venv/bin/python"
        if not py.exists():
            self.run(["uv", "sync"], self.repo / "backend", h)
            py = self.repo / ".venv/bin/python"
        for script in ("backend_pre_start.py", "initial_data.py"):
            if script == "initial_data.py":
                migration = "from alembic.config import Config; from alembic import command; import sys; c=Config(sys.argv[1]); c.set_main_option('script_location', sys.argv[2]); command.upgrade(c, 'head')"
                self.run(
                    [
                        str(py),
                        "-c",
                        migration,
                        str(self.repo / "backend/alembic.ini"),
                        str(self.repo / "backend/app/alembic"),
                    ],
                    self.host_cwd,
                    h,
                )
            self.run(
                [str(py), str(self.repo / "backend/app" / script)], self.host_cwd, h
            )
        fixture = "from openpyxl import Workbook; import sys; from app.domain.customer_upload_profiles import REQUIRED_HEADERS, WARNING_HEADERS, OPTIONAL_HEADERS; w=Workbook(); s=w.active; s.append(list(REQUIRED_HEADERS + WARNING_HEADERS + OPTIONAL_HEADERS)); [s.append([f'192.0.2.{i}',443,443,'是','https://synthetic.example','HTTPS','Synthetic owner','Synthetic department','Synthetic owner','Synthetic department',i]) for i in range(1,39)]; [s.append(['192.0.2.1',443,443,'是','https://synthetic.example','HTTPS','Synthetic owner','Synthetic department','Synthetic owner','Synthetic department',100]) for _ in range(30)]; w.save(sys.argv[1])"
        self.run(
            [str(py), "-c", fixture, str(self.evidence / "customer.xlsx")],
            self.host_cwd,
            h,
        )
        self.start(
            [
                str(py),
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                v["API_PORT"],
            ],
            self.host_cwd,
            self.evidence / "api.log",
            h,
        )
        self.wait(f"http://127.0.0.1:{v['API_PORT']}/health/ready")
        self.start(
            [
                "bun",
                "run",
                "dev",
                "--",
                "--host",
                "127.0.0.1",
                "--port",
                v["UI_PORT"],
                "--strictPort",
            ],
            self.ui_cwd,
            self.evidence / "ui.log",
            env({"API_PROXY_TARGET": f"http://127.0.0.1:{v['API_PORT']}"}),
        )
        self.wait(f"http://127.0.0.1:{v['UI_PORT']}")

    def browser(self):
        test_env = env(
            {
                **self.v,
                "RUN_NETFLOW_USABILITY_E2E": "1",
                "PLAYWRIGHT_BASE_URL": f"http://127.0.0.1:{self.ports['ui']}",
                "NETFLOW_USABILITY_EVIDENCE": str(self.evidence),
                "NETFLOW_USABILITY_UPSTREAM": f"{self.network}-upstream",
            }
        )
        self.run(
            [
                "bunx",
                "playwright",
                "test",
                "--config=playwright.netflow.config.ts",
                "--reporter=line",
            ],
            self.repo / "frontend",
            test_env,
        )

    def finish(self):
        for p in self.procs:
            if p.poll() is None:
                p.terminate()
        for p in self.procs:
            try:
                p.wait(10)
            except subprocess.TimeoutExpired:
                p.kill()
        if not self.keep:
            # agent-compose guests are discovered by this invocation's mount root.
            ids = subprocess.check_output(
                [
                    "docker",
                    "ps",
                    "-aq",
                    "--filter",
                    f"ancestor={self.v['RUNNER_IMAGE']}",
                ],
                text=True,
            ).split()
            if ids:
                guests = json.loads(
                    subprocess.check_output(["docker", "inspect", *ids], text=True)
                )
                for guest in guests:
                    if any(
                        str(mount.get("Source", "")).startswith(
                            str(self.evidence) + "/"
                        )
                        for mount in guest.get("Mounts", [])
                    ):
                        subprocess.run(
                            ["docker", "rm", "-fv", guest["Id"]],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                        )
            for n in reversed(self.names):
                subprocess.run(
                    ["docker", "rm", "-fv", n],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            subprocess.run(
                ["docker", "network", "rm", self.network],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

    def execute(self):
        try:
            print(f"Evidence directory: {self.evidence}", flush=True)
            self.prep()
            self.infra()
            self.host()
            self.browser()
            if (
                subprocess.check_output(
                    ["git", "status", "--porcelain"], cwd=self.repo, text=True
                ).strip()
                or subprocess.check_output(
                    ["git", "rev-parse", "HEAD"], cwd=self.repo, text=True
                ).strip()
                != self.sha
            ):
                raise RuntimeError(
                    "Checkout changed during acceptance; results are not attributed to the recorded commit"
                )
            (self.evidence / "result.json").write_text(
                json.dumps({"status": "PASS", "sha": self.sha, "ports": self.ports})
                + "\n"
            )
            print(f"PASS evidence={self.evidence}")
            return 0
        except Exception as e:
            for n in self.names:
                subprocess.run(
                    ["docker", "logs", n],
                    stdout=(self.evidence / f"{n}.log").open("wb"),
                    stderr=subprocess.STDOUT,
                )
            (self.evidence / "result.json").write_text(
                json.dumps({"status": "FAIL", "error": str(e)}) + "\n"
            )
            print(f"FAIL evidence={self.evidence}: {e}", file=sys.stderr)
            return 1
        finally:
            self.finish()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--repo", type=Path, default=DEFAULT_REPO)
    p.add_argument("--output", type=Path)
    p.add_argument("--keep", action="store_true")
    a = p.parse_args()
    if a.output and (
        a.output.is_symlink()
        or (a.output.exists() and (not a.output.is_dir() or any(a.output.iterdir())))
    ):
        raise SystemExit("--output must be a new or empty non-symlink directory")
    if subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=a.repo, text=True
    ).strip():
        raise SystemExit(
            "Commit the candidate first; acceptance requires a clean checkout for an exact build identity"
        )
    return Run(
        a.repo,
        a.output
        or Path(tempfile.mkdtemp(prefix="exposure-netflow-usability-", dir="/tmp")),
        a.keep,
    ).execute()


if __name__ == "__main__":
    raise SystemExit(main())
