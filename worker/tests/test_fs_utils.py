from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from timeline_for_audio_worker.fs_utils import write_json_atomic


class FsUtilsTests(unittest.TestCase):
    def test_concurrent_atomic_writes_use_independent_temp_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "status.json"
            errors: list[Exception] = []
            start = threading.Event()
            active_replaces = 0
            max_active_replaces = 0
            replace_lock = threading.Lock()
            original_replace = Path.replace

            def instrumented_replace(path: Path, target_path: Path) -> Path:
                nonlocal active_replaces, max_active_replaces
                with replace_lock:
                    active_replaces += 1
                    max_active_replaces = max(max_active_replaces, active_replaces)
                try:
                    time.sleep(0.02)
                    return original_replace(path, target_path)
                finally:
                    with replace_lock:
                        active_replaces -= 1

            def writer(index: int) -> None:
                start.wait(timeout=2.0)
                try:
                    write_json_atomic(target, {"value": index})
                except Exception as exc:  # pragma: no cover - failure path asserted below
                    errors.append(exc)

            with patch.object(Path, "replace", new=instrumented_replace):
                threads = [threading.Thread(target=writer, args=(idx,)) for idx in range(4)]
                for thread in threads:
                    thread.start()
                start.set()
                for thread in threads:
                    thread.join(timeout=2.0)

            self.assertEqual([], errors)
            self.assertEqual(1, max_active_replaces)
            payload = json.loads(target.read_text(encoding="utf-8"))
            self.assertIn(payload["value"], {0, 1, 2, 3})


if __name__ == "__main__":
    unittest.main()
