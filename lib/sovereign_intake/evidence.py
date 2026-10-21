"""Opt-in bounded source evidence. Explicit source/version approval on the hub."""
import datetime
import hashlib
import json
from pathlib import Path
from brain_redact import redact_text
from .common import IntakeError, read_under, relative, slug
from .selection import scrub_detected, secret_hits

LIMIT = 256000
CHUNK = 8000
PARTS = 32

def permitted(path):
    p = relative(path)
    if any(x in {'sessions','quarantine','protonmail-env','tastytrade-env'} or x.startswith('.env') for x in p.parts):
        return False
    if p.name.lower() in {'creds.md','ams_polymarket_access.md','auth.json','config.yaml','positions.md','trade-journal.json','user.md','memory.md'}:
        return False
    return p.suffix in {'.md', '.jsonl'}

def clean(text):
    text, hits = redact_text(text)
    text, more = scrub_detected(text)
    hits.extend(more)
    if secret_hits(text):
        raise IntakeError('evidence_redaction_failed')
    return text, sorted(set(hits))

def split(text):
    parts=[]; buf=[]; size=0
    for c in text:
        n=len(c.encode())
        if size+n>CHUNK:
            parts.append(''.join(buf));buf=[];size=0
        buf.append(c);size+=n
    if buf:parts.append(''.join(buf))
    if not parts or len(parts)>PARTS:raise IntakeError('evidence_part_bound')
    return parts

def projection(raw, kind):
    rows=[]
    allowed_maintenance={'plan','status','timestamp','baseline','candidate','error','rollback','rollback_error','health_after','health_baseline','gateway_pid','recovery','verification','final_activation_verified_at','expected_paths','operation','gateway_restarted','node_dependencies_refreshed','restart_required'}
    for line in raw.decode().splitlines():
        r=json.loads(line)
        if not isinstance(r,dict):raise IntakeError('invalid_receipt_record')
        if kind=='maintenance-history':
            if set(r)-allowed_maintenance:raise IntakeError('receipt_schema_review_required')
            row={k:r[k] for k in ['timestamp','status','operation','error','rollback','rollback_error','recovery','gateway_restarted','restart_required'] if k in r}
            for key, fields in [('rollback', ['status','baseline','error']), ('recovery', ['diagnosis','candidate_fast_forwarded_without_additional_restart','controller_changed'])]:
                if isinstance(row.get(key), dict):
                    row[key] = {k:row[key][k] for k in fields if k in row[key]}
        elif kind=='health-history':
            if set(r)-{'checks','sent','timestamp'}:raise IntakeError('receipt_schema_review_required')
            checks=r.get('checks',[])
            if not isinstance(checks,list):raise IntakeError('invalid_health_checks')
            row={'timestamp':r['timestamp'],'sent':r.get('sent'),'checks':[{k:c[k] for k in ['name','status','ok','severity'] if k in c} for c in checks]}
            if any(not c for c in row['checks']):raise IntakeError('unrecognized_health_check_schema')
        else:raise IntakeError('unsupported_evidence_kind')
        rows.append((line,row))
    if not rows:raise IntakeError('empty_receipt_history')
    if len(rows)>1000:raise IntakeError('receipt_history_bound_requires_review')
    out=[]
    for start in range(0,len(rows),20):
        batch=rows[start:start+20]
        rawblock=('\n'.join(a for a,b in batch)+'\n').encode()
        text=json.dumps([b for a,b in batch],ensure_ascii=False,indent=2)+'\n'
        out.append((f'-b{start//20+1:03d}',rawblock,text,f'Projected {kind}; records {start+1}-{start+len(batch)}. Raw diagnostics, package plans, process IDs and account/provider data omitted. Outcomes are source assertions.'))
    return out

def assess_evidence(config, collected, validate, identity, digest):
    items=[]; observations=[]
    selectors=config.get('evidence_selectors',[])
    if not isinstance(selectors,list) or len(selectors)>1000:raise IntakeError('invalid_evidence_selectors')
    ids=[slug(s['id']) for s in selectors]
    if len(ids)!=len(set(ids)):raise IntakeError('duplicate_evidence_id')
    for s in selectors:
        obs={'source_id':s['id'],'state':'error'};observations.append(obs)
        try:
            path=str(relative(s['path']))
            if not permitted(path):raise IntakeError('forbidden_evidence_source')
            raw,st=read_under(config['evidence_root'],path,LIMIT)
            kind=s.get('kind','markdown')
            if kind=='markdown':
                if not path.endswith('.md'):raise IntakeError('evidence_kind_mismatch')
                groups=[('',raw,raw.decode('utf-8'),'Source document. Historical evidence, not current operating authority.')]
            else:
                if not path.endswith('.jsonl'):raise IntakeError('evidence_kind_mismatch')
                groups=projection(raw,kind)
            count=0
            for group,original,text,note in groups:
                text,hits=clean(text);parts=split(text)
                sourcehash=hashlib.sha256(original).hexdigest();retainedhash=hashlib.sha256(text.encode()).hexdigest()
                for n,part in enumerate(parts,1):
                    source_id=slug(s['id']+group+f'-p{n:02d}')
                    body=f'# {s["title"]}\n\n{note}\nSource: {path}\nOriginal SHA-256: {sourcehash}\nRetained SHA-256: {retainedhash}\nRedactions: {", ".join(hits) or "none"}\nPart: {n}/{len(parts)}\n\n<!-- retained-source-begin -->\n'+part+'\n<!-- retained-source-end -->\n'
                    item=dict(schema_version=1,exporter_version='2',client_id=config['client_id'],source_id=source_id,source_path=path,title=s['title'],topics=s.get('topics',[]),body=body,source_observed_at=datetime.datetime.fromtimestamp(st.st_mtime,datetime.timezone.utc).isoformat(),collected_at=collected)
                    item['capture_id']=digest(identity(item));validate(item,config['client_id']);items.append(item);count+=1
            obs.update(state='selected',parts=count,source_bytes=len(raw),truncated=False)
        except (IntakeError,OSError,UnicodeError,ValueError,KeyError,TypeError) as exc:
            obs['reason']=str(exc) if isinstance(exc,IntakeError) else 'source_unreadable_or_invalid'
    # Explicit roots are inventoried for new documents. Never silently widen scope.
    selected={s['path'] for s in selectors};excluded=set(config.get('evidence_excluded',[]))
    for root in config.get('evidence_watch_roots',[]):
        rel=relative(root);base=Path(config['evidence_root'])/str(rel)
        if not base.is_dir() or base.is_symlink():
            observations.append({'source_id':'coverage','state':'error','reason':'watch_root_missing_or_linked'});continue
        unknown=[str(p.relative_to(config['evidence_root'])) for p in base.rglob('*.md') if str(p.relative_to(config['evidence_root'])) not in selected|excluded]
        if unknown:observations.append({'source_id':'coverage','state':'error','reason':'new_sources_require_discovery','paths':sorted(unknown)})
    return items,observations
