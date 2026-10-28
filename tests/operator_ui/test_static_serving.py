# SPDX-FileCopyrightText: (C) 2026 Intel Corporation
# SPDX-License-Identifier: Apache-2.0
"""The Python server serves the compiled React UI without shadowing API routes."""

from __future__ import annotations

import http.client
import importlib.util
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch


class StaticServingTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.dist = root / "dist"
        (self.dist / "assets").mkdir(parents=True)
        (self.dist / "index.html").write_text("<!doctype html><div id=root></div>")
        (self.dist / "assets" / "app-abc.js").write_text("console.log(1)")
        (self.dist / "assets" / "app-abc.css").write_text("body{}")
        (self.dist / "assets" / "notes.txt").write_text("not an allowed type")
        (root / "secret.js").write_text("secret")
        self._env = patch.dict("os.environ", {
            "QSR_AUTONOMY_DB": str(root / "state.db"),
            "QSR_AUTONOMY_MODULES": "",
            "QSR_WARMUP": "false",
        })
        self._env.start()
        spec = importlib.util.spec_from_file_location("qsr_static_test", "operator-ui/app.py")
        self.app = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.app)
        self.app._DIST_DIR = self.dist
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self.app.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.thread.join()
        self.server.server_close()
        self.app.AUTONOMY.store.close()
        self._env.stop()
        self._tmp.cleanup()

    def get(self, path):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        try:
            connection.request("GET", path)
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def test_index_served_at_root_and_index_html(self):
        for path in ("/", "/index.html"):
            status, headers, body = self.get(path)
            self.assertEqual(status, 200)
            self.assertTrue(headers["Content-Type"].startswith("text/html"))
            self.assertIn("no-store", headers["Cache-Control"])
            self.assertIn(b'id=root', body)

    def test_assets_have_types_and_immutable_caching(self):
        status, headers, body = self.get("/assets/app-abc.js")
        self.assertEqual((status, body), (200, b"console.log(1)"))
        self.assertTrue(headers["Content-Type"].startswith("text/javascript"))
        self.assertIn("immutable", headers["Cache-Control"])
        status, headers, _ = self.get("/assets/app-abc.css?v=1")
        self.assertEqual(status, 200)
        self.assertTrue(headers["Content-Type"].startswith("text/css"))

    def test_asset_traversal_and_unknown_types_are_rejected(self):
        for path in (
            "/assets/../index.html",
            "/assets/%2e%2e/secret.js",
            "/assets/..%2fsecret.js",
            "/assets//etc/passwd",
            "/assets/notes.txt",
            "/assets/missing.js",
            "/assets/",
        ):
            status, _, body = self.get(path)
            self.assertEqual(status, 404, path)
            self.assertNotIn(b"secret", body)

    def test_unknown_paths_and_api_routes_never_return_the_frontend(self):
        for path in ("/nope", "/autonomy/proposals", "/ask", "/ask/stream"):
            status, headers, body = self.get(path)
            self.assertEqual(status, 404, path)
            self.assertNotIn(b"id=root", body)
            self.assertFalse(headers["Content-Type"].startswith("text/html"))

    def test_existing_get_routes_still_work(self):
        self.assertEqual(self.get("/health")[0], 200)
        self.assertEqual(self.get("/ready")[0], 200)
        status, _, body = self.get("/autonomy/status")
        self.assertEqual(status, 200)
        self.assertIn(b'"ok": true', body)

    def test_missing_build_returns_actionable_503(self):
        (self.dist / "index.html").unlink()
        status, _, body = self.get("/")
        self.assertEqual(status, 503)
        self.assertIn(b"npm run build", body)


if __name__ == "__main__":
    unittest.main()
