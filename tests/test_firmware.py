# SPDX-License-Identifier: EUPL-1.2
"""0.15.0 HW key firmware (server/firmware.py): GitHub release download with checks, UF2 block checks, API access."""
import hashlib
import json
import shutil
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from test_api import Client, make_invite  # noqa: E402 – sets MORSE_DB to a temporary database first

from server import firmware as fw

FAMILY = 0x57755a57
BASE = 0x08010000


def uf2(blocks=4, base=BASE, family=FAMILY, bad_at=None, magic=fw.UF2_MAGIC0):
    out = b""
    for i in range(blocks):
        addr = base + 256 * i if bad_at != i else 0x08000000
        head = struct.pack("<8I", magic, fw.UF2_MAGIC1, fw.UF2_FLAG_FAMILY, addr, 256, i, blocks, family)
        out += head + bytes(476) + struct.pack("<I", fw.UF2_MAGIC_END)
    return out


def release(version="0.3.0", images=None, tag=None, **manifest_extra):
    images = images or {"cwkey-f411.uf2": uf2(), "cwkey-f401.uf2": uf2(3)}
    mcu = {"cwkey-f411.uf2": "STM32F411CE", "cwkey-f401.uf2": "STM32F401CC/CD/CE"}
    manifest = {"name": "CwKey", "version": version, "uf2_family_id": hex(FAMILY), "targets": [
        {"mcu": mcu.get(n, "X"), "uf2_app_base": hex(BASE),
         "uf2": {"file": n, "size": len(d), "sha256": hashlib.sha256(d).hexdigest()},
         "bootloader_drive": {"volume_label": "STMF411BOOT", "info_model": "ST STM32F411 BlackPill",
                              "info_board_id": "STM32F411-BlackPill-rev2"}} for n, d in images.items()],
        **manifest_extra}
    files = {"manifest.json": json.dumps(manifest).encode(), **images}
    rel = {"tag_name": tag or f"v{version}", "published_at": "2026-11-11T17:31:14Z", "body": "notes", "html_url": "u",
           "assets": [{"name": n, "browser_download_url": f"https://dl/{n}"} for n in files]}
    return rel, files, manifest


def fake_get(rel, files):
    def get(url, accept=None):
        if url == fw.RELEASE_URL:
            return json.dumps(rel).encode()
        return files[url.rsplit("/", 1)[1]]
    return get


class Uf2CheckTest(unittest.TestCase):
    def test_good_image(self):
        self.assertEqual(fw.check_uf2(uf2(5), FAMILY, BASE), 5)

    def test_rejects_bootloader_area_wrong_family_and_garbage(self):
        for data in (uf2(4, bad_at=2), uf2(4, family=0x1234), uf2(2, magic=0x1), b"x" * 100, b""):
            with self.assertRaises(fw.FwError):
                fw.check_uf2(data, FAMILY, BASE)

    def test_rejects_beyond_flash_end(self):
        with self.assertRaises(fw.FwError):
            fw.check_uf2(uf2(2, base=0x0807FF80), FAMILY, BASE, 0x08080000)

    def test_manifest_base_inside_bootloader(self):
        _, _, m = release()
        m["targets"][0]["uf2_app_base"] = "0x08000000"
        with self.assertRaises(fw.FwError):
            fw.check_manifest(m)


class SyncTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)

    def test_download_store_and_skip_known(self):
        rel, files, _ = release()
        self.assertEqual(fw.sync(fake_get(rel, files), self.dir), ("0.3.0", "new"))
        self.assertEqual(fw.sync(fake_get(rel, files), self.dir), ("0.3.0", "have"))
        cur = fw.current(self.dir)
        self.assertEqual((cur["version"], cur["released"], cur["notes"]), ("0.3.0", "2026-11-11T17:31:14Z", "notes"))
        self.assertEqual([t["blocks"] for t in cur["targets"]], [4, 3])
        self.assertEqual(fw.file_path("0.3.0", "cwkey-f411.uf2", self.dir).read_bytes(), files["cwkey-f411.uf2"])
        for bad in (("0.3.0", "manifest.json"), ("0.3.0", "../x.uf2"), ("../0.3.0", "cwkey-f411.uf2"),
                    ("0.4.0", "cwkey-f411.uf2")):
            self.assertIsNone(fw.file_path(*bad, self.dir))

    def test_newest_version_wins(self):
        for v in ("0.3.0", "0.10.0", "0.4.0"):
            fw.sync(fake_get(*release(v)[:2]), self.dir)
        self.assertEqual(fw.current(self.dir)["version"], "0.10.0")
        self.assertEqual([r["version"] for r in fw.releases(self.dir)], ["0.10.0", "0.4.0", "0.3.0"])

    def test_bad_release_stores_nothing(self):
        rel, files, _ = release()
        files["cwkey-f401.uf2"] = files["cwkey-f401.uf2"][:-1] + b"\x00"       # SHA-256 no longer matches
        with self.assertRaises(fw.FwError):
            fw.sync(fake_get(rel, files), self.dir)
        rel2, files2, _ = release(images={"cwkey-f411.uf2": uf2(4, bad_at=1)})  # writes into the bootloader
        with self.assertRaises(fw.FwError):
            fw.sync(fake_get(rel2, files2), self.dir)
        rel3, files3, _ = release(tag="v9.9.9")
        with self.assertRaises(fw.FwError):
            fw.sync(fake_get(rel3, files3), self.dir)
        self.assertIsNone(fw.current(self.dir))
        self.assertEqual(list(self.dir.iterdir()), [])

    def test_prerelease_ignored(self):
        rel, files, _ = release()
        rel["prerelease"] = True
        with self.assertRaises(fw.FwError):
            fw.sync(fake_get(rel, files), self.dir)

    def test_sync_now_never_raises(self):
        with mock.patch.object(fw, "sync", side_effect=OSError("offline")):
            self.assertIn("offline", fw.sync_now()["error"])
        self.assertIn("offline", fw.state()["error"])


class CheckOnLoginTest(unittest.TestCase):
    def setUp(self):
        self.addCleanup(fw._auto.update, dict(fw._auto))

    def test_login_triggers_a_throttled_background_check(self):
        calls = []
        fw._auto.update(on=True, running=False, last=0.0)
        with mock.patch.object(fw, "sync_now", side_effect=lambda: calls.append(1) or {"result": "have"}):
            c = Client()
            assert c.register(make_invite(), "FwLogin").status_code == 201
            self.assertEqual(c.login("FwLogin").status_code, 200)
            for th in [x for x in __import__("threading").enumerate() if x.name == "fw-check"]:
                th.join(5)
            self.assertEqual(calls, [1])
            self.assertEqual(c.req("GET", "/api/me").status_code, 200)   # within LOGIN_GAP_S → no new check
            self.assertFalse(fw.check_soon())
        self.assertEqual(calls, [1])

    def test_off_outside_the_service(self):
        fw._auto.update(on=False, running=False, last=0.0)
        with mock.patch.object(fw, "sync_now") as s:
            self.assertFalse(fw.check_soon())
            s.assert_not_called()


class FirmwareApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = Path(tempfile.mkdtemp())
        rel, cls.files, _ = release()
        fw.sync(fake_get(rel, cls.files), cls.dir)
        cls.patch = mock.patch.object(fw, "FW_DIR", cls.dir)
        cls.patch.start()
        cls.admin = Client()
        assert cls.admin.register(make_invite("admin"), "FwSpravce").status_code == 201
        cls.coach = Client()
        assert cls.coach.register(make_invite("trener"), "FwTrener").status_code == 201
        cls.student = Client()
        assert cls.student.register(make_invite("zak"), "FwZak").status_code == 201

    @classmethod
    def tearDownClass(cls):
        cls.patch.stop()
        shutil.rmtree(cls.dir, True)

    def test_coach_sees_release_and_downloads(self):
        r = self.coach.req("GET", "/api/fw").get_json()
        self.assertEqual(r["release"]["version"], "0.3.0")
        self.assertNotIn("sync", r)
        self.assertEqual(r["older"], [])
        f = self.coach.req("GET", "/api/fw/0.3.0/cwkey-f411.uf2")
        self.assertEqual((f.status_code, f.data), (200, self.files["cwkey-f411.uf2"]))
        self.assertEqual(self.coach.req("GET", "/api/fw/0.3.0/manifest.json").status_code, 404)

    def test_student_without_key_page_refused(self):
        self.assertEqual(self.student.req("GET", "/api/fw").status_code, 403)
        self.assertEqual(self.student.req("GET", "/api/fw/0.3.0/cwkey-f411.uf2").status_code, 403)
        self.assertEqual(Client().req("GET", "/api/fw").status_code, 403)

    def test_admin_state_and_check(self):
        self.assertIn("sync", self.admin.req("GET", "/api/fw").get_json())
        with mock.patch.object(fw, "sync", return_value=("0.3.0", "have")):
            self.assertEqual(self.admin.req("POST", "/api/fw/check").get_json(), {"version": "0.3.0", "result": "have"})
        self.assertEqual(self.coach.req("POST", "/api/fw/check").status_code, 403)


if __name__ == "__main__":
    unittest.main()
