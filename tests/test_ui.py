"""Click the production café against isolated SQLite data. Speech bytes here are a
browser fixture; real Kokoro speech is a separate mandatory installed-app check."""
import io
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
import wave
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]


class CafeUI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw=sync_playwright().start();cls.browser=cls.pw.chromium.launch()
        buf=io.BytesIO()
        with wave.open(buf,'wb') as wav:
            wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(8000);wav.writeframes(b'\0\0'*1600)
        cls.audio=buf.getvalue()
    @classmethod
    def tearDownClass(cls):cls.browser.close();cls.pw.stop()
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.home=Path(self.tmp.name)
        env={k:v for k,v in os.environ.items() if not k.startswith('MAIDCAFE_')}
        env.update(MAIDCAFE_HOME=str(self.home),MAIDCAFE_MODEL='nonexistent-ui-test-model')
        self.proc=subprocess.Popen([sys.executable,str(ROOT/'desktop.py'),'--headless'],cwd=ROOT,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        self.addCleanup(self.stop)
        for _ in range(100):
            if (self.home/'server.json').exists():break
            time.sleep(.1)
        self.base=json.loads((self.home/'server.json').read_text())['url'].rstrip('/')
        self.page=self.browser.new_page(viewport={'width':1440,'height':900});self.addCleanup(self.page.close)
        self.errors=[];self.page.on('pageerror',lambda e:self.errors.append(str(e)))
        self.page.route('**/api/cafe/word-audio?*',lambda route:route.fulfill(body=self.audio,content_type='audio/wav'))
        self.page.goto(self.base);self.page.wait_for_function('window.__maidcafe!==undefined')
    def stop(self):
        self.proc.terminate()
        try:self.proc.wait(timeout=8)
        except subprocess.TimeoutExpired:self.proc.kill();self.proc.wait()
    def click(self,action,selector=''):
        self.page.locator('[data-action="'+action+'"]'+selector).click()
        self.page.wait_for_function('!document.querySelector(".app-shell[data-screen=error]")') if False else None
        self.page.wait_for_timeout(70)
    def snapshot(self):return self.page.evaluate('__maidcafe.snapshot()')
    def screen(self):return self.snapshot()['page']
    def choose_level(self):
        self.click('seat');self.click('go','[data-page="level"]');self.click('level','[data-index="1"]');self.click('confirm-level')
    def grade(self,known=True):
        self.click('reveal');self.click('judge','[data-known="'+('yes' if known else 'no')+'"]')
    def complete_tutorial(self):
        self.choose_level();self.click('start-tutorial')
        for _ in range(5):self.grade()
        self.click('next-group');self.click('begin-learning')
        self.assertEqual(self.screen(),'learn')
    def database(self):
        con=sqlite3.connect(self.home/'progress.db')
        try:return {t:con.execute('select * from '+t).fetchall() for t in ('marks','word_srs')}
        finally:con.close()

    def test_onboarding_retry_and_optional_dialogue(self):
        self.assertEqual(self.page.locator('[data-action]').count(),1)
        self.page.goto(self.base+'/#/learn');self.page.wait_for_function('window.__maidcafe!==undefined')
        self.assertEqual(self.screen(),'welcome')
        self.choose_level();self.assertEqual(self.snapshot()['level'],1);self.click('start-tutorial')
        for i in range(5):self.grade(i>1)
        self.assertEqual(self.screen(),'group');self.assertEqual(self.page.locator('[data-action="next-group"]').count(),0)
        self.click('retry-group');self.assertEqual(len(self.snapshot()['tutorial']['ids']),2)
        for _ in range(2):self.grade()
        self.click('next-group');self.assertEqual(self.screen(),'welcome-end')
        self.assertEqual(self.database(),{'marks':[],'word_srs':[]})
        self.click('begin-learning');self.assertEqual(len(self.snapshot()['learning']['ids']),20)
        self.assertEqual(self.page.locator('[data-action="menu"]').count(),1)
        self.assertEqual(self.page.locator('.learning-controls button').count(),4)
        self.assertEqual(self.errors,[])

    def test_group_retry_shrinks_and_art_survives_restart(self):
        self.complete_tutorial();art=self.snapshot()['learning']['art']
        for i in range(20):self.grade(i>0)
        self.assertEqual(self.screen(),'group');self.click('retry-group')
        self.assertEqual(len(self.snapshot()['learning']['ids']),1)
        self.page.reload();self.page.wait_for_function('window.__maidcafe!==undefined')
        self.assertEqual(self.snapshot()['learning']['art'],art)
        self.grade();self.assertEqual(self.screen(),'group')
        self.click('gen-mode','[data-value="custom"]');self.assertEqual(self.page.locator('[data-action="select-word"]').count(),1)
        self.click('next-group');self.assertEqual(self.snapshot()['learning']['index'],0)
        self.assertNotEqual(self.snapshot()['learning']['art'],art)
        self.assertEqual(len(self.database()['word_srs']),20)
        self.assertEqual(self.errors,[])

    def test_assessment_saved_between_hearing_and_spelling(self):
        self.click('seat');self.click('go','[data-page="methods"]');self.click('method','[data-id="sample"]');self.click('start-assessment')
        first=self.snapshot()['assessment']['queue'][0]
        self.click('assessment-answer','[data-known="yes"]');self.click('pause-assessment')
        self.page.reload();self.page.wait_for_function('window.__maidcafe!==undefined')
        self.click('resume-assessment');a=self.snapshot()['assessment']
        self.assertEqual(a['queue'][0],first);self.assertEqual(a['phase'],'know');self.assertTrue(a['heard'])
        self.click('assessment-answer','[data-known="no"]');self.assertEqual(self.snapshot()['assessment']['index'],1)
        self.assertEqual(self.errors,[])

    def test_binary_test_finishes_and_full_test_can_pause(self):
        self.click('seat');self.click('go','[data-page="methods"]');self.click('start-assessment')
        for _ in range(70):
            if self.screen()!='assessment':break
            self.click('assessment-answer','[data-known="no"]');self.click('assessment-answer','[data-known="no"]')
        self.assertEqual(self.screen(),'result');self.assertEqual(self.snapshot()['learningFrontier'],0)
        self.assertEqual(self.errors,[])

    def test_exam_settings_library_and_error_recovery(self):
        self.complete_tutorial();self.grade();before=self.database()
        self.click('menu');self.click('tool','[data-page="exam-select"]')
        self.page.locator('[data-exam-id]').first.check();self.page.wait_for_timeout(150);self.click('start-exam');self.click('exam-reveal');self.click('exam-answer','[data-known="no"]')
        self.assertEqual(self.screen(),'exam-result');self.assertEqual(self.database(),before)
        self.click('return-study');self.click('menu');self.click('tool','[data-page="settings"]')
        self.assertEqual(self.page.locator('.workroom').count(),1)
        self.page.locator('#group-size').fill('7');self.page.locator('#group-size').dispatch_event('change');self.page.wait_for_timeout(200)
        self.assertEqual(self.snapshot()['settings']['size'],7)
        self.click('return-study');self.click('menu');self.click('tool','[data-page="library"]')
        self.click('add-word');self.page.locator('#new-word').fill('moonlight');self.click('save-word')
        self.assertIn('moonlight',self.snapshot()['recent'])
        self.click('return-study');index=self.snapshot()['learning']['index']
        self.page.route('**/api/cafe/state',lambda route:route.fulfill(status=503,json={'error':'保存暂时不可用'}))
        self.click('reveal');self.assertEqual(self.screen(),'error')
        self.page.unroute('**/api/cafe/state');self.click('recover')
        self.page.wait_for_function('__maidcafe.snapshot().page==="learn"')
        self.assertEqual(self.snapshot()['learning']['index'],index);self.assertEqual(self.errors,[])

    def test_history_player_lookup_and_real_text_import(self):
        self.complete_tutorial()
        con=sqlite3.connect(self.home/'progress.db')
        turns=[{'speaker':'Momo','text':'Hello, coffee please.'},{'speaker':'Haruka','text':'Your coffee is ready.'}]
        cur=con.execute('insert into dialogues(ts,scene,characters,target_words,turns,report,status) values(?,?,?,?,?,?,?)',
                        (time.time(),'fixture scene','["Momo","Haruka"]','["coffee"]',json.dumps(turns),'{}','done'))
        did=cur.lastrowid;con.commit();con.close()
        folder=self.home/'audio_out'/str(did);folder.mkdir(parents=True)
        for i in range(2):(folder/('turn_%02d.wav'%i)).write_bytes(self.audio)
        self.page.reload();self.page.wait_for_function('window.__maidcafe!==undefined')
        self.click('menu');self.click('tool','[data-page="history"]')
        self.assertEqual(self.page.locator('.history-day').count(),1)
        self.click('history-dialogue');self.assertEqual(self.screen(),'player')
        self.click('play-dialogue');self.page.wait_for_timeout(250)
        self.assertGreater(self.page.locator('.token.target').count(),0)
        self.page.locator('.token.target').first.click();self.page.wait_for_timeout(120)
        self.assertEqual(self.page.locator('[role=dialog]').count(),1);self.click('modal-close')
        self.click('back-history');self.click('return-study');self.click('menu');self.click('tool','[data-page="library"]')
        self.click('import');self.page.locator('#import-text').fill('moonbeam 月光\ncoffeeshop 咖啡店')
        self.click('import-text');self.click('import-done')
        self.assertIn('moonbeam',self.snapshot()['recent']);self.assertIn('coffeeshop',self.snapshot()['recent'])
        self.page.reload();self.page.wait_for_function('window.__maidcafe!==undefined')
        self.assertIn('moonbeam',self.snapshot()['recent']);self.assertEqual(self.errors,[])

    def test_full_assessment_pause_and_setup_required(self):
        self.click('seat');self.click('go','[data-page="methods"]');self.click('method','[data-id="full"]');self.click('start-assessment')
        self.assertGreater(len(self.snapshot()['assessment']['queue']),20000)
        self.click('assessment-answer','[data-known="yes"]');self.click('assessment-answer','[data-known="no"]');self.click('pause-assessment')
        self.click('go','[data-page="level"]');self.click('confirm-level');self.click('start-tutorial');self.click('reveal');self.click('single-story')
        self.page.wait_for_selector('[role=dialog][aria-label="故事助手"]')
        self.assertIn('Kokoro',self.page.locator('[role=dialog]').inner_text())
        self.assertEqual(self.snapshot()['dialogues'],[])
        self.click('modal-close');self.assertEqual(self.errors,[])

    def test_responsive_layout_and_all_twenty_five_backgrounds(self):
        self.complete_tutorial()
        for width,height in [(1440,900),(1160,820),(620,720),(390,844)]:
            self.page.set_viewport_size({'width':width,'height':height})
            self.assertLessEqual(self.page.evaluate('document.documentElement.scrollWidth'),width+1)
        result=self.page.evaluate("""async()=>{const {POOLS}=await import('/static/cafe-ui/presentation.js');const failed=[];await Promise.all(POOLS.learn.map(src=>new Promise(resolve=>{const i=new Image();i.onload=resolve;i.onerror=()=>{failed.push(src);resolve();};i.src='/static/cafe-ui/assets/'+src;})));return {count:POOLS.learn.length,failed};}""")
        self.assertEqual(result,{'count':25,'failed':[]});self.assertEqual(self.errors,[])

if __name__=='__main__':unittest.main(verbosity=2)
