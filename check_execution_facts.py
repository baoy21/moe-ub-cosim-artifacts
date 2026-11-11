"""Independently read a delivered diagnostic package and its frozen observations.

This checks table identities, references, interval accounting and exact frozen
counter reconstruction. It computes no detector prediction or method score.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import time
import numpy as np


def read(path):return json.loads(Path(path).read_text())


def digest(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()


def require(ok,message):
    if not ok:raise ValueError(message)


def table(root,definition):
    p=root/definition['file']
    require(p.parent==root and digest(p)==definition['sha256'],'Changed/escaping diagnostic table')
    with np.load(p,allow_pickle=False) as f:
        require(f.files==definition['columns'],'Changed columns')
        result={k:f[k] for k in f.files}
    require(all(a.dtype==np.dtype('<i8') and a.shape==(definition['rows'],) for a in result.values()),'Noninteger or ragged table')
    return result


def frozen_counts(root,case,arrivals,service):
    """Rebin records into each original public object/window, including zeros."""
    results=[]
    for width in (1024,8192):
        path=root/'observed'/case['input_id']/str(width);public=read(path/'public.json')
        original=case['views'][str(width)]['original_files']
        require({name:digest(path/name) for name in original}==original,'Changed frozen observation')
        for direction,facts,select,timekey in [('ingress',arrivals,arrivals['source_access']==1,'time_ns'),('egress',service,np.ones(len(service['packet']),dtype=bool),'start_ns')]:
            lookup={(o['asic_id'],o['port_id']):i for i,o in enumerate(public['objects']) if o['direction']==direction}
            grouped=Counter();byte_counts=Counter()
            for node,port,t,size in zip(facts['node'][select],facts['port'][select],facts[timekey][select],facts['bytes'][select]):
                require((int(node),int(port)) in lookup,'Fact outside original object coverage')
                # Stored window is the left boundary in 1024 ns base ticks,
                # including for the 8192 ns view; it is not a coarse ordinal.
                k=lookup[int(node),int(port)],(int(t)//width)*(width//1024)
                grouped[k]+=1;byte_counts[k]+=int(size)
            with np.load(path/(direction+'.npz'),allow_pickle=False) as z:
                original_count={(int(o),int(w)):int(n) for o,w,n in zip(z['object'],z['window'],z['N']) if n}
                require(grouped==original_count,f'Exact original N reconstruction failed: {width} ns {direction}')
                if direction=='egress':
                    original_bytes={(int(o),int(w)):int(b) for o,w,b in zip(z['object'],z['window'],z['B']) if b}
                    require(byte_counts==original_bytes,'Exact original B reconstruction failed')
            results.append(dict(width_ns=width,direction=direction,packets=sum(grouped.values()),bytes=sum(byte_counts.values()),exact_N=True,exact_B=direction=='egress'))
    return results


def check(directory,published,output):
    start=time.monotonic();manifest=read(directory/'manifest.json');old=read(published/'manifest.json')
    require(manifest['status']=='completed' and manifest['diagnostic_only'] is True,'Incomplete diagnostic package')
    require(digest(published/'manifest.json')==manifest['original_package_manifest_sha256'],'Changed original package')
    require([(r['input_id'],r['condition']) for r in manifest['cases']]==[(r['input_id'],r['condition']) for r in old['cases']] and len(old['cases'])==7,'Whole seven-condition group missing')
    report=dict(schema='diagnostic-execution-facts-receipt/1',package_manifest_sha256=digest(directory/'manifest.json'),original_manifest_sha256=digest(published/'manifest.json'),cases=[],new_scores=0)
    for binding,original in zip(manifest['cases'],old['cases']):
        root=directory/binding['input_id'];require(digest(root/'case.json')==binding['case_sha256'],'Changed case')
        c=read(root/'case.json');require(c['capture']==original['capture'],'Changed capture')
        require(c['diagnostic_only'] is True,'Not diagnostic-only')
        t={k:table(root,v) for k,v in c['tables'].items()}
        p,s,a,w,b,tr,lag=[t[k] for k in ('packets','service','arrivals','waits','blockers','transfers','matched_sends')]
        require(np.array_equal(p['packet'],np.arange(len(p['packet']))),'Packet row identity changed')
        def packet_refs(v):require(np.all((v>=0)&(v<len(p['packet']))),'Unbound packet reference')
        for f in (s,a,w):packet_refs(f['packet'])
        transfers=set(tr['transfer'].tolist());require(len(transfers)==len(tr['transfer']),'Duplicate transfer')
        require(set(p['transfer'].tolist())<=(transfers|{-1}),'Unknown packet transfer')
        require(set(lag['transfer'].tolist())<=transfers,'Unknown matched submission')
        require(np.all((p['source_cna']==-1)|(p['source_device']==((p['source_cna']>>4)&4095))),'CNA decoding differs')
        known=(p['source_device']>=0)&(p['native_source']>=0)
        require(np.all(p['source_device'][known]==p['native_source'][known]),'Native creator differs from decoded device')
        require(np.all(a['time_ns']>=p['native_created_ns'][a['packet']]),'Arrival precedes packet creation')
        access=np.bincount(a['packet'][a['source_access']==1],minlength=len(p['packet']))
        require(np.array_equal(access,p['source_access_count']),'Lost/repeated source-access mapping')
        parent=p['request_packet'];known=parent>=0;packet_refs(parent[known])
        require(np.all(p['native_created_ns'][known]>=p['native_created_ns'][parent[known]]),'Response before request')
        require(np.all(p['transfer'][known]==p['transfer'][parent[known]]),'Response linked to another transfer')
        lookup={int(k):i for i,k in enumerate(tr['transfer'])}
        for tid,born,remote in zip(p['transfer'],p['native_created_ns'],p['response']):
            if tid>=0 and born>=0:require(born>=tr['submit_ns'][lookup[int(tid)]],'Native packet before original submission')
        require(np.all(s['duration_with_ifg_ns']==s['serialization_ns']+c['ifg_ns']),'IFG mismatch')
        require(np.all(abs(s['serialization_ns']-s['bytes']*8e9/s['rate_bps'])<=1.000001),'Serialization differs from actual rate')
        require(set(zip(s['node'].tolist(),s['port'].tolist()))<={(p['node_id'],p['port_id']) for p in c['ports']},'Unlisted service port')
        queued=s['enqueue_ns']>=0
        require(np.all(s['enqueue_ns'][queued]<=s['dequeue_ns'][queued]) and np.all(s['dequeue_ns'][queued]==s['start_ns'][queued]),'FIFO chronology differs')
        positive=queued&(s['dequeue_ns']>s['enqueue_ns'])
        expected=Counter(zip(s['packet'][positive].tolist(),s['node'][positive].tolist(),s['port'][positive].tolist(),s['enqueue_ns'][positive].tolist(),s['dequeue_ns'][positive].tolist()))
        actual=Counter(zip(w['packet'].tolist(),w['node'].tolist(),w['port'].tolist(),w['start_ns'].tolist(),w['end_ns'].tolist()))
        require(expected==actual,'Positive FIFO wait coverage differs')
        require(len(s['packet'])==c['network_event_counts']['tx'],'Missing transmissions')
        require(np.all((b['wait']>=0)&(b['wait']<len(w['packet']))) and np.all((b['tx']>=0)&(b['tx']<len(s['packet']))),'Bad blocker reference')
        wi,ti=b['wait'],b['tx'];left=np.maximum(w['start_ns'][wi],s['start_ns'][ti]);right=np.minimum(w['end_ns'][wi],s['start_ns'][ti]+s['duration_with_ifg_ns'][ti])
        require(np.all(right>left) and np.array_equal(left,b['overlap_start_ns']) and np.array_equal(right,b['overlap_end_ns']),'Blocker overlap mismatch')
        require(np.all(w['node'][wi]==s['node'][ti]) and np.all(w['port'][wi]==s['port'][ti]),'Blocker from another port')
        owner=p['source_cna'][w['packet'][wi]];other=s['source_cna'][ti]
        relation=np.where((owner<0)|(other<0),2,(owner!=other).astype(np.int64))
        require(np.array_equal(relation,b['relation']),'Source relation mismatch')
        for value,column in [(0,'same_source_ns'),(1,'other_source_ns'),(2,'unknown_source_ns')]:
            mask=relation==value;total=np.zeros(len(w['packet']),dtype=np.int64);np.add.at(total,wi[mask],(right-left)[mask])
            require(np.array_equal(total,w[column]),'Overlap totals mismatch')
        require(np.all(w['end_ns']-w['start_ns']==w['same_source_ns']+w['other_source_ns']+w['unknown_source_ns']+w['unexplained_ns']),'Wait residual mismatch')
        require(digest(root/'events.json')==c['events_sha256'],'Changed original-event projection')
        frozen=frozen_counts(published,original,a,s)
        result=dict(input_id=c['input_id'],condition=c['condition'],packets=len(p['packet']),transmissions=len(s['packet']),waits=len(w['packet']),blocker_overlaps=len(b['wait']),missing=c['missing'],normal_comparable=c['comparison_to_normal']['normal_comparable_business_workload'],exact_original_counter_reconstruction=frozen)
        report['cases'].append(result);print('Independently checked',c['condition'],flush=True)
    report.update(status='completed',wall_seconds=time.monotonic()-start,checker_sha256=digest(Path(__file__)))
    output.parent.mkdir(parents=True,exist_ok=True)
    with output.open('x') as f:json.dump(report,f,indent=2);f.write('\n')
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--package',type=Path,required=True);p.add_argument('--published',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();check(a.package,a.published,a.output)


if __name__=='__main__':main()
