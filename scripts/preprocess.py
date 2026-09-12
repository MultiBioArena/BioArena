"""Create auditable, versioned graph packages from downloaded research tables."""
from pathlib import Path
import hashlib
import json
import numpy as np
import pandas as pd
import openpyxl
from scipy.sparse import csr_array
from scipy.sparse.csgraph import breadth_first_order

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data/raw'
OUT = ROOT / 'data/processed'
CHANNELS = ['approach', 'avoid', 'volume', 'volatility']

def save(key, nodes, pre, post, raw, sign, groups, info, gap=None):
    folder = OUT / key
    folder.mkdir(parents=True, exist_ok=True)
    n = len(nodes)
    pre, post = np.asarray(pre, np.int32), np.asarray(post, np.int32)
    raw, sign = np.asarray(raw, np.float32), np.asarray(sign, np.float32)
    assert len(pre) and len(pre) == len(post) == len(raw) == len(sign)
    assert np.all(np.isfinite(raw)) and np.all(raw > 0)
    assert pre.min() >= 0 and max(pre.max(), post.max()) < n
    assert len({x['id'] for x in nodes}) == n
    for group in CHANNELS + ['buy', 'sell']:
        assert groups[group], (key, 'empty group', group)
    assert not set(groups['buy']) & set(groups['sell'])
    assert not set(sum([groups[x] for x in CHANNELS], [])) & set(groups['buy'] + groups['sell'])
    degrees = np.bincount(pre, minlength=n) + np.bincount(post, minlength=n)
    gap = gap or ([], [], [])
    for i, node in enumerate(nodes):
        node.update(index=i, role='inter', channel=None)
    for name, indices in groups.items():
        for i in indices:
            nodes[i]['role'] = 'input' if name in CHANNELS else name
            nodes[i]['channel'] = name
    # Virtual source reaches all sensory ports, then follows biological directed edges.
    inputs = sorted(set(sum([groups[c] for c in CHANNELS], [])))
    graph = csr_array((np.ones(len(pre)+len(inputs)),
                       (np.r_[pre, np.full(len(inputs), n)], np.r_[post, inputs])), shape=(n+1,n+1))
    reached = set(breadth_first_order(graph, n, directed=True, return_predecessors=False).tolist())
    reachability = {c: sum(i in reached for i in groups[c])/len(groups[c]) for c in ['buy','sell']}
    assert min(reachability.values()) > 0, (key, 'no sensory-output path')
    sample = []
    for group in CHANNELS + ['buy','sell']:
        sample.extend(groups[group][:16])
    sample = list(dict.fromkeys(sample))
    incident = np.bincount(post[np.isin(pre, sample)], minlength=n)
    incident += np.bincount(pre[np.isin(post, sample)], minlength=n)
    for i in np.argsort(-incident, kind='stable'):
        if int(i) not in sample:
            sample.append(int(i))
        if len(sample) >= min(n, 180):
            break
    position = {i: k for k,i in enumerate(sample)}
    visible = np.flatnonzero(np.isin(pre,sample) & np.isin(post,sample))
    visible = visible[np.argsort(-raw[visible],kind='stable')[:500]]
    vis_edges = [[position[int(pre[k])],position[int(post[k])],float(raw[k]),float(sign[k])] for k in visible]
    groups = {k:[int(x) for x in v] for k,v in groups.items()}
    np.savez_compressed(folder/'graph.npz', pre=pre, post=post, raw=raw, sign=sign,
                        gap_pre=np.asarray(gap[0],np.int32),gap_post=np.asarray(gap[1],np.int32),
                        gap_raw=np.asarray(gap[2],np.float32), sample=np.asarray(sample,np.int32))
    (folder/'nodes.json').write_text(json.dumps(nodes,ensure_ascii=False))
    (folder/'mapping.json').write_text(json.dumps(groups,indent=2))
    (folder/'visual.json').write_text(json.dumps({'nodes':[nodes[i] for i in sample], 'edges':vis_edges,
        'layout':'Schematic functional layout; positions are not anatomical coordinates', 'sample_size':len(sample)}))
    files = ['graph.npz','nodes.json','mapping.json','visual.json']
    hashes = {f:hashlib.sha256((folder/f).read_bytes()).hexdigest() for f in files}
    provenance = json.loads((RAW/'sources.json').read_text())
    source_names = info.pop('source_files')
    manifest = dict(info, id=key, neurons=n, edges=len(pre), raw_weight_total=float(raw.sum()),
                    electrical_directed_edges=len(gap[0]), isolated_neurons=int((degrees==0).sum()),
                    sensory_output_reachability=reachability, groups={k:len(v) for k,v in groups.items()},
                    processed_sha256=hashes, sources={x:provenance['files'][x] for x in source_names},
                    preprocessing_version='bio-arena-v1')
    (folder/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
    print(key, n, 'neurons,',len(pre),'edges; reachable',reachability,flush=True)

def worm():
    workbook = openpyxl.load_workbook(RAW/'worm_cells.xlsx',read_only=True,data_only=True)
    types = {}
    for sheet in ['pharynx','sex-shared','hermaphrodite specific']:
        for row in workbook[sheet].values:
            if row[0] and str(row[1]) in ['sensory','interneuron','motorneuron','neuron']:
                types[str(row[0])] = str(row[1])
    ids = sorted(types)
    assert len(ids)==302
    idx = {x:i for i,x in enumerate(ids)}
    workbook = openpyxl.load_workbook(RAW/'worm.xlsx',read_only=True,data_only=True)
    def matrix(sheet):
        rows = list(workbook[sheet].values)
        cols = rows[2]
        a,b,w = [],[],[]
        for row in rows[3:]:
            if row[2] not in idx: continue
            for j, value in enumerate(row[3:],3):
                if cols[j] in idx and isinstance(value,(int,float)) and value>0:
                    a.append(idx[row[2]]); b.append(idx[cols[j]]); w.append(value)
        return a,b,w
    pre,post,raw = matrix('hermaphrodite chemical')
    gap = matrix('hermaphrodite gap jn symmetric')
    def port(names):return [idx[x] for x in names if x in idx]
    groups = {'approach':port(['AWAL','AWAR','AWCL','AWCR']),
              'avoid':port(['ASHL','ASHR']), 'volume':port(['ASEL','ASER']),
              'volatility':port(['ALML','ALMR','PLML','PLMR']),
              'buy':port(['AVBL','AVBR','PVCL','PVCR']),
              'sell':port(['AVAL','AVAR','AVDL','AVDR','AVEL','AVER'])}
    inhibitory = {x for x in ids if x.startswith(('DD','VD','RME')) or x in ['RIS','AVL','DVB']}
    nodes = [{'id':x,'name':x,'cell_type':types[x], 'side':'left' if x.endswith('L') else 'right' if x.endswith('R') else 'center',
              'polarity':'GABA-class proxy' if x in inhibitory else 'assumed excitatory'} for x in ids]
    save('worm',nodes,pre,post,raw,[-1 if ids[i] in inhibitory else 1 for i in pre],groups,{
        'name':'C. elegans','subtitle':'C. elegans · Adult hermaphrodite','color':'#b7e480',
        'source_files':['worm.xlsx','worm_cells.xlsx'],'paper':'https://www.nature.com/articles/s41586-019-1352-7',
        'license':'Verify original Cook/WormWiring data reuse terms; preserve attribution',
        'weight_units':'EM section counts / size-weighted connectivity, not individual synapse counts',
        'selection':'All 302 annotated hermaphrodite neurons; non-neuronal effectors excluded; absent rows retained as zero connections',
        'assumptions':['LIF approximates mostly graded-potential neurons.',
            'DD/VD/RME/RIS/AVL/DVB inhibitory class proxy; all other chemical signs assumed positive. Receptor-level signs not verified.',
            'Forward-related AVB/PVC = buy; backward-related AVA/AVD/AVE = sell is an engineered mapping.',
            'Symmetric electrical table used as directed voltage-difference coupling without duplicating entries.']},gap)

def larva():
    meta = pd.read_csv(RAW/'larva_neurons.csv',index_col=0,keep_default_na=False)
    meta = meta.loc[meta.brain_and_inputs == True].sort_index()
    assert len(meta)==3016
    ids = meta.index.to_numpy(np.int64)
    idx = {x:i for i,x in enumerate(ids)}
    edges = pd.read_csv(RAW/'larva_edges.txt',sep=' ',names=['pre','post','weight'])
    edges = edges[edges.pre.isin(idx)&edges.post.isin(idx)]
    pre=edges.pre.map(idx).to_numpy(np.int32);post=edges.post.map(idx).to_numpy(np.int32)
    def port(mask):return np.flatnonzero(np.asarray(mask)).tolist()
    # ORN left/right encode signed market channels; not an innate approach/avoid claim.
    orn = meta.class2.eq('ORN') & meta.inputs.eq(True)
    groups={'approach':port(orn & meta.left.eq(True)), 'avoid':port(orn & meta.right.eq(True)),
            'volume':port(meta.class2.isin(['photoRh5','photoRh6']) & meta.inputs.eq(True)),
            'volatility':port(meta.class2.eq('MN') & meta.inputs.eq(True)),
            'buy':port(meta.dVNCs.eq(True) & meta.left.eq(True)),
            'sell':port(meta.dVNCs.eq(True) & meta.right.eq(True))}
    signs=np.where(meta.LNs.eq(True).to_numpy(),-1,1)
    nodes=[{'id':str(id),'name':str(row['name']),'cell_type':str(row['simple_group']),
            'side':str(row['hemisphere']), 'polarity':'assumed inhibitory LN' if signs[i]<0 else 'assumed excitatory'}
           for i,(id,row) in enumerate(meta.iterrows())]
    save('larva',nodes,pre,post,edges.weight.to_numpy(),signs[pre],groups,{
        'name':'Drosophila larva','subtitle':'D. melanogaster · First-instar larva','color':'#a7b7ef',
        'source_files':['larva_edges.txt','larva_neurons.csv'],'paper':'https://pmc.ncbi.nlm.nih.gov/articles/PMC7614541/',
        'license':'Winding 2023 paper CC BY 4.0; tables distributed by coauthor Pedigo in bilateral-connectome',
        'weight_units':'Aggregated directed connection weights from coauthor export',
        'selection':'Exact brain_and_inputs annotation (3016 nodes), includes isolates; induced graph from coauthor eLife export',
        'assumptions':['Export contains no comprehensive neurotransmitter signs: LNs assigned inhibitory, others excitatory, as an explicit class-level hypothesis.',
            'Left/right ORNs encode positive/negative channels; left/right descending pools encode buy/sell. These meanings are engineered.',
            'All compartment connection types collapsed to a single-compartment LIF input; brain dataset is not a complete body model.']})

def adult(limit=10000):
    ids=pd.read_csv(RAW/'adult_neurons.csv',index_col=0).index.to_numpy(np.int64)
    ann=pd.read_csv(RAW/'adult_annotations.tsv',sep='\t',keep_default_na=False).set_index('root_id').reindex(ids).fillna('')
    con=pd.read_parquet(RAW/'adult.parquet',columns=['Presynaptic_Index','Postsynaptic_Index','Connectivity','Excitatory'])
    pre=con.Presynaptic_Index.to_numpy(np.int32);post=con.Postsynaptic_Index.to_numpy(np.int32)
    raw=con.Connectivity.to_numpy(np.float32);sign=con.Excitatory.to_numpy(np.float32)
    outgoing=np.bincount(pre,weights=raw,minlength=len(ids))
    def strongest(mask,k=64):
        candidates=np.flatnonzero(np.asarray(mask))
        return candidates[np.argsort(-outgoing[candidates],kind='stable')[:k]]
    ports={'approach':strongest(ann.cell_sub_class.eq('sugar/water')),
           'avoid':strongest(ann.cell_sub_class.eq('bitter')),
           'volume':strongest(ann.super_class.eq('sensory') & ann.cell_class.eq('olfactory')),
           'volatility':strongest(ann.cell_sub_class.eq('auditory')),
           'buy':np.flatnonzero(ann.super_class.eq('descending') & ann.side.eq('left')),
           'sell':np.flatnonzero(ann.super_class.eq('descending') & ann.side.eq('right'))}
    selected=ann.cell_class.eq('CX').to_numpy() | ann.super_class.eq('descending').to_numpy()
    for p in ports.values():selected[p]=True
    # Grow only central/sensory/descending relay nodes; retain fixed seeds and recurrent neighbourhoods.
    eligible=ann.super_class.isin(['central','sensory','descending','ascending','sensory_ascending','motor']).to_numpy()
    for iteration in range(3):
        score=np.bincount(post,weights=raw*selected[pre],minlength=len(ids))
        score+=np.bincount(pre,weights=raw*selected[post],minlength=len(ids))
        candidates=np.flatnonzero(eligible & ~selected & (score>0))
        need=(limit-int(selected.sum()) + (2-iteration))//(3-iteration)
        chosen=candidates[np.argsort(-score[candidates],kind='stable')[:need]]
        selected[chosen]=True
    assert selected.sum()==limit
    keep=selected[pre]&selected[post]
    remap=np.full(len(ids),-1,np.int32);remap[selected]=np.arange(limit,dtype=np.int32)
    internal=np.bincount(post[keep],weights=raw[keep],minlength=len(ids))
    total=np.bincount(post,weights=raw,minlength=len(ids))
    retained=np.divide(internal,total,out=np.zeros_like(total),where=total>0)
    nodes=[]
    for i in np.flatnonzero(selected):
        row=ann.iloc[i]
        name=row.cell_type or row.cell_class or row.super_class or str(ids[i])
        nodes.append({'id':str(ids[i]),'name':str(name),'cell_type':str(row.cell_class or row.super_class),
                      'side':str(row.side),'polarity':'Shiu v783 signed edge convention',
                      'predicted_nt':str(row.top_nt),'retained_input_fraction':round(float(retained[i]),4)})
    groups={k:remap[v].tolist() for k,v in ports.items()}
    save('adult',nodes,remap[pre[keep]],remap[post[keep]],raw[keep],sign[keep],groups,{
        'name':'Drosophila adult','subtitle':'D. melanogaster · Adult · FlyWire v783 subnetwork','color':'#f2b37f',
        'source_files':['adult.parquet','adult_neurons.csv','adult_annotations.tsv'],
        'paper':'https://www.nature.com/articles/s41586-024-07763-9','license':'FlyWire data CC BY-NC 4.0; Shiu model code MIT',
        'weight_units':'Synapse counts aggregated per directed neuron pair',
        'selection':'10000-node induced subgraph: CX + descending seeds + top 64 sensory cells/channel; 3 deterministic weighted neighbourhood expansions over central/sensory/descending/ascending/motor classes',
        'mean_retained_input_fraction':float(retained[selected].mean()),
        'full_model_neurons':len(ids),'full_model_edges':len(pre),
        'assumptions':['Shiu v783 edge polarities preserved. Predicted transmitter labels are not receptor-level functional validation.',
            'Removed external inputs are set to zero; recurrent subgraph dynamics are not a reproduction of the full Shiu model.',
            'Left/right descending pools assigned buy/sell; this is an engineered readout, not native financial behaviour.']})

if __name__=='__main__':
    worm();larva();adult()
