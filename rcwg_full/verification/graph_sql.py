"""Independent graph gold: indexed SQLite relations and a disk priority queue.

No native adjacency, runtime comparator, graph kernel or reference plan is used.
The same implementation is differential-tested against the small Bellman-Ford
and edge-scan oracle before it is eligible for formal source review.
"""
import hashlib,json,math,sqlite3
from pathlib import Path
from rcwg_full.evidence import canonical,digest,write,read,exclusive_directory,safe_path


def file_hash(path):
    with safe_path(path).open('rb') as file:return hashlib.file_digest(file,'sha256').hexdigest()


def build_recipe(sources,context,manifest,directory):
    private=exclusive_directory(directory);path=private/'graph-oracle.sqlite3';db=sqlite3.connect(path)
    graph=sources['dataset:graph'];number=context['number']
    try:
        db.executescript('PRAGMA temp_store=FILE; PRAGMA cache_size=-8192; PRAGMA mmap_size=0;'
            'CREATE TABLE nodes(id INTEGER PRIMARY KEY,eligible INTEGER,raw TEXT);'
            'CREATE TABLE edges(id INTEGER PRIMARY KEY,src INTEGER,dst INTEGER,type TEXT,time INTEGER,weight REAL,raw TEXT);'
            'CREATE TABLE mappings(node_id INTEGER,document_id TEXT); CREATE TABLE attrs(id INTEGER PRIMARY KEY,raw TEXT);')
        db.executemany('INSERT INTO nodes VALUES(?,?,?)',((r['node_id'],int(r['eligible']),canonical(r).decode()) for r in graph['nodes']))
        db.executemany('INSERT INTO edges VALUES(?,?,?,?,?,?,?)',((r['edge_id'],r['src'],r['dst'],r['type'],r['time'],r['weight'],canonical(r).decode()) for r in graph['edges']))
        db.execute('CREATE INDEX edges_src ON edges(src)');db.execute('CREATE INDEX edges_dst ON edges(dst)')
        if 'dataset:node_doc' in sources:db.executemany('INSERT INTO mappings VALUES(?,?)',((r['node_id'],r['document_id']) for r in sources['dataset:node_doc']))
        if 'dataset:attributes' in sources:db.executemany('INSERT INTO attrs VALUES(?,?)',((r['attribute_node_id'],canonical(r).decode()) for r in sources['dataset:attributes']))
        db.execute('CREATE TABLE reached(id INTEGER PRIMARY KEY)');db.execute('CREATE TABLE frontier(id INTEGER PRIMARY KEY)')
        db.executemany('INSERT INTO reached VALUES(?)',((n,) for n in context['seeds']));db.execute('INSERT INTO frontier SELECT id FROM reached')
        if number in {1,4,6,7,9}:
            where="AND edges.type='allowed'" if number in {4,7,9} else ''
            if number==4:where+=' AND edges.time>=10 AND edges.time<70'
            for _ in range(4 if number in {4,7,9} else 3):
                db.execute('CREATE TEMP TABLE next_frontier AS SELECT DISTINCT dst AS id FROM edges JOIN frontier ON edges.src=frontier.id WHERE dst NOT IN (SELECT id FROM reached) '+where)
                db.execute('INSERT INTO reached SELECT id FROM next_frontier');db.execute('DELETE FROM frontier')
                db.execute('INSERT INTO frontier SELECT id FROM next_frontier');db.execute('DROP TABLE next_frontier')
        db.execute('CREATE TABLE best(id INTEGER PRIMARY KEY,distance REAL,settled INTEGER NOT NULL)')
        if number in {2,3,5,12}:
            db.execute('INSERT INTO best SELECT id,NULL,0 FROM nodes')
            db.executemany('UPDATE best SET distance=0 WHERE id=?',((n,) for n in context['seeds']))
            db.execute('CREATE INDEX priority ON best(distance,id) WHERE settled=0 AND distance IS NOT NULL')
            while row:=db.execute('SELECT id,distance FROM best WHERE settled=0 AND distance IS NOT NULL ORDER BY distance,id LIMIT 1').fetchone():
                node,distance=row;db.execute('UPDATE best SET settled=1 WHERE id=?',(node,))
                for target,weight in db.execute('SELECT dst,weight FROM edges WHERE src=?',(node,)):
                    proposal=distance+weight
                    db.execute('UPDATE best SET distance=? WHERE id=? AND settled=0 AND (distance IS NULL OR distance>?)',(proposal,target,proposal))
        db.execute('CREATE TABLE selected(id INTEGER PRIMARY KEY)')
        if number==11:db.execute('INSERT INTO selected SELECT id FROM nodes WHERE eligible=1')
        elif number==8:
            if context['mode']=='induced':selected=context['selection']
            else:selected=sorted({r[k] for r in context['selection'] for k in ['src','dst']})
            db.executemany('INSERT INTO selected VALUES(?)',((i,) for i in selected))
        db.commit()
        proof={'revision':'FULL001_GRAPH_SQL_ORACLE_1','sqlite_version':sqlite3.sqlite_version,
            'algorithm':'independent indexed SQL edge joins and on-disk minimum-distance queue',
            'source_rows':{'nodes':db.execute('SELECT COUNT(*) FROM nodes').fetchone()[0],'edges':db.execute('SELECT COUNT(*) FROM edges').fetchone()[0]},
            'source_logical_hashes':{s['source_id']:s['logical_content_sha256'] for s in manifest['sources']},
            'configured_sqlite_cache_kib':8192,'temp_store':'FILE','oracle_process_peak_ram_bytes':None,
            'native_execution_performed':False,'formal_frozen':False}
    finally:db.close()
    recipe={'comparison':'graph_sql_v1','context':context,'oracle_file':path.name,'oracle_sha256':file_hash(path),
            'source_logical_hashes':proof['source_logical_hashes'],'formal_gold_reviewed':False,'formal_frozen':False}
    verifier=private/'private_verifier_recipe.json';write(verifier,recipe);write(private/'oracle-proof.json',proof)
    return verifier,proof


def connect(recipe,path):
    relative=Path(recipe['oracle_file'])
    if relative.is_absolute() or len(relative.parts)!=1:raise ValueError('ORACLE_PATH')
    path=safe_path(Path(path).parent/relative)
    if file_hash(path)!=recipe['oracle_sha256']:raise ValueError('ORACLE_HASH')
    db=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True);db.execute('PRAGMA temp_store=FILE');db.execute('PRAGMA cache_size=-8192')
    return db


def check(actual,recipe,path):
    from .compare import equivalent,set_equal,bag_equal
    context=recipe['context'];number=context['number']
    db=connect(recipe,path)
    try:
        if number in {1,4,6,7,9}:
            sql='SELECT DISTINCT document_id FROM mappings JOIN reached ON mappings.node_id=reached.id' if number==9 else 'SELECT id FROM reached'
            return set_equal(actual,[r[0] for r in db.execute(sql)])
        if number==10:
            if type(actual) is not dict or set(actual)!={'q0','q1'}:return False
            return all(bag_equal(actual[label],[json.loads(r[0]) for r in db.execute('SELECT raw FROM edges WHERE src IN (?,?)',ids)])
                       for label,ids in [('q0',(0,1)),('q1',(2,3))])
        if number in {8,11}:
            if type(actual) is not dict or set(actual)!={'graph'}:return False
            graph=actual['graph']
            if not all(graph.get(k)==context[k] for k in ['domain','revision']) or graph.get('directed') is not True:return False
            edge_filter='src IN (SELECT id FROM selected) AND dst IN (SELECT id FROM selected)'
            if number==11:edge_filter+=' AND weight<=3'
            elif context['mode']=='edge_selected':edge_filter='id IN ('+','.join(str(r['edge_id']) for r in context['selection'])+')'
            for table,values,key,where in [('nodes',graph['nodes'],'node_id','id IN (SELECT id FROM selected)'),('edges',graph['edges'],'edge_id',edge_filter)]:
                if type(values) is not list or len(values)!=db.execute(f'SELECT COUNT(*) FROM {table} WHERE {where}').fetchone()[0]:return False
                db.execute('CREATE TEMP TABLE seen_'+table+'(id INTEGER PRIMARY KEY)')
                for value in values:
                    if type(value.get(key)) is not int:return False
                    try:db.execute('INSERT INTO seen_'+table+' VALUES(?)',(value[key],))
                    except sqlite3.IntegrityError:return False
                    row=db.execute(f'SELECT raw FROM {table} WHERE id=? AND ({where})',(value[key],)).fetchone()
                    if row is None or not equivalent(value,json.loads(row[0])):return False
            return True
        paths=actual['paths'] if number==12 else actual
        if type(paths) is not list or len(paths)!=len(context['targets']):return False
        if any(type(p) is not dict or type(p.get('target')) is not int or type(p.get('nodes')) is not list or
               type(p.get('edges')) is not list or any(type(i) is not int for i in p['nodes']+p['edges']) for p in paths):return False
        if sorted(p['target'] for p in paths)!=sorted(context['targets']):return False
        attributes=[];evidence=[]
        for p in paths:
            row=db.execute('SELECT distance FROM best WHERE id=?',(p['target'],)).fetchone();distance=row[0]
            if distance is None:
                if p['reachable'] is not False or p['distance'] is not None or p['nodes'] or p['edges']:return False
                continue
            if p['reachable'] is not True or not p['nodes'] or len(p['nodes'])!=len(p['edges'])+1:return False
            if p['nodes'][0] not in context['seeds'] or p['nodes'][-1]!=p['target'] or len(set(p['nodes']))!=len(p['nodes']):return False
            total=0.
            for index,(src,dst,ident) in enumerate(zip(p['nodes'],p['nodes'][1:],p['edges'])):
                edge=db.execute('SELECT raw FROM edges WHERE id=? AND src=? AND dst=?',(ident,src,dst)).fetchone()
                if edge is None:return False
                edge=json.loads(edge[0]);total+=edge['weight']
                if number==12:evidence.append({'target':p['target'],'edge_ref':ident,'edge_ordinal':index,**edge})
            if type(p['distance']) not in {int,float} or not math.isfinite(p['distance']):return False
            if not math.isclose(p['distance'],distance,abs_tol=1e-8,rel_tol=1e-6) or not math.isclose(total,distance,abs_tol=1e-8,rel_tol=1e-6):return False
            if number==12:
                for index,ident in enumerate(p['nodes']):
                    attr=json.loads(db.execute('SELECT raw FROM attrs WHERE id=?',(ident,)).fetchone()[0])
                    attributes.append({'target':p['target'],'node_id':ident,'ordinal':index,'value':attr['value'],'source_revision':attr['source_revision']})
        return number!=12 or set(actual)=={'paths','attributes','edges'} and bag_equal(actual['attributes'],attributes) and bag_equal(actual['edges'],evidence)
    finally:db.close()
