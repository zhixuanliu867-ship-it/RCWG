"""Resolve public API symbols independently of a reviewer's chosen granularity."""
import ast,re
from functools import lru_cache
from common import ROOT
@lru_cache(maxsize=12)
def index(dataset,version):
    folder={'r0':'v0','r1':'v1','r2':'fixed'}[version];root=ROOT/'assets'/dataset/folder;classes={}
    for p in (root/'src'/dataset).glob('*.py'):
        tree=ast.parse(p.read_text(encoding='utf-8'));module=p.stem
        for node in tree.body:
            if isinstance(node,ast.ClassDef):
                bases=[]
                for x in node.bases:
                    if isinstance(x,ast.Subscript):x=x.value
                    bases.append(x.id if isinstance(x,ast.Name) else x.attr if isinstance(x,ast.Attribute) else '')
                classes[node.name]={'module':module,'path':str(p.relative_to(root)).replace('\\','/'),'methods':{n.name for n in node.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))},'bases':bases}
    return classes
def legacy_valid_symbol(symbol,dataset,version):
    if not isinstance(symbol,str):return False
    parts=symbol.split('.')
    if parts[0]!=dataset or len(parts) not in (3,4):return False
    cls,method=parts[-2:];classes=index(dataset,version)
    if cls not in classes:return False
    if len(parts)==4 and parts[1]!=classes[cls]['module']:return False
    seen=set()
    def defines(c):
        if c in seen or c not in classes:return False
        seen.add(c);return method in classes[c]['methods'] or any(defines(b) for b in classes[c]['bases'])
    return defines(cls)
@lru_cache(maxsize=12)
def symbol_index(dataset,version):
    root=ROOT/'assets'/dataset/{'r0':'v0','r1':'v1','r2':'fixed'}[version]
    result={}
    for p in (root/'src'/dataset).rglob('*.py'):
        module='.'.join(p.relative_to(root/'src').with_suffix('').parts)
        if module.endswith('.__init__'):module=module[:-9]
        result[module]={'kind':'module','path':p.relative_to(root).as_posix(),'class':None}
        tree=ast.parse(p.read_text(encoding='utf-8'))
        for n in tree.body:
            if isinstance(n,(ast.ClassDef,ast.FunctionDef,ast.AsyncFunctionDef)):
                meta={'kind':'class' if isinstance(n,ast.ClassDef) else 'function','path':p.relative_to(root).as_posix(),'class':n.name if isinstance(n,ast.ClassDef) else None}
                result[module+'.'+n.name]=meta
                if isinstance(n,(ast.ClassDef,ast.FunctionDef,ast.AsyncFunctionDef)):
                    # Root-package alias is accepted only if it is really exported.
                    init=(root/'src'/dataset/'__init__.py').read_text(encoding='utf-8')
                    if re.search(r'\b'+re.escape(n.name)+r'\b',init):result[dataset+'.'+n.name]=meta
    return result

def canonical_symbol(symbol):
    if not isinstance(symbol,str):return symbol
    value=symbol.strip().strip('`')
    annotated=re.fullmatch(r'([A-Za-z_]\w*(?:\.[A-Za-z_]\w*){1,4})\s+\([^()]*\)',value)
    if annotated:value=annotated.group(1)
    located=re.fullmatch(r'src/([A-Za-z_][\w/]+)\.py:([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)',value)
    if located:value=located.group(1).replace('/','.')+'.'+located.group(2)
    return value

def resolve(symbol,dataset,version):
    if not isinstance(symbol,str):return None
    symbol=canonical_symbol(symbol)
    idx=symbol_index(dataset,version)
    if symbol in idx:return idx[symbol]
    if legacy_valid_symbol(symbol,dataset,version):
        cls=symbol.split('.')[-2];c=index(dataset,version)[cls]
        return {'kind':'method','path':c['path'],'class':cls}
    if symbol.startswith('src/') and symbol.endswith('.py'):
        return next((dict(v,kind='module') for v in idx.values() if v['path']==symbol),None)
    return None

def valid_symbol(symbol,dataset,version):return resolve(symbol,dataset,version) is not None

# Task-source-specific routes, inspected before the new calls. This registry maps
# known helper/API routes to behavioral families; source existence is independent.
FUNCTION_FAMILIES={**{f'requests.{prefix}{name}':{'Session'} for prefix in ('','api.') for name in ('request','get','options','head','post','put','patch','delete')},
 'requests.cookies.merge_cookies':{'PreparedRequest','RequestsCookieJar'},
 'requests.cookies.get_cookie_header':{'PreparedRequest','RequestsCookieJar'},
 'requests.utils.redirect_identity':{'Session','SessionRedirectMixin'},
 'requests.api.request':{'Session'},
 'requests.cookies.extract_cookies_to_jar':set(),
 'requests.auth.HTTPDigestAuth.handle_401':{'PreparedRequest'},
 'requests.adapters.HTTPAdapter.send':set(),
 'requests.models.Response.next':{'PreparedRequest'},
 'requests.models.Request.prepare':{'PreparedRequest'},
 'requests.Request.prepare':{'PreparedRequest'},
 'requests.Response.next':{'PreparedRequest'},
 'requests.cookies.CookieConflictError':set(),
 'itsdangerous.signer.Signer.unsign':set(),
 'itsdangerous._age_policy.age_policy':{'TimestampSigner'},
}
def check(values,task,gold):
    required={x for group in gold.get('required_scope',[]) for x in group}
    if not isinstance(values,list) or any(not isinstance(x,str) for x in values) or len(values)!=len(set(values)):return False,{'reason':'invalid or duplicate scope items'}
    dataset=task['dataset'];resolved={x:resolve(x,dataset,task['final_version']) for x in values if isinstance(x,str)}
    unresolved=[x for x in values if not resolved.get(x)]
    if all(isinstance(x,str) and x.endswith('.py') for x in values):
        allowed=required | ({'src/requests/api.py','src/requests/auth.py','src/requests/cookies.py','src/requests/adapters.py'} if dataset=='requests' else {'src/itsdangerous/signer.py','src/itsdangerous/serializer.py','src/itsdangerous/url_safe.py'})
        return required<=set(values)<=allowed and not unresolved,{'representation':'module_paths','required_modules':sorted(required),'unresolved_symbols':unresolved,'unclassified_module_paths':sorted(set(values)-allowed),'note':'Required source coverage plus source-audited related caller/helper modules. Existence alone is insufficient.'}
    groups=[{'TimestampSigner'},{'TimedSerializer'},{'URLSafeTimedSerializer'}] if dataset=='itsdangerous' else [{'Session','SessionRedirectMixin'},{'PreparedRequest','RequestsCookieJar'}]
    families=set();pending=[]
    for x,meta in resolved.items():
        if not meta:continue
        if meta['class'] in set().union(*groups):families.add(meta['class'])
        elif canonical_symbol(x) in FUNCTION_FAMILIES:families.update(FUNCTION_FAMILIES[canonical_symbol(x)])
        elif meta['kind']=='module' and meta['path'] in required:pass # explicit related implementation module; no invented API-family credit
        else:pending.append(x)
    covered=[bool(g&families) for g in groups]
    return not unresolved and all(covered) and not pending,{'representation':'public_api_symbols','covered_public_families':covered,'resolved_symbols':resolved,'representation_normalizations':{x:canonical_symbol(x) for x in resolved if x!=canonical_symbol(x)},'unresolved_symbols':unresolved,'relevance_requires_review':pending,'module_scope_required_for_source_evidence':sorted(required),'note':'AST existence, behavioral coverage, and semantic relevance are distinct. Existing unclassified symbols are review cases, not nonexistent symbols.'}
