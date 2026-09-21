#!/usr/bin/env python3
"""maidcafe FULL-CLICK UI tests (Playwright, real headless Chromium).

Automates the TESTPLAN walk column: every home-flow state and button,
the probe funnel, blind archives, the S6 brew/list/player/word-card,
exams, refresh semantics, settings, keyboard, and the event log —
against an ISOLATED server (temp DB, synthetic wordbook, bogus model).

Dev-only dependency (the product itself stays stdlib-only):
    pip install playwright && python -m playwright install chromium
Run:  python3 tests/test_ui.py -v
"""

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KNOWN_BELOW = 100


def make_env(tmp, port):
    cache = os.path.join(tmp, "cache")
    os.makedirs(cache)
    words = [{"word": "w%03d" % i, "phonetic": "/w%d/" % i,
              "definition": "释义%d" % i, "example_en": "", "example_cn": "",
              "sources": ["test"]} for i in range(300)]
    with open(os.path.join(cache, "words_cache.json"), "w") as f:
        json.dump(words, f)
    return dict(os.environ,
                MAIDCAFE_DB=os.path.join(tmp, "ui.db"),
                MAIDCAFE_CACHE=cache,
                MAIDCAFE_PORT=str(port),
                MAIDCAFE_MODEL="no-such-model",
                MAIDCAFE_ECDICT=os.path.join(tmp, "none.db"))


class UIBase(unittest.TestCase):
    PORT = 8797

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="maidcafe-ui-")
        cls.base = "http://127.0.0.1:%d" % cls.PORT
        cls.proc = subprocess.Popen(
            [sys.executable, os.path.join(ROOT, "server.py")],
            env=make_env(cls.tmp, cls.PORT),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(60):
            try:
                urllib.request.urlopen(cls.base + "/api/home_status", timeout=2)
                break
            except Exception:
                time.sleep(0.25)
        else:
            raise RuntimeError("server did not start")
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch()
        cls.page = cls.browser.new_page()
        cls.page.on("dialog", lambda d: d.accept())

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()
        cls.proc.terminate()
        try:
            cls.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cls.proc.kill()

    # ---- helpers ----
    def api(self, path, data=None):
        req = urllib.request.Request(
            self.base + path,
            data=json.dumps(data).encode() if data is not None else None,
            headers={"Content-Type": "application/json"})
        return json.load(urllib.request.urlopen(req, timeout=10))

    def visible(self, sel):
        return self.page.is_visible(sel)

    def view(self):
        for v in ("vNew", "vIntro", "vEmpty", "vLearn", "vListen",
                  "vExam", "vExamDone", "vDone"):
            if self.page.is_visible("#" + v):
                return v
        return None

    def click_probe_through(self, known_below=KNOWN_BELOW, limit=60):
        """在校准页把当前探针/抽样流程点穿（无音频词=看词判断路径）。
        批次切换/收尾瞬间两个元素都不可见，故用二选一等待。"""
        either = ("(!document.getElementById('probeCard').classList"
                  ".contains('hidden')) || "
                  "(document.getElementById('wordPreview').offsetParent"
                  " !== null)")
        for _ in range(limit):
            self.page.wait_for_function(either, timeout=8000)
            if self.page.is_visible("#probeCard"):
                return
            w = self.page.text_content("#wordPreview").strip()
            know = int(w[1:]) < known_below
            self.page.click("#btnKnow" if know else "#btnShow")
            self.page.click("#btnNext" if know else "#btnOops")
        raise AssertionError("probe did not finish")


class TestMainJourney(UIBase):
    """一个新客人的完整旅程，按 TESTPLAN A/B/C 行逐按钮执行。"""

    def test_u01_s0_single_action(self):
        self.page.goto(self.base + "/")
        self.page.wait_for_selector("#vNew", state="visible")
        self.assertEqual(self.view(), "vNew")
        btns = self.page.locator("#vNew button").all_text_contents()
        self.assertEqual(len(btns), 1, "S0 must offer exactly one action")
        self.page.click("#goProbeBtn")
        self.page.wait_for_url("**/calibrate?probe=1")
        self.page.wait_for_selector("#card", state="visible")
        self.assertFalse(self.visible("#tierSelect"),
                         "full-scan toolbar must hide during the probe")

    def test_u02_probe_to_funnel_result(self):
        self.click_probe_through()
        self.assertFalse(self.visible("#endBtn"), "no round to end on result")
        self.assertFalse(self.visible("#topNav"),
                         "result page exits only via its own buttons")
        self.assertIn("边界", self.page.text_content("#probeBoundary"))

    def test_u03_full_coverage_button(self):
        self.page.click("#probeMoreBtn")
        self.page.wait_for_selector("#card", state="visible")
        self.assertTrue(self.visible("#topNav"), "nav returns for card flows")
        self.click_probe_through()
        self.page.wait_for_function(
            "document.getElementById('probeNums').textContent.includes('±')",
            timeout=8000)

    def test_u04_intro_card_once(self):
        self.page.click("text=去主页开始学习")
        self.page.wait_for_selector("#vIntro", state="visible")
        self.assertIn("20", self.page.text_content("#introLine"))
        self.page.click("#introStartBtn")
        self.page.wait_for_selector("#vLearn", state="visible")

    def test_u05_card_order_is_group_order(self):
        session = [w["word"] for w in self.api("/api/session")["words"]]
        flips = []
        tags = []
        for _ in range(6):
            self.page.click("#lRevealBtn")
            flips.append(self.page.text_content("#lWord").strip())
            tags.append(self.page.text_content("#newTag").strip())
            self.page.click("#lNextBtn")
        self.assertEqual(flips[:5], session[:5],
                         "cards must follow group 1 in exact order")
        self.assertEqual(flips[5], session[5], "then group 2 begins")
        self.assertTrue(all(t.startswith("第1组") for t in tags[:5]), tags)
        self.assertTrue(tags[5].startswith("第2组"), tags)
        self.assertEqual(
            self.page.locator(".grp.ready").count(), 1,
            "group 1 unlocks after all five are flipped")
        heads = self.page.locator(".grp .grp-head").all_text_contents()
        self.assertIn("可开火", heads[0])
        self.assertIn("1/5", heads[1])

    def test_u06_brew_error_path(self):
        # 先塞一条已出锅的对话，供列表/播放器用（无音频文件=瞬时揭示链）
        ws = [w["word"] for w in self.api("/api/session")["words"][:3]]
        con = sqlite3.connect(os.path.join(self.tmp, "ui.db"))
        con.execute(
            "insert into dialogues(id,ts,scene,characters,target_words,"
            "turns,report,status) values(1,?,?,?,?,?,?, 'done')",
            (time.time(), "ui walk scene", json.dumps(["Momo", "Suzu"]),
             json.dumps(ws),
             json.dumps([{"speaker": "Momo", "text": "Try the %s cake" % ws[0]},
                         {"speaker": "Suzu", "text": "It is %s and %s" % (ws[1], ws[2])}]),
             json.dumps({"known_ratio": 0.95})))
        con.commit()
        con.close()
        self.page.click(".grp.ready")
        self.page.wait_for_selector("#vListen", state="visible")
        self.page.wait_for_function(
            "document.getElementById('lsGenLine').textContent.includes('翻')",
            timeout=20000)
        self.assertTrue(self.visible("#lsAgainBtn"),
                        "retry button appears after a failed brew")

    def test_u07_embedded_player_and_word_card(self):
        row = self.page.locator("#lsDlgList .ditem").first
        row.locator(".d-top").click()
        self.page.wait_for_selector(".ls-play", state="visible")
        row.locator(".ls-play").click()
        self.page.wait_for_function(
            "document.querySelector('.ls-prog').textContent.startsWith('2/2')")
        self.assertEqual(row.locator(".txt.veiled").count(), 0,
                         "all turns revealed after playing through")
        row.locator(".wclick").first.click()
        self.page.wait_for_selector("#wordCard", state="visible")
        self.assertTrue(self.page.text_content("#wcWord").strip())
        self.page.click("#wcClose")

    def test_u08_exam_partial_then_quit(self):
        self.page.click("#lsExamBtn")
        self.page.wait_for_selector("#vExam", state="visible")
        for _ in range(2):
            self.page.click("#exYes")
            self.page.click("#exYes2")
        self.page.click("#examQuitBtn")
        self.page.wait_for_selector("#vLearn", state="visible")
        self.assertIn("2/20", self.page.text_content("#learnProgress"))
        session = [w["word"] for w in self.api("/api/session")["words"]]
        self.page.click("#lRevealBtn")
        first = self.page.text_content("#lWord").strip()
        self.page.click("#lNextBtn")
        self.assertIn(first, session, "cards keep serving unpassed words")

    def test_u09_exam_all_pass_then_seconds(self):
        self.page.click("#examBtn")
        self.page.wait_for_selector("#vExam", state="visible")
        for _ in range(18):
            self.page.click("#exYes")
            self.page.click("#exYes2")
        self.page.wait_for_selector("#vDone", state="visible")
        self.assertIn("20", self.page.text_content("#doneLine"))
        self.page.click("#moreBtn")
        self.page.wait_for_selector("#vLearn", state="visible")
        self.assertIn("0/20", self.page.text_content("#learnProgress"))
        heads = self.page.locator(".grp .grp-head").all_text_contents()
        self.assertTrue(all("0/" in h for h in heads),
                        "a fresh portion resets group counters")

    def test_u10_refresh_lands_in_s2(self):
        self.page.reload()
        self.page.wait_for_selector("#vLearn", state="visible")
        self.assertEqual(self.view(), "vLearn")

    def test_u11_keyboard_flow(self):
        before = self.page.text_content("#lWord").strip()
        self.page.keyboard.press("Space")
        revealed = self.page.text_content("#lWord").strip()
        self.assertNotEqual(revealed, before)
        self.assertNotIn("·", revealed)
        self.page.keyboard.press("Space")
        self.assertIn("·", self.page.text_content("#lWord"))

    def test_u12_settings_modal(self):
        self.page.click("#cfgBtn")
        self.page.wait_for_selector("#cfgModal", state="visible")
        self.page.fill("#quotaInput", "15")
        self.page.click("#quotaSave")
        self.page.wait_for_function(
            "document.getElementById('toastMsg').textContent.includes('15')")
        self.assertEqual(self.api("/api/config")["new_quota"], 15)
        self.page.fill("#quotaInput", "20")
        self.page.click("#quotaSave")
        links = self.page.locator(".cfg-links a").count()
        self.assertEqual(links, 3)
        self.page.click("#cfgClose")
        self.assertFalse(self.visible("#cfgModal"))

    def test_u13_event_log_captured_clicks(self):
        rows = self.api("/api/log?limit=400")
        events = {r["event"] for r in rows}
        self.assertIn("click", events)
        self.assertIn("view", events)
        self.assertIn("exam", events)
        self.assertTrue(any("examBtn" in (r["detail"] or "") for r in rows),
                        "button identities must be recorded")


class TestSecondaryFlows(UIBase):
    """空池、盲测采用/删除、对话史与生词本页。"""
    PORT = 8798

    def test_v01_all_known_user_lands_on_empty(self):
        self.page.goto(self.base + "/")
        self.page.click("#goProbeBtn")
        self.page.wait_for_selector("#card", state="visible")
        self.click_probe_through(known_below=10 ** 6)
        self.page.click("text=去主页开始学习")
        self.page.wait_for_selector("#vEmpty", state="visible")
        self.assertIn("词池空了", self.page.text_content("#vEmpty"))

    def test_v02_blind_discard_then_adopt(self):
        for action, status in (("#discardBtn", None), ("#adoptBtn", "adopted")):
            self.page.goto(self.base + "/calibrate?blind=1")
            self.page.wait_for_selector("#card", state="visible")
            before = self.api("/api/home_status")
            self.click_probe_through(known_below=10 ** 6)
            self.assertTrue(self.visible("#adoptBtn"))
            self.page.click(action)
            self.page.wait_for_selector("#probeCard", state="hidden")
            self.assertTrue(self.visible("#topNav"), "nav restored")
            sessions = self.api("/api/probe_sessions")
            if status is None:
                self.assertEqual(sessions, [])
            else:
                self.assertEqual(sessions[0]["status"], status)
            self.assertTrue(before["calibrated"])

    def test_v03_listen_page_tabs_and_wordbook(self):
        self.page.goto(self.base + "/listen")
        self.page.wait_for_selector("#listView", state="visible")
        self.page.click("#tabWordbook")
        self.page.wait_for_selector("#wordbookView", state="visible")
        self.page.fill("#addWordInput", "zzzqq")
        self.page.click("#addWordBtn")
        self.page.wait_for_function(
            "document.getElementById('addWordMsg').textContent.length > 0")
        self.assertIn("词典里没有", self.page.text_content("#addWordMsg"))
        self.page.click("#tabList")
        self.page.wait_for_selector("#listView", state="visible")
        # 深链语义 = 全新加载（同页仅改 hash 不会重启脚本，属预期）
        self.page.goto(self.base + "/")
        self.page.goto(self.base + "/listen#wordbook")
        self.page.wait_for_selector("#wordbookView", state="visible")


if __name__ == "__main__":
    unittest.main(verbosity=2)
