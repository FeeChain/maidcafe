"""Persistent bridge for the approved café UI. Study grades and cursors commit together.

The established SRS maths remains in server.py. A voluntary exam never calls it.
UI snapshots are kept in kv so ordinary record backups include interrupted groups.
"""
import copy
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import threading
from pathlib import Path

STATE_KEY = 'cafe.state.v1'
SPEECH_LOCK = threading.Lock()


def stage(band):
    return 0 if band and band <= 3 else 1 if band == 4 else 2 if band in (5, 6) else 3 if band == 7 else 4


def read_state(con):
    row = con.execute('select value from kv where key=?', (STATE_KEY,)).fetchone()
    return json.loads(row[0]) if row else None


def put_state(con, state):
    con.execute('insert into kv(key,value) values(?,?) on conflict(key) do update set value=excluded.value',
                (STATE_KEY, json.dumps(state, ensure_ascii=False, separators=(',', ':'))))


def vocabulary(s, con):
    tutorial = json.loads((Path(s.ROOT) / 'resources/tutorial.json').read_text(encoding='utf-8'))
    words = []
    for w in s.WORDS:
        words.append(dict(id=w['word'].lower(), word=w['word'], meaning=w.get('definition', '')[:240],
                          phonetic=w.get('phonetic', ''), band=stage(w.get('band')),
                          tier=w['tier'], rank=w['rank'], example=''))
    ids = {w['id'] for w in words}
    for (word,) in con.execute('select word from marks union select word from word_srs'):
        if word not in ids:
            w = s.word_info(word)
            words.append(dict(id=word, word=word, meaning=w['definition'], phonetic=w['phonetic'],
                              band=0, tier=0, rank=10**9, example=''))
    return tutorial + words


def snapshot(s):
    con = s.db()
    try:
        state = read_state(con)
        words = vocabulary(s, con)
        now = time.time()
        records = s.srs_map(con, now)
        marks = {w: (status, ts) for w, status, ts in con.execute('select word,status,ts from marks')}
        due = sorted((w for w, r in records.items() if r['state'] == 'learning'
                      and r['weight'] <= s.REVIEW_LINE and not s.same_day(r['last'], now)),
                     key=lambda w: (records[w]['weight'], s.word_rank(w), w))
        mastery = {w: dict(known=r['state'] in ('learning', 'graduated'), seen=(r['last'] or now)*1000,
                           state=r['state'], weight=r['weight']) for w, r in records.items()}
        for w, (status, ts) in marks.items():
            mastery.setdefault(w, dict(known=status in (3, 4), seen=ts*1000, state='known' if status in (3, 4) else 'new'))
        return dict(state=state, revision=(state or {}).get('revision', 0), words=words,
                    dueIds=due, mastery=mastery,
                    recent=[w for w, _ in sorted(marks.items(), key=lambda item: item[1][1], reverse=True)][:100],
                    dialogues=dialogues(s, con), version=s.VERSION)
    finally:
        con.close()


def dialogues(s, con):
    result = []
    for did, ts, scene, targets, turns, report, status in con.execute(
            'select id,ts,scene,target_words,turns,report,status from dialogues order by id'):
        meta = con.execute('select value from kv where key=?', ('cafe.dialogue.'+str(did),)).fetchone()
        meta = json.loads(meta[0]) if meta else {}
        rows = json.loads(turns or '[]')
        adir = Path(s.AUDIO_OUT) / str(did)
        files = sorted(p.name for p in adir.glob('turn_*') if p.suffix in ('.wav', '.mp3', '.m4a'))
        for i, turn in enumerate(rows):
            turn['audio'] = '/dialogue_audio/%s/%s' % (did, files[i]) if i < len(files) else ''
        titles=['窗边的午后','一杯咖啡的小事','柜台旁的小故事','今天也很高兴见到你','雨天的招待','咖啡喝到一半']
        result.append(dict(id=str(did), ts=ts*1000, title=titles[(did-1)%len(titles)],
                           targets=meta.get('targets', json.loads(targets)), turns=rows,
                           status=status, report=json.loads(report or '{}'),
                           groupId=meta.get('groupId', 'legacy'), single=meta.get('single'),
                           tutorial=meta.get('tutorial', False)))
    return result


def commit(s, payload):
    candidate = payload.get('state')
    if not isinstance(candidate, dict) or candidate.get('version') != 1:
        raise ValueError('学习记录格式不正确。')
    if len(json.dumps(candidate)) > 8*1024*1024:
        raise ValueError('学习记录过大，请重新打开软件。')
    size = candidate.get('settings', {}).get('size')
    if type(size) is not int or not 1 <= size <= 100:
        raise ValueError('每组词数应为 1–100。')
    con = s.db()
    try:
        con.execute('begin immediate')
        previous = read_state(con)
        revision = (previous or {}).get('revision', 0)
        if payload.get('revision') != revision:
            raise RuntimeError('另一个窗口更新了学习记录，请重新读取后继续。')
        intent = payload.get('intent') or {}
        if intent.get('action') == 'judge' and previous and previous.get('welcomeComplete') and not previous.get('replayTutorial'):
            group = previous.get('learning') or {}
            after = candidate.get('learning') or {}
            index = group.get('index', 0)
            if not group.get('revealed') or group.get('done') or index >= len(group.get('ids', [])):
                raise ValueError('请先翻开当前词卡。')
            word_id = group['ids'][index]
            passed = intent.get('known') == 'yes'
            expected = copy.deepcopy(group)
            expected['passed'] = [w for w in group['passed'] if w != word_id] + ([word_id] if passed else [])
            expected.update(index=index+1, revealed=False, done=index+1 == len(group['ids']))
            if after != expected:
                raise ValueError('词卡进度不一致，当前回答尚未保存。')
            word = word_for(candidate, word_id)
            con.execute("insert into marks(word,status,ts,src) values(?,1,?,'add') on conflict(word) do update set ts=excluded.ts",
                        (word, time.time()))
            (s.srs_pass if passed else s.srs_fail)(con, word)
        if intent.get('action') in ('readd', 'add-existing', 'save-word', 'import-text'):
            old_ids = set((previous or {}).get('recent', []))
            added = set(candidate.get('recent', [])) - old_ids
            if intent.get('id'):
                added.add(intent['id'])
            for wid in added:
                word = word_for(candidate, wid)
                con.execute("insert into marks(word,status,ts,src) values(?,1,?,'add') on conflict(word) do update set status=1,ts=excluded.ts", (word, time.time()))
                if intent.get('action') == 'readd':
                    con.execute("update word_srs set state='lapsed',reviewed_ts=null where word=?", (word,))
        if intent.get('action') == 'assessment-answer' and candidate.get('assessment', {}).get('done') and not candidate.get('recalibrating'):
            assessment = candidate['assessment']
            for answer in assessment['answers']:
                status = (3 if answer['known'] else 4) if answer['heard'] else (2 if answer['known'] else 1)
                con.execute('insert into marks(word,status,ts,src) values(?,?,?,?) on conflict(word) do update set status=excluded.status,ts=excluded.ts,src=excluded.src',
                            (answer['id'], status, time.time(), 'scan' if assessment['method']=='full' else 'probe'))
        state = copy.deepcopy(candidate)
        # Dialogue content is canonical in its own table, never copied from the browser.
        state['dialogues'] = []
        state['revision'] = revision+1
        put_state(con, state)
        con.commit()
        return dict(ok=True, revision=revision+1)
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def word_for(state, wid):
    custom = next((w['word'].lower() for w in state.get('customWords', []) if w['id']==wid), None)
    word = custom or wid
    if not isinstance(word, str) or not re.fullmatch(r"[a-z]+(?:[ '-][a-z]+){0,3}", word):
        raise ValueError('词条格式不正确。')
    return word


def generate(s, payload):
    ids = payload.get('ids', [])
    if not isinstance(ids, list) or not 1 <= len(ids) <= 5:
        raise ValueError('请选择 1–5 个词。')
    setup = s.ai_runtime.inspect(s.kv_get('model', ''))
    if not setup['ready']:
        raise RuntimeError(setup['message'])
    with s.GEN_LOCK:
        if s.GEN_PROCESS is not None and s.GEN_PROCESS.poll() is None:
            raise RuntimeError('上一段故事还在准备，请稍后再点。')
        con = s.db()
        try:
            state = read_state(con) or {}
            tutorial = payload.get('tutorial') is True
            words = [word_for(state, wid.removeprefix('tutorial:') if tutorial else wid) for wid in ids]
            cur = con.execute('insert into dialogues(ts,scene,characters,target_words,turns,report,status) values(?,?,?,?,?,?,?)',
                              (time.time(), '窗边的小故事', '[]', json.dumps(words), '[]', '{}', 'writing'))
            did = cur.lastrowid
            meta = {k:payload.get(k) for k in ('groupId', 'single', 'tutorial')}
            meta['targets'] = ids
            con.execute('insert into kv values(?,?)', ('cafe.dialogue.'+str(did), json.dumps(meta)))
            con.commit()
        finally:
            con.close()
        s.write_known_snapshot()
        cmd = ([sys.executable, '--generate', json.dumps(words)] if getattr(sys, 'frozen', False)
               else [sys.executable, os.path.join(s.ROOT, 'dialogue.py'), '--words', ','.join(words)])
        env = dict(os.environ, MAIDCAFE_MODEL=setup['model'], MAIDCAFE_OLLAMA_BASE=s.ai_runtime.OLLAMA_BASE,
                   MAIDCAFE_DIALOGUE_ID=str(did), MAIDCAFE_TUTORIAL='1' if tutorial else '0')
        Path(s.LOG_DIR).mkdir(parents=True, exist_ok=True)
        opts = {'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {'start_new_session':True}
        try:
            with open(os.path.join(s.LOG_DIR, 'generate.log'), 'a') as log:
                s.GEN_PROCESS = subprocess.Popen(cmd, env=env, stdout=log, stderr=log, **opts)
        except Exception:
            con=s.db()
            con.execute("update dialogues set status='error',report=? where id=?", (json.dumps({'error':'故事助手未能启动，请重试。'}),did))
            con.commit();con.close()
            raise
        return dict(id=str(did))


def handle(handler, s, path, payload=None, qs=None):
    try:
        if path == '/api/cafe/word-audio' and payload is None:
            word = (qs or {}).get('word', [''])[0].lower()
            word_for({}, word)
            key = hashlib.sha256(('kokoro-af_sarah-v1:'+word).encode()).hexdigest()
            folder = Path(s.CACHE_DIR)/'word-speech'/key
            target = folder/'turn_00.wav'
            with SPEECH_LOCK:
                if not target.is_file():
                    import dialogue
                    dialogue.synthesize([{'speaker':'Narrator','text':word}], {}, str(folder))
            body = target.read_bytes()
            handler.send_response(200)
            handler.send_header('Content-Type','audio/wav')
            handler.send_header('Content-Length',str(len(body)))
            handler.send_header('Cache-Control','private, max-age=31536000, immutable')
            handler.end_headers()
            handler.wfile.write(body)
            return
        if path == '/api/cafe/bootstrap' and payload is None:
            return handler._send(200, snapshot(s))
        if path == '/api/cafe/state' and payload is not None:
            return handler._send(200, commit(s, payload))
        if path == '/api/cafe/generate' and payload is not None:
            return handler._send(200, generate(s, payload))
        if path == '/api/cafe/dialogues' and payload is None:
            con=s.db()
            try:
                return handler._send(200, dialogues(s, con))
            finally:
                con.close()
        return handler._send(404, {'error':'没有找到这个操作。'})
    except (ValueError, RuntimeError) as e:
        return handler._send(409 if isinstance(e, RuntimeError) else 400, {'error':str(e)})
