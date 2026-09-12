from pathlib import Path
import json
import numpy as np
import pandas as pd
import pytest
from bio_arena.cell_connections import cell_connections,graph_data

pytestmark = pytest.mark.requires_data

ROOT=Path(__file__).resolve().parents[1]

@pytest.mark.parametrize('bio',['worm','adult','larva'])
def test_geometry_indices_match_exact_simulation_ids(bio):
    geometry=json.loads((ROOT/f'frontend/public/connectomes/{bio}.json').read_text())
    nodes=json.loads((ROOT/f'data/processed/{bio}/nodes.json').read_text())
    points=geometry['points']
    assert len({p['id'] for p in points})==len(points)
    assert all(p['index']<0 or nodes[p['index']]['id']==p['id'] for p in points)
    assert np.isfinite([p['position'] for p in points]).all()
    assert sum(p['index']>=0 for p in points)==geometry['located_simulated']

def test_fly_soma_units_and_static_context():
    geometry=json.loads((ROOT/'frontend/public/connectomes/adult.json').read_text())
    raw=pd.read_csv(ROOT/'data/raw/adult_annotations.tsv',sep='\t',usecols=['root_id','soma_x','soma_y','soma_z']).set_index('root_id')
    assert len(geometry['points'])==14000
    assert sum(p['index']<0 for p in geometry['points'])==4696
    for p in geometry['points'][::137]:
        microns=raw.loc[int(p['id'])].to_numpy(float)*[.004,.004,.04]
        assert np.allclose(p['source_position_um'],microns,atol=.001)

@pytest.mark.parametrize('bio',['worm','adult','larva'])
def test_selected_cell_connections_are_from_simulated_edges(bio):
    nodes,_,graph=graph_data(bio)
    i=17
    response=cell_connections(bio,nodes[i]['id'])
    incident=np.flatnonzero((graph['pre']==i)|(graph['post']==i))
    assert response['total_connections']==len(incident)
    assert response['shown_connections']==min(200,len(incident))
    for edge in response['connections']:
        pre,post=(nodes[i]['id'],edge['partner_id']) if edge['direction']=='outgoing' else (edge['partner_id'],nodes[i]['id'])
        assert any(nodes[graph['pre'][j]]['id']==pre and nodes[graph['post'][j]]['id']==post and graph['raw'][j]==edge['weight'] for j in incident)
    assert cell_connections(bio,'absent-id') is None
