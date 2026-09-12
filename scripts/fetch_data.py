"""Fetch fixed public graph tables; never download EM volumes or model outputs."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
import json
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
SHIU = '91bdd1e7dcf193f3e7ca5a8933497fcef63b7960'
ANNOTATIONS = '8587524c1748ce5ef2080822a2fc890fc03bf597'
LARVA = '0ff9bbe0515504b88ac827c6a31481db47a92ad2'
RAW = 'https://raw.githubusercontent.com'
SOURCES = {
    'worm_atlas.csv': (f'{RAW}/openworm/NeuroPAL/85783437bea1112c1e4b1cacaac3e5337e7ce4a4/data/CanonicalPositions/LowResAtlasWithHighResHeadsAndTails.csv', '85783437bea1112c1e4b1cacaac3e5337e7ce4a4'),
    'worm.xlsx': ('https://wormwiring.org/si/SI%205%20Connectome%20adjacency%20matrices,%20corrected%20July%202020.xlsx', 'Cook 2019; corrected July 2020'),
    'worm_cells.xlsx': ('https://wormwiring.org/si/SI%204%20Cell%20lists.xlsx', 'Cook 2019 SI4'),
    'adult.parquet': (f'{RAW}/philshiu/Drosophila_brain_model/{SHIU}/Connectivity_783.parquet', SHIU),
    'adult_neurons.csv': (f'{RAW}/philshiu/Drosophila_brain_model/{SHIU}/Completeness_783.csv', SHIU),
    'adult_annotations.tsv': (f'{RAW}/flyconnectome/flywire_annotations/{ANNOTATIONS}/supplemental_files/Supplemental_file1_neuron_annotations.tsv', ANNOTATIONS),
    'larva_edges.txt': (f'{RAW}/neurodata/bilateral-connectome/{LARVA}/data/elife/G_edgelist.txt', LARVA),
    'larva_neurons.csv': (f'{RAW}/neurodata/bilateral-connectome/{LARVA}/data/elife/meta_data.csv', LARVA),
}

def fetch(item):
    name, (url, version) = item
    folder = ROOT / 'data/raw'
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    if not path.exists():
        temp = path.with_suffix(path.suffix + '.part')
        request = urllib.request.Request(url, headers={'User-Agent': 'BioArena/0.1 public-data-loader'})
        with urllib.request.urlopen(request, timeout=90) as response, temp.open('wb') as output:
            while block := response.read(1024 * 1024):
                output.write(block)
        temp.replace(path)
    digest = sha256(path.read_bytes()).hexdigest()
    print(f'{name}: {path.stat().st_size:,} bytes, sha256={digest[:12]}', flush=True)
    return name, {'url': url, 'version': version, 'bytes': path.stat().st_size,
                  'sha256': digest}

if __name__ == '__main__':
    with ThreadPoolExecutor(max_workers=3) as pool:
        entries = dict(pool.map(fetch, SOURCES.items()))
    (ROOT / 'data/raw/sources.json').write_text(json.dumps({
        'checked_at': datetime.now(timezone.utc).isoformat(), 'files': entries
    }, indent=2))
