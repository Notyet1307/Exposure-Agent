from __future__ import annotations

import unittest

from probe import (
    CONTROL_IMAGE,
    CONTROL_REVISION,
    CONTROL_VERSION,
    GUEST_IMAGE,
    GUEST_RUNTIME_VERSION,
    RecoveryAction,
    SessionObservation,
    classify_session,
    recovery_action,
    redact_report,
)


class ProbeContractTests(unittest.TestCase):
    def test_probe_pins_the_real_control_plane_and_guest_revisions(self) -> None:
        self.assertEqual(
            CONTROL_IMAGE,
            (
                "ghcr.io/chaitin/agent-compose@"
                "sha256:838452756fe1f71b0f4239c02068700c3f15c8cf8ffade1a09ba08837669f89e"
            ),
        )
        self.assertEqual(
            GUEST_IMAGE,
            (
                "ghcr.io/chaitin/agent-compose-guest@"
                "sha256:99a031b38be9e6afc5b7ce5161a4c5ee6f93c9990f3b39a3fbd8c9b29044ee32"
            ),
        )
        self.assertEqual(CONTROL_VERSION, "v2607.10.0")
        self.assertEqual(CONTROL_REVISION, "e14c4dbd5e3b0dec6178073902d67d2765390427")
        self.assertEqual(GUEST_RUNTIME_VERSION, "0.7.0")

    def test_only_a_successful_control_plane_query_can_classify_a_session(self) -> None:
        self.assertIs(
            classify_session("running", control_plane_reachable=True),
            SessionObservation.RUNNING,
        )
        self.assertIs(
            classify_session("stopped", control_plane_reachable=True),
            SessionObservation.TERMINAL,
        )
        self.assertIs(
            classify_session("failed", control_plane_reachable=True),
            SessionObservation.TERMINAL,
        )
        self.assertIs(
            classify_session("pending", control_plane_reachable=True),
            SessionObservation.UNKNOWN,
        )
        self.assertIs(
            classify_session("stopped", control_plane_reachable=False),
            SessionObservation.UNKNOWN,
        )
        self.assertIs(
            classify_session(None, control_plane_reachable=False),
            SessionObservation.UNKNOWN,
        )

    def test_recovery_never_releases_or_replaces_an_unknown_or_running_session(
        self,
    ) -> None:
        self.assertIs(
            recovery_action(SessionObservation.TERMINAL),
            RecoveryAction.RESUME_SAME_SESSION,
        )
        self.assertIs(
            recovery_action(SessionObservation.RUNNING),
            RecoveryAction.HOLD_PROJECT_RUN_SLOT,
        )
        self.assertIs(
            recovery_action(SessionObservation.UNKNOWN),
            RecoveryAction.HOLD_PROJECT_RUN_SLOT,
        )

    def test_redaction_removes_machine_paths_credentials_and_guest_output(self) -> None:
        report = redact_report(
            {
                "workspace": "/private/tmp/issue-34/workspace",
                "token": "secret-value",
                "guest_output": "full guest output",
                "session_id": "stable-session-id",
                "status": "stopped",
            }
        )

        self.assertEqual(
            report, {"session_id": "stable-session-id", "status": "stopped"}
        )


if __name__ == "__main__":
    unittest.main()
