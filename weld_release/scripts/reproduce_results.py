"""Reproduce the WELD paper's central numerical results without model calls."""
from pathlib import Path
import argparse,csv,json,hashlib,statistics,collections,math,itertools
R=Path(__file__).resolve().parents[1]
def rows(name):
    with (R/'data'/name).open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))
def yes(x):return str(x).lower() in {'true','1'}
def number(x):return float(x) if x else 0.0
def require(condition,message):
    if not condition:raise ValueError(message)
def key(r):return (r['parent'],r['replicate'],r['model_a'],r['model_b'])
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,default=R/'reproduced/summary.json');p.add_argument('--skip-hashes',action='store_true',help='For edited research copies only; default verifies release files.');args=p.parse_args()
    verified=0
    if not args.skip_hashes:
        m=json.loads((R/'provenance/public_manifest.json').read_text())
        for name,meta in m['files'].items():
            f=R/name;data=f.read_bytes()
            require(len(data)==meta['bytes'] and hashlib.sha256(data).hexdigest()==meta['sha256'],'Hash mismatch: '+name);verified+=1
    stage=rows('combined_main_stages.csv');require(len(stage)==6000,'Expected 6,000 final stages')
    ids={(x['model'],x['parent'],x['replicate'],x['condition']) for x in stage};require(len(ids)==6000,'Duplicate logical stage')
    models=sorted({x['model'] for x in stage});parents={x['parent'] for x in stage};clusters={x['source_cluster'] for x in stage}
    require((len(models),len(parents),len(clusters))==(10,100,20),'Unexpected experimental matrix')
    require(set(collections.Counter(x['model'] for x in stage).values())=={600},'Incomplete model denominator')
    require(set(collections.Counter((x['model'],x['scene']) for x in stage).values())=={120},'Unbalanced scenario denominator')
    for x in stage:require(yes(x['G'])==(yes(x['Q1']) and yes(x['Q2'])),'Validity conjunction mismatch')
    counts={c:sum(yes(x['G']) for x in stage if x['condition']==c) for c in ['base','related','unrelated']}
    require(counts=={'base':1479,'related':862,'unrelated':1532},'Paper validity counts changed')
    base={(x['model'],x['parent'],x['replicate']):x for x in stage if x['condition']=='base'}
    adaptation={}
    for c in ['related','unrelated']:
        eligible=[x for x in stage if x['condition']==c and yes(base[(x['model'],x['parent'],x['replicate'])]['G'])]
        n=sum(yes(x['G']) for x in eligible);adaptation[c]={'valid':n,'eligible':len(eligible),'rate':n/len(eligible)}
    require((adaptation['related']['valid'],adaptation['unrelated']['valid'])==(807,1468),'Adaptation counts changed')
    pairs=rows('native_work_pairs.csv');components=rows('native_work_pair_components.csv');groups=collections.defaultdict(list)
    for x in components:groups[key(x)].append(x)
    require(len(groups)==len(pairs)==5006,'Pair/component coverage mismatch')
    for x in pairs:
        xs=groups[key(x)];a=[number(z['work_a']) for z in xs];b=[number(z['work_b']) for z in xs]
        relation='equal' if a==b else 'a_dominates' if all(i<=j for i,j in zip(a,b)) else 'b_dominates' if all(i>=j for i,j in zip(a,b)) else 'tradeoff'
        require(relation==x['relation'],'Work relation mismatch: '+str(key(x)))
        require(yes(base[(x['model_a'],x['parent'],x['replicate'])]['G']) and yes(base[(x['model_b'],x['parent'],x['replicate'])]['G']),'Invalid pair member')
    relation=collections.Counter(x['relation'] for x in pairs)
    dominance=relation['a_dominates']+relation['b_dominates'];require((dominance,relation['equal'],relation['tradeoff'])==(2241,2393,372),'Relation totals changed')
    same=[x for x in pairs if number(x['tool_calls_a'])==number(x['tool_calls_b'])]
    hidden=[x for x in same if any(yes(z['primary']) and number(z['work_a'])!=number(z['work_b']) for z in groups[key(x)])]
    require((len(same),len(hidden),len({x['parent'] for x in hidden}))==(3619,187,29),'Call-count contrast changed')
    timing=rows('attenuation_primary.csv');estimates={}
    for x in timing:
        sw=1-number(x['work_low'])/number(x['work_high']);st=1-number(x['time_low'])/number(x['time_high'])
        require(math.isclose(sw,number(x['work_saving']),abs_tol=1e-10) and math.isclose(st,number(x['time_saving']),abs_tol=1e-10),'Saving formula mismatch')
    for domain in ['online','online_without_admission','native_replay_1','native_replay_4']:
        xs=[x for x in timing if x['difficulty']=='medium' and x['timing']==domain];by_parent=collections.defaultdict(list)
        for x in xs:by_parent[x['parent']].append(number(x['work_saving'])-number(x['time_saving']))
        estimates[domain]={'pairs':len(xs),'parents':len(by_parent),'equal_parent_gap':statistics.mean(statistics.mean(v) for v in by_parent.values())}
    require(math.isclose(estimates['online']['equal_parent_gap'],0.3164342142575891,abs_tol=1e-10),'Online estimate changed')
    require(math.isclose(estimates['online_without_admission']['equal_parent_gap'],0.1454194608168163,abs_tol=1e-10),'Adjusted estimate changed')
    result={'status':'PASS','verified_files':verified,'stages':len(stage),'models':len(models),'parents':len(parents),'source_clusters':len(clusters),'joint_valid':sum(counts.values()),'valid_by_condition':counts,'valid_initial_pairs':len(pairs),'work_relations':dict(relation),'dominance':dominance,'equal_call_pairs':len(same),'equal_call_unequal_primary_work':len(hidden),'adaptation':adaptation,'medium_timing':estimates}
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf8');print(json.dumps(result,indent=2))
if __name__=='__main__':main()
