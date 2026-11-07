"""Small portable learning-record backups. Audio and dictionaries stay separate."""
import time

TABLES = ('marks', 'word_srs', 'kv', 'probe_sessions', 'probe_marks', 'dialogues')


def export_records(con):
    tables = {}
    for name in TABLES:
        columns = [c[1] for c in con.execute('pragma table_info(%s)' % name)]
        tables[name] = {'columns': columns, 'rows': con.execute('select * from %s' % name).fetchall()}
    return {'format': 'maidcafe-records', 'version': 1, 'created': time.time(), 'tables': tables}


def restore_records(con, payload):
    if not isinstance(payload, dict) or payload.get('format') != 'maidcafe-records' or payload.get('version') != 1:
        raise ValueError('请选择 maidcafe 导出的学习记录备份。')
    tables = payload.get('tables')
    if not isinstance(tables, dict) or set(tables) != set(TABLES):
        raise ValueError('备份结构不完整。')
    total = 0
    for name in TABLES:
        spec = tables[name]
        columns = [c[1] for c in con.execute('pragma table_info(%s)' % name)]
        if not isinstance(spec, dict) or spec.get('columns') != columns or not isinstance(spec.get('rows'), list):
            raise ValueError('备份版本与当前应用不兼容。')
        total += len(spec['rows'])
        if total > 200000:
            raise ValueError('备份记录过多。')
        for row in spec['rows']:
            if not isinstance(row, (list, tuple)) or len(row) != len(columns) or any(v is not None and not isinstance(v, (str, int, float)) for v in row):
                raise ValueError('备份包含无法读取的记录。')
        if name == 'kv':
            for key, value in spec['rows']:
                if key == 'new_quota' and (not str(value).isdigit() or not 1 <= int(value) <= 100):
                    raise ValueError('备份中的每份词数无效。')
    con.execute('begin immediate')
    try:
        if any(con.execute('select count(*) from %s' % t).fetchone()[0] for t in TABLES if t != 'kv'):
            raise ValueError('当前已有学习记录。为避免覆盖，请在全新安装中恢复备份。')
        con.execute('delete from kv')
        for name in TABLES:
            rows = tables[name]['rows']
            if rows:
                placeholders = ','.join('?' for _ in tables[name]['columns'])
                con.executemany('insert into %s values(%s)' % (name, placeholders), rows)
        con.execute("update dialogues set status='error', report=? where status in ('writing','tts')",
                    ('{"error":"这段故事在备份前尚未完成，可以重新点单。"}',))
        con.commit()
    except Exception:
        con.rollback()
        raise
    return total
