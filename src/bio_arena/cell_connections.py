"""On-demand incident connections from the exact simulated graph."""
from functools import lru_cache
from pathlib import Path
import json
import numpy as np
from .registry import validate_bio_id

ROOT=Path(__file__).resolve().parents[2]

@lru_cache(maxsize=16)
def graph_data(bio):
    validate_bio_id(bio)
    folder=ROOT/'data/processed'/bio
    nodes=json.loads((folder/'nodes.json').read_text())
    with np.load(folder/'graph.npz',allow_pickle=False) as z:
        arrays={key:z[key] for key in ['pre','post','raw','sign']}
    return nodes,{n['id']:i for i,n in enumerate(nodes)},arrays

@lru_cache(maxsize=256)
def cell_connections(bio,node_id):
    nodes,indices,g=graph_data(bio)
    if node_id not in indices:return None
    i=indices[node_id];incident=np.flatnonzero((g['pre']==i)|(g['post']==i))
    ranked=incident[np.argsort(-g['raw'][incident],kind='stable')]
    edges=[]
    for e in ranked[:200]:
        outgoing=int(g['pre'][e])==i;partner=int(g['post'][e] if outgoing else g['pre'][e])
        edges.append({'partner_id':nodes[partner]['id'],'direction':'outgoing' if outgoing else 'incoming',
                      'weight':float(g['raw'][e]),'sign':float(g['sign'][e])})
    return {'node':nodes[i],'connections':edges,'total_connections':len(incident),
            'shown_connections':len(edges),'scope':'Simulated subgraph; top 200 incident connections by weight. Lines join soma/display positions, not individual synapse sites.'}
