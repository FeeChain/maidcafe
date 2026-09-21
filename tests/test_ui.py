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
import wave

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KNOWN_BELOW = 100


def make_env(tmp, port, with_audio=False):
    cache = os.path.join(tmp, "cache")
    os.makedirs(cache)
    words = [{"word": "w%03d" % i, "phonetic": "/w%d/" % i,
              "definition": "释义%d" % i, "example_en": "", "example_cn": "",
              "sources": ["test"]} for i in range(300)]
    if with_audio:
        # 每个词共用一个真 wav：/audio/<word> 必须端出真字节
        wav_path = os.path.join(tmp, "beep.wav")
        with wave.open(wav_path, "wb") as wv:
            wv.setnchannels(1)
            wv.setsampwidth(2)
            wv.setframerate(8000)
            wv.writeframes(b"\x00\x00" * 800)   # 0.1s 静音
        for w in words:
            w["audio_path"] = wav_path
    with open(os.path.join(cache, "words_cache.json"), "w") as f:
        json.dump(words, f)
    return dict(os.environ,
                MAIDCAFE_DB=os.path.join(tmp, "ui.db"),
                MAIDCAFE_CACHE=cache,
                MAIDCAFE_PORT=str(port),
                MAIDCAFE_MODEL="no-such-model",
                MAIDCAFE_ECDICT=os.path.join(tmp, "none.db"),
                MAIDCAFE_AUDIO_OUT=os.path.join(tmp, "audio_out"))


class UIBase(unittest.TestCase):
    PORT = 8797
    WITH_AUDIO = False

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp(prefix="maidcafe-ui-")
        cls.base = "http://127.0.0.1:%d" % cls.PORT
        cls.proc = subprocess.Popen(
            [sys.executable, os.path.join(ROOT, "server.py")],
            env=make_env(cls.tmp, cls.PORT, with_audio=cls.WITH_AUDIO),
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

    def test_u05_shuffled_cards_fill_the_basket(self):
        session = {w["word"] for w in self.api("/api/session")["words"]}
        # 没翻词：篮子按钮灰（v4：只报数，不剧透具体词）
        self.assertTrue(self.page.locator("#brewBtn").is_disabled(),
                        "empty basket must be disabled")
        flips, tags = [], []
        for i in range(6):
            self.page.click("#lRevealBtn")
            flips.append(self.page.text_content("#lWord").strip())
            tags.append(self.page.text_content("#newTag").strip())
            if i == 0:
                self.assertIn("1 个词", self.page.text_content("#brewBtn"))
                self.assertFalse(self.page.locator("#brewBtn").is_disabled(),
                                 "one word is enough to brew")
            self.page.click("#lNextBtn")
        self.assertEqual(len(set(flips)), 6, "six distinct cards, no repeats")
        self.assertTrue(set(flips) <= session, "cards come from the session")
        self.assertTrue(all(t in ("新词", "复习") for t in tags), tags)
        # 翻了 6 个，篮子 5 封顶
        self.assertIn("5 个词", self.page.text_content("#brewBtn"))

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
        self.page.click("#brewBtn")
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
        passed_words = []
        for _ in range(2):
            # 考卡是打乱出的——记下实际考过的词再断组框
            passed_words.append(
                self.page.text_content("#exWordPreview").strip())
            self.page.click("#exYes")
            self.page.click("#exYes2")
        self.page.click("#examQuitBtn")
        self.page.wait_for_selector("#vLearn", state="visible")
        self.assertIn("2/20", self.page.text_content("#learnProgress"))
        # 考试=一轮的分界：回来篮子清空重新攒（用户裁决）
        self.assertEqual(self.page.evaluate("brewQueue()"), [],
                         "an exam resets the basket")
        self.assertTrue(self.page.locator("#brewBtn").is_disabled())
        ps = self.page.evaluate("Array.from(passed)")
        self.assertEqual(sorted(ps), sorted(passed_words))
        session = [w["word"] for w in self.api("/api/session")["words"]]
        self.page.click("#lRevealBtn")
        first = self.page.text_content("#lWord").strip()
        self.page.click("#lNextBtn")
        self.assertIn(first, session, "cards keep serving unpassed words")

    def test_u08b_basket_refills_after_a_brew(self):
        # 考试清篮后重新翻卡攒——进过锅的 5 词就算再翻开也不回篮
        for _ in range(30):
            if "5 个词" in self.page.text_content("#brewBtn"):
                break
            if self.visible("#lRevealBtn"):
                self.page.click("#lRevealBtn")
            self.page.click("#lNextBtn")
        else:
            self.fail("basket never refilled to five")
        q = self.page.evaluate("brewQueue()")
        pot = self.page.evaluate("Array.from(inPot)")
        self.assertEqual(len(q), 5)
        self.assertEqual(len(pot), 5, "the first brew claimed five words")
        self.assertFalse(set(q) & set(pot),
                         "brewed words don't come back to the basket")
        self.assertIn("2/20", self.page.text_content("#learnProgress"),
                      "portion counter keeps the full denominator")

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
        # 新一份：篮子清零变灰；翻 1 张就能煮（不足 5 不硬凑）
        self.assertTrue(self.page.locator("#brewBtn").is_disabled(),
                        "a fresh portion starts with an empty basket")
        self.page.click("#lRevealBtn")
        self.assertIn("1 个词", self.page.text_content("#brewBtn"))
        self.assertFalse(self.page.locator("#brewBtn").is_disabled())
        self.page.click("#lNextBtn")   # 回到遮罩态，别影响后面的键盘用例

    def test_u10_refresh_lands_in_s2(self):
        self.page.reload()
        self.page.wait_for_selector("#vLearn", state="visible")
        self.assertEqual(self.view(), "vLearn")

    def test_u10b_brand_escapes_any_state(self):
        # 品牌逃生口：考试半途点 maidcafe ☕ = 关掉重开，直落 S2
        self.page.click("#examBtn")
        self.page.wait_for_selector("#vExam", state="visible")
        self.page.click(".brand")
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
            # nav 的恢复在 loadTiers/loadQueue 两个异步请求之后（showCurrent
            # 里），慢机器上晚于 probeCard 隐藏——必须等待而非立即断言
            self.page.wait_for_selector("#topNav", state="visible")
            sessions = self.api("/api/probe_sessions")
            if status is None:
                self.assertEqual(sessions, [])
            else:
                self.assertEqual(sessions[0]["status"], status)
            self.assertTrue(before["calibrated"])

    def test_v03_listen_page_tabs_and_wordbook(self):
        # 品牌逃生口：校准页（v02 收尾处）点 maidcafe ☕ → 主页
        self.page.click(".brand")
        self.page.wait_for_selector("#vEmpty", state="visible")
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
        # 品牌逃生口：对话史/生词本页 → 主页
        self.page.click(".brand")
        self.page.wait_for_selector("#vEmpty", state="visible")


class TestAudioAndTimeout(UIBase):
    """有声词库上的两个此前缺口：
    w01 音频通路（前端请求了正确的 /audio/词 并调用 play，服务端端出真字节）
    w02 B04 生成超时红字路径（用 window.MC_GEN_TIMEOUT 测试钩子缩短 12 分钟）。
    """
    PORT = 8799
    WITH_AUDIO = True

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # 探针在 API 层重放（与 e2e t03 同一逻辑），把浏览器留给音频/超时本身
        def call(path, data=None):
            req = urllib.request.Request(
                cls.base + path,
                data=json.dumps(data).encode() if data is not None else None,
                headers={"Content-Type": "application/json"})
            return json.load(urllib.request.urlopen(req, timeout=10))
        for _ in range(40):
            r = call("/api/probe_next")
            if r.get("done"):
                break
            for w in r["words"]:
                status = 3 if int(w["word"][1:]) < KNOWN_BELOW else 1
                call("/api/mark", {"word": w["word"].lower(),
                                   "status": status, "src": "probe"})
        else:
            raise RuntimeError("probe seeding did not converge")
        # 8 秒：给 w02 的秒表断言留出走字窗口，之后才允许撞超时
        cls.page.add_init_script("window.MC_GEN_TIMEOUT = 8;")
        cls.page.add_init_script("""
            window.__mcAudio = [];
            const RealAudio = window.Audio;
            window.Audio = function (src) {
                const a = new RealAudio(src);
                const rec = { src: src, played: false };
                window.__mcAudio.push(rec);
                const play = a.play.bind(a);
                a.play = () => { rec.played = true; return play(); };
                return a;
            };
        """)

    def test_w01_word_audio_really_requested(self):
        self.page.goto(self.base + "/")
        self.page.wait_for_selector("#vLearn", state="visible")
        words = {w["word"] for w in self.api("/api/session")["words"]}
        self.page.wait_for_function("window.__mcAudio.length > 0")
        log = self.page.evaluate("window.__mcAudio")
        first = log[0]["src"].rsplit("/", 1)[-1]
        self.assertIn(first, words,   # 卡序已洗牌——断词属会话即可
                      "first learn card must request a session word's audio")
        self.assertTrue(log[0]["played"], "play() must actually be called")
        n = len(log)
        self.page.keyboard.press("k")           # A08 重听
        self.page.wait_for_function("window.__mcAudio.length > %d" % n)
        log = self.page.evaluate("window.__mcAudio")
        self.assertEqual(log[-1]["src"], "/audio/" + first,
                         "K replays the same word")
        self.assertTrue(log[-1]["played"])
        # 服务端把真字节端上来（此前 /audio/ 只测过 404 分支）
        with open(os.path.join(self.tmp, "beep.wav"), "rb") as f:
            wav = f.read()
        with urllib.request.urlopen(self.base + "/audio/" + first,
                                    timeout=10) as r:
            self.assertEqual(r.status, 200)
            self.assertEqual(r.read(), wav)

    def test_w02_b04_generation_timeout_red_path(self):
        words = [w["word"] for w in self.api("/api/session")["words"][:5]]
        self.page.evaluate(
            "localStorage.setItem('mc_home_gen', JSON.stringify("
            "{ words: %s, t0: Date.now() / 1000 }))" % json.dumps(words))
        self.page.goto(self.base + "/")
        self.page.wait_for_selector("#vLearn", state="visible")
        self.page.wait_for_function(
            "document.getElementById('brewBtn').textContent.includes('灶上')")
        self.page.click("#brewBtn")
        self.page.wait_for_selector("#vListen", state="visible")
        # 煮着可离开的安心提示必须在生成中亮着
        self.assertTrue(self.visible("#lsFreeHint"),
                        "free-to-leave hint shows while brewing")
        # 实时秒表：进度行必须带"已 m:ss · 平常约 m:ss"且每秒走字
        self.page.wait_for_function(
            "document.getElementById('lsGenLine').textContent"
            ".includes('平常约')", timeout=8000)
        t1 = self.page.text_content("#lsGenLine")
        self.page.wait_for_function(
            "document.getElementById('lsGenLine').textContent !== %s"
            % json.dumps(t1), timeout=8000)
        # 秒表每秒一拍都在查超时：越过 8 秒钩子阈值 -> 超时红字
        self.page.wait_for_function(
            "document.getElementById('lsGenLine').textContent"
            ".includes('超时')", timeout=20000)
        self.assertIn("Ollama", self.page.text_content("#lsGenLine"))
        self.assertTrue(self.visible("#lsAgainBtn"),
                        "timeout must re-offer the retry button")
        self.assertFalse(self.visible("#lsFreeHint"),
                         "hint goes away once the stove stops")
        self.assertIsNone(
            self.page.evaluate("localStorage.getItem('mc_home_gen')"),
            "timed-out brew must be cleared, not resumed forever")


if __name__ == "__main__":
    unittest.main(verbosity=2)
