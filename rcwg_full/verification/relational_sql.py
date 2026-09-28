"""Independent on-disk SQL oracle for generated F1/F2 source files.

No runtime operator or reference WorkIR is executed here. SQLite temp storage
and a bounded page cache avoid retaining the input or a join cross product in
Python. Expected output is written incrementally to a private recipe.
"""
import json
import os
import sqlite3
from rcwg_full.evidence import canonical,safe_path,write


def query(family,number):
    if family=='F1':
        where=[]
        if number in {1,2,4,7,9,10,12}:where.append('eligible IS 1')
        if number==2:where.append('q IS 1')
        if number==4:where.append('score >= 0')
        if number==8:where.append('(id IN (SELECT id FROM left_candidates UNION SELECT id FROM right_candidates))')
        selected='SELECT * FROM records'+(' WHERE '+' AND '.join(where) if where else '')
        if number in {6,8}:
            selected=f'SELECT * FROM (SELECT *, ROW_NUMBER() OVER (PARTITION BY entity_id ORDER BY _ordinal) AS position FROM ({selected})) WHERE position=1'
        if number==5:
            return f'SELECT id, score, group_id FROM (SELECT *, ROW_NUMBER() OVER (PARTITION BY group_id ORDER BY score DESC, id) AS position FROM ({selected})) WHERE position<=3 ORDER BY group_id, position'
        if number==9:return f'SELECT group_id, SUM(amount) AS total FROM ({selected}) GROUP BY group_id ORDER BY total DESC, group_id LIMIT 10'
        if number==10:return f'SELECT COUNT(CASE WHEN score>=5 THEN 1 END) AS low, COUNT(CASE WHEN score>=10 THEN 1 END) AS high FROM ({selected})'
        fields='id,score'+(',priority' if number==3 else ',entity_id' if number in {6,8} else '')
        order='score DESC,priority,id' if number==3 else 'priority,score DESC,id' if number==11 else 'score DESC,id'
        return f'SELECT {fields} FROM ({selected}) ORDER BY {order} LIMIT 20'
    if family!='F2':raise ValueError('SQL_ORACLE_FAMILY')
    if number==11:return 'SELECT entity_id,SUM(amount) AS total FROM "left" WHERE timestamp>=70 AND timestamp<230 GROUP BY entity_id HAVING SUM(amount)>=30'
    if number==6:return 'SELECT a.left_id,a.group_id FROM "left" a WHERE EXISTS (SELECT 1 FROM "right" b WHERE a.join_key=b.join_key AND b.qualified IS 1)'
    joined='FROM "left" a '+('LEFT JOIN' if number==5 else 'JOIN')+' "right" b ON a.join_key=b.join_key'
    if number in {9,10}:joined+=' JOIN third c ON b.right_entity_id=c.entity_key'
    if number==10:joined+=' WHERE a.eligible IS 1'
    if number in {1,3,5}:return 'SELECT a.left_id,b.right_id '+joined
    if number==2:return 'SELECT a.join_key AS "left.join_key",COUNT(*) AS count '+joined+' GROUP BY a.join_key'
    if number==4:return 'SELECT a.group_id,COUNT(*) AS count '+joined+' GROUP BY a.group_id'
    if number==7:return 'SELECT a.group_id,COUNT(DISTINCT b.right_entity_id) AS count '+joined+' GROUP BY a.group_id'
    if number in {8,9,10}:return 'SELECT a.group_id,SUM(a.amount) AS total '+joined+' GROUP BY a.group_id'
    if number==12:return 'SELECT SUM(a.amount) AS total,COUNT(*) AS count '+joined
    raise ValueError('SQL_ORACLE_TEMPLATE')


def build_recipe(catalog,template,comparison,private,*,seed,profile):
    private=safe_path(private);private.mkdir(parents=True,exist_ok=False,mode=0o700)
    db_path=private/'oracle.sqlite3';db=sqlite3.connect(db_path)
    db.row_factory=sqlite3.Row;source_rows={};peak_insert_rows=0
    try:
        db.execute('PRAGMA temp_store=FILE');db.execute('PRAGMA cache_size=-8192')
        db.execute('PRAGMA mmap_size=0');db.execute('PRAGMA automatic_index=ON')
        for ident,source in catalog.sources.items():
            alias=ident.removeprefix('dataset:')
            if alias not in {'records','left_candidates','right_candidates','approximate_candidates','left','right','third'}:raise ValueError('SQL_SOURCE_ALIAS')
            schema=source.public['schema'];fields=list(schema)
            def sql_type(typ):
                kind=typ if isinstance(typ,str) else typ['kind']
                if kind=='Nullable':return sql_type(typ['item'])
                return {'Int64':'INTEGER','Bool':'INTEGER','Float64':'REAL','Utf8':'TEXT'}[kind]
            definitions=','.join('"'+name+'" '+sql_type(schema[name]) for name in fields)
            db.execute(f'CREATE TABLE "{alias}" (_ordinal INTEGER PRIMARY KEY,{definitions})')
            insert=f'INSERT INTO "{alias}" VALUES('+','.join('?' for _ in range(len(fields)+1))+')'
            ordinal=0
            for batch in source.batches(batch_size=512):
                rows=batch.to_pylist();peak_insert_rows=max(peak_insert_rows,len(rows))
                db.executemany(insert,((ordinal+i,*[row[k] for k in fields]) for i,row in enumerate(rows)))
                ordinal+=len(rows)
            source_rows[ident]=ordinal
            if 'join_key' in fields:db.execute(f'CREATE INDEX "{alias}_key" ON "{alias}" (join_key)')
            if 'entity_key' in fields:db.execute(f'CREATE INDEX "{alias}_key" ON "{alias}" (entity_key)')
        db.commit();family=template[:2];number=int(template[-2:]);sql=query(family,number)
        cursor=db.execute(sql);row_count=0
        metadata={'role':'PRIVATE_FORMAL_CANDIDATE_ORACLE' if profile=='formal_candidate_v1' else 'PRIVATE_FORMAL_BUILDER_FIXTURE_ORACLE',
            'template_id':template,'seed':seed,'comparison':comparison,'implementation':'independent SQLite declarative query; no runtime kernels',
            'formal_gold_reviewed':False,'formal_frozen':False,'profile':profile}
        path=private/'private_verifier_recipe.json'
        with path.open('xb') as f:
            f.write(canonical(metadata)[:-1]+b',"expected":')
            if (family,number) in {('F1',10),('F2',12)}:
                row=dict(cursor.fetchone());value=({'low':{'count':row['low']},'high':{'count':row['high']}} if family=='F1' else {'sum':{'total':row['total']},'count':{'count':row['count']}})
                f.write(canonical(value));row_count=1
            else:
                f.write(b'[')
                for row in cursor:
                    if row_count:f.write(b',')
                    f.write(canonical(dict(row)));row_count+=1
                f.write(b']')
            f.write(b'}\n');f.flush();os.fsync(f.fileno())
        proof={'revision':'FULL001_RELATIONAL_SQL_ORACLE_1','sqlite_version':sqlite3.sqlite_version,'query':sql,
            'source_rows':source_rows,'source_logical_hashes':{k:s.entry['logical_content_sha256'] for k,s in catalog.sources.items()},
            'peak_insert_batch_rows':peak_insert_rows,'configured_sqlite_cache_kib':8192,'temp_store':'FILE',
            'expected_result_records':row_count,'sqlite_file_bytes':db_path.stat().st_size,'process_peak_ram_bytes':None,
            'native_execution_performed':False,'formal_frozen':False}
        write(private/'oracle-proof.json',proof)
        return path,proof
    finally:db.close()
