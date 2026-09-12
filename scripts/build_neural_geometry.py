"""Export source-based display geometry without changing any simulation graph."""
from pathlib import Path
from hashlib import sha256
import json
import re
import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'frontend/public/connectomes'
OUT.mkdir(parents=True,exist_ok=True)
SOURCES=json.loads((ROOT/'data/raw/sources.json').read_text())['files']

def nodes(key):return json.loads((ROOT/f'data/processed/{key}/nodes.json').read_text())
def save(key,points,method,source,details):
    payload={'bio_id':key,'version':'neural-geometry-v1','method':method,'source':source,
             'details':details,'points':points,'simulated_neurons':len(nodes(key)),
             'located_simulated':sum(p['index']>=0 for p in points),'displayed_points':len(points)}
    path=OUT/f'{key}.json';path.write_text(json.dumps(payload,separators=(',',':'),allow_nan=False))
    print(key,len(points),'points;',payload['located_simulated'],'simulated;',path.stat().st_size,'bytes')
    return {'file':path.name,'sha256':sha256(path.read_bytes()).hexdigest(),'source':source,'details':details}

def worm():
    atlas=pd.read_csv(ROOT/'data/raw/worm_atlas.csv',names=['id','x','y','z']).set_index('id')
    points=[];missing=[]
    for n in nodes('worm'):
        name=re.sub(r'([A-Z]+)0+(\d+)$',r'\1\2',n['id'])
        if name not in atlas.index:missing.append(n['id']);continue
        row=atlas.loc[name];u=float(row.x/800)
        points.append({'id':n['id'],'name':n['name'],'type':n['cell_type'],'index':n['index'],
            'position':[round(float(row.z)*.007,5),round((.5-u)*3.0,5),round(float(row.y)*.007,5)],
            'source_position_um':[float(row.x),float(row.y),float(row.z)],'axis':u,'region':n['cell_type'],'side':n['side']})
    source='https://github.com/openworm/NeuroPAL/blob/85783437bea1112c1e4b1cacaac3e5337e7ce4a4/data/CanonicalPositions/LowResAtlasWithHighResHeadsAndTails.csv'
    return save('worm',points,'Canonical body axis',source,{
        'atlas_sha256':sha256((ROOT/'data/raw/worm_atlas.csv').read_bytes()).hexdigest(),
        'source_units':'micrometers','missing_coordinates':missing,
        'transform':'x/800 gives anterior-posterior fraction; dorsal/lateral offsets expanded for readability. Body undulation is a readout-driven illustration.',
        'name_matching':'AS01 -> AS1 and equivalent zero-padded motor names; all other names exact',
        'motion':'AVB activity drives forward wave; AVA activity drives reverse wave. This is not a biomechanical simulation.'})

def adult():
    meta=pd.read_csv(ROOT/'data/raw/adult_annotations.tsv',sep='\t',low_memory=False).fillna('')
    coords=meta[['soma_x','soma_y','soma_z']].apply(pd.to_numeric,errors='coerce')
    meta=meta.loc[coords.notna().all(axis=1)&coords.gt(0).all(axis=1)].copy()
    sim={n['id']:n for n in nodes('adult')};in_sim=meta.root_id.astype(str).isin(sim)
    modeled=meta.loc[in_sim];context=meta.loc[~in_sim & meta.super_class.isin(['optic','visual_projection','visual_centrifugal'])]
    count=14000-len(modeled);parts=[]
    for side in ['left','right']:
        group=context.loc[context.side.eq(side)]
        parts.append(group.sample(n=count//2+(side=='right' and count%2),random_state=20260911))
    shown=pd.concat([modeled,*parts]).sort_values('root_id')
    xyz=shown[['soma_x','soma_y','soma_z']].to_numpy(float)*np.array([.004,.004,.04])
    center=(xyz.min(axis=0)+xyz.max(axis=0))/2;scale=3.15/np.ptp(xyz,axis=0).max()
    points=[]
    for (_,row),coordinate in zip(shown.iterrows(),xyz):
        root=str(row.root_id);node=sim.get(root);p=(coordinate-center)*scale
        points.append({'id':root,'name':row.cell_type or row.cell_class or row.super_class,
            'type':row.cell_class or row.super_class,'index':node['index'] if node else -1,
            'position':[round(float(p[0]),5),round(float(-p[1]),5),round(float(p[2]),5)],
            'source_position_um':np.round(coordinate,3).tolist(),'region':row.super_class,'side':row.side})
    return save('adult',points,'FlyWire soma coordinates',SOURCES['adult_annotations.tsv']['url'],{
        'source_sha256':SOURCES['adult_annotations.tsv']['sha256'],'source_units':'4 x 4 x 40 nm voxels, converted to micrometers',
        'center_um':center.tolist(),'isotropic_scale':float(scale),'axis_mapping':'[x, -y, z]',
        'reference_points':count,'sampling':'All simulated cells with valid soma coordinates; remaining points sampled equally from left/right visual classes with seed 20260911.',
        'context_activity':'Reference cells are static and do not receive invented spikes. 696 simulated cells without soma coordinates are omitted from the spatial view.'})

def larva():
    meta=pd.read_csv(ROOT/'data/raw/larva_neurons.csv',index_col=0,low_memory=False)
    model=nodes('larva');meta=meta.loc[[int(n['id']) for n in model]].copy()
    order=['sensories','ascendings','PNs','PNs-somato','LNs','LHNs','MBINs','KCs','MBONs','MB-FBNs','CNs','FFNs','RGNs','unk','pre-dSEZs','dSEZs','pre-dVNCs','dVNCs']
    groups={name:i for i,name in enumerate(order)};meta['group_order']=meta.simple_group.map(groups)
    meta['pair_key']=[int(r.pair_id) if r.pair_id>=0 else int(i)+100000000 for i,r in meta.iterrows()]
    # Curated pair IDs align homologues; missing pairs remain individual cells.
    pairs=meta.groupby('pair_key').agg(group=('group_order','min')).sort_values(['group','pair_key'])
    rows={int(key):i for i,key in enumerate(pairs.index)};points=[]
    for node,(_,row) in zip(model,meta.iterrows()):
        rank=rows[int(row.pair_key)];y=1.4-2.8*(rank//8)/max(1,(len(pairs)-1)//8)
        side=-1 if row.hemisphere=='L' else 1
        x=side*(.17+(rank%8)*.04+.025*np.sin(row.group_order*.7))
        z=((rank//8)%5-2)*.024
        points.append({'id':node['id'],'name':node['name'],'type':node['cell_type'],'index':node['index'],
            'position':[round(float(x),5),round(float(y),5),round(float(z),5)],
            'region':row.simple_group,'side':row.hemisphere,'pair_id':int(row.pair_id)})
    return save('larva',points,'Bilateral circuit organization',SOURCES['larva_neurons.csv']['url'],{
        'source_sha256':SOURCES['larva_neurons.csv']['sha256'],
        'layout':'Curated hemisphere, pair_id and cell-type order; homologous pairs share longitudinal position. Within-type order is deterministic.',
        'group_order':order,'paired_cells':int((meta.pair_id>=0).sum()),
        'scope':'3016 brain-and-input neurons, not a complete ventral nerve cord. These are organization coordinates, not measured soma positions.'})

if __name__=='__main__':
    manifest={key:fn() for key,fn in [('worm',worm),('adult',adult),('larva',larva)]}
    (OUT/'manifest.json').write_text(json.dumps(manifest,indent=2))
