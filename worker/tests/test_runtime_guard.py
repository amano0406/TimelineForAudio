from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

from timeline_for_audio_worker.runtime_guard import (
    ALLOW_HOST_RUN_ENV,
    WORKER_FLAVOR_ENV,
    assert_worker_runtime_allowed,
    is_host_worker_run_allowed_for_tests,
    is_running_in_container,
)


class RuntimeGuardTests(unittest.TestCase):
    def test_host_worker_run_is_blocked_without_explicit_test_override(self) -> None:
        with (
            patch.dict(os.environ, {}, clear=True),
            patch(
                "timeline_for_audio_worker.runtime_guard._is_docker_marker_present",
                return_value=False,
            ),
            patch.object(sys, "stderr"),
        ):
            with self.assertRaises(SystemExit) as error:
                assert_worker_runtime_allowed()

        self.assertEqual(2, error.exception.code)

    def test_host_worker_run_is_allowed_with_explicit_test_override(self) -> None:
        with (
            patch.dict(os.environ, {ALLOW_HOST_RUN_ENV: "1"}, clear=True),
            patch(
                "timeline_for_audio_worker.runtime_guard._is_docker_marker_present",
                return_value=False,
            ),
        ):
            self.assertTrue(is_host_worker_run_allowed_for_tests())
            assert_worker_runtime_allowed()

    def test_docker_worker_environment_is_allowed(self) -> None:
        with (
            patch.dict(os.environ, {WORKER_FLAVOR_ENV: "cpu"}, clear=True),
            patch(
                "timeline_for_audio_worker.runtime_guard._is_docker_marker_present",
                return_value=False,
            ),
        ):
            self.assertTrue(is_running_in_container())
            assert_worker_runtime_allowed()


if __name__ == "__main__":
    unittest.main()
