"""Real database regressions for the approved learning loop and upgrade path."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import cafe
import server


def state():
    group=dict(id='batch-1',kind='new',rootIds=['coffee','cup'],ids=['coffee','cup'],passed=[],index=0,revealed=True,round=1,done=False,art='momo-room-v4.png')
    return dict(version=1,settings={'size':20},revision=0,welcomeComplete=True,replayTutorial=False,
                learning=group,mastery={},recent=[],customWords=[],dialogues=[],level=0)


class CafeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name)
        self.patcher=patch.multiple(server,DB_PATH=str(root/'progress.db'),CACHE_DIR=str(root/'cache'),
                    WORDS_CACHE=str(root/'cache/words_cache.json'),DECKS_DIR=str(root/'decks'),
                    ECDICT_DB=str(root/'none.db'),ECDICT_PATH=str(root/'none.db'),AUDIO_OUT=str(root/'audio'))
        self.patcher.start();self.addCleanup(self.patcher.stop)
        server.build_words();self.s=state();self.commit()

    def commit(self,intent=None):
        result=cafe.commit(server,dict(state=self.s,revision=self.s['revision'],intent=intent or {}))
        self.s['revision']=result['revision'];return result

    def rows(self,table):
        con=server.db()
        try:return con.execute('select * from '+table).fetchall()
        finally:con.close()

    def grade(self,passed):
        g=self.s['learning'];word=g['ids'][g['index']]
        g['passed']=[w for w in g['passed'] if w!=word]+([word] if passed else [])
        g.update(index=g['index']+1,revealed=False,done=g['index']+1==len(g['ids']))
        self.commit(dict(action='judge',known='yes' if passed else 'no'))

    def test_first_pass_enters_review_not_graduation(self):
        self.grade(True)
        con=server.db();r=server.srs_map(con)['coffee'];con.close()
        self.assertEqual((r['state'],r['stab'],r['base']),('learning',1,100))
        self.assertAlmostEqual(r['due_ts']-r['last'],86400,places=3)
        snap=cafe.snapshot(server)
        self.assertEqual(snap['state']['learning']['index'],1)
        self.assertNotIn('coffee',snap['dueIds'])

    def test_failed_new_word_stays_new(self):
        self.grade(False)
        self.assertEqual(self.rows('word_srs'),[])
        self.assertFalse(cafe.snapshot(server)['mastery']['coffee']['known'])
        self.assertTrue(cafe.snapshot(server)['mastery']['coffee']['studied'])

    def test_failed_commit_never_advances_or_grades(self):
        before=self.rows('kv');self.s['learning']['index']=2
        with self.assertRaises(ValueError):self.commit(dict(action='judge',known='yes'))
        self.assertEqual(self.rows('kv'),before);self.assertEqual(self.rows('word_srs'),[])

    def test_stale_revision_cannot_double_grade(self):
        old=copy.deepcopy(self.s);self.grade(True)
        with self.assertRaises(RuntimeError):cafe.commit(server,dict(state=old,revision=old['revision']))
        self.assertEqual(len(self.rows('word_srs')),1)

    def test_voluntary_exam_never_changes_srs_or_marks(self):
        self.grade(True);before=(self.rows('word_srs'),self.rows('marks'))
        self.s['exam']={'answers':[{'id':'coffee','known':False}],'done':True}
        self.commit(dict(action='exam-answer',known='no'))
        self.assertEqual((self.rows('word_srs'),self.rows('marks')),before)

    def test_tutorial_does_not_change_real_records(self):
        self.s['replayTutorial']=True;self.commit()
        self.commit(dict(action='judge',known='yes'))
        self.assertEqual(self.rows('word_srs'),[]);self.assertEqual(self.rows('marks'),[])

    def test_due_queue_contains_all_due_words_not_twenty(self):
        con=server.db();now=time.time()
        words=[w['word'].lower() for w in server.WORDS[:45]]
        for word in words:server.srs_upsert_learning(con,word,1,1,now-2*86400)
        con.commit();con.close()
        self.assertEqual(set(cafe.snapshot(server)['dueIds']),set(words))

    def test_review_failure_then_same_day_pass_keeps_daily_rule(self):
        con=server.db();server.srs_upsert_learning(con,'coffee',2,2,time.time()-3*86400);con.commit();con.close()
        self.grade(False);before=self.rows('word_srs')
        g=self.s['learning'];g.update(ids=['coffee'],index=0,done=False,revealed=True,round=2)
        self.commit();self.grade(True)
        self.assertEqual(self.rows('word_srs'),before)
        self.assertEqual(self.s['learning']['passed'],['coffee'])
        self.assertTrue(cafe.snapshot(server)['mastery']['coffee']['retryTomorrow'])
        with patch('cafe.time.time',return_value=time.time()+86400):
            self.assertFalse(cafe.snapshot(server)['mastery']['coffee']['retryTomorrow'])

    def test_readd_graduate_returns_to_new_pool(self):
        con=server.db();server.srs_upsert_learning(con,'coffee',5,30,time.time());con.execute("update word_srs set state='graduated'");con.commit();con.close()
        self.commit(dict(action='readd',id='coffee'))
        self.assertFalse(cafe.snapshot(server)['mastery']['coffee']['known'])

    def test_background_and_revealed_card_survive_restart(self):
        self.s['learning']['art']='aoi-garden-v6.webp';self.commit()
        restored=cafe.snapshot(server)['state']['learning']
        self.assertEqual(restored['art'],'aoi-garden-v6.webp');self.assertTrue(restored['revealed'])

    def test_bundled_dictionary_has_real_tiers_and_all_stages(self):
        words=cafe.snapshot(server)['words'][5:]
        self.assertGreater(len(words),20000)
        self.assertEqual(set(w['band'] for w in words),set(range(5)))
        self.assertTrue(all(w['meaning'] for w in words))
        for tier in {w['tier'] for w in words}:
            self.assertLessEqual(sum(w['tier']==tier for w in words),100)

    def test_backup_contains_interrupted_group(self):
        con=server.db();backup=server.portability.export_records(con);con.close()
        kv=dict(backup['tables']['kv']['rows'])
        self.assertEqual(json.loads(kv[cafe.STATE_KEY])['learning'],self.s['learning'])

    def test_calibration_hearing_is_required_for_known(self):
        self.s['assessment']={'done':True,'method':'sample','answers':[{'id':'coffee','heard':False,'known':True},{'id':'cup','heard':True,'known':True}]}
        self.commit(dict(action='assessment-answer'))
        self.assertEqual({r[0]:r[1] for r in self.rows('marks')},{'coffee':2,'cup':3})
        self.assertFalse(any(m['studied'] for m in cafe.snapshot(server)['mastery'].values()))

if __name__=='__main__':unittest.main(verbosity=2)
