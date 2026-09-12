# Data sources and preprocessing

The original files are pinned to the versions below. Downloaded SHA-256 hashes, byte counts, and verification times are recorded in `data/raw/sources.json`.

| File | Version | Source |
| --- | --- | --- |
| `worm.xlsx` | Cook 2019; corrected July 2020 | [Original file](https://wormwiring.org/si/SI%205%20Connectome%20adjacency%20matrices,%20corrected%20July%202020.xlsx) |
| `worm_cells.xlsx` | Cook 2019 SI4 | [Original file](https://wormwiring.org/si/SI%204%20Cell%20lists.xlsx) |
| `worm_atlas.csv` | 85783437bea1112c1e4b1cacaac3e5337e7ce4a4 | [NeuroPAL atlas](https://raw.githubusercontent.com/openworm/NeuroPAL/85783437bea1112c1e4b1cacaac3e5337e7ce4a4/data/CanonicalPositions/LowResAtlasWithHighResHeadsAndTails.csv) |
| `adult.parquet` | 91bdd1e7dcf193f3e7ca5a8933497fcef63b7960 | [Original file](https://raw.githubusercontent.com/philshiu/Drosophila_brain_model/91bdd1e7dcf193f3e7ca5a8933497fcef63b7960/Connectivity_783.parquet) |
| `adult_neurons.csv` | 91bdd1e7dcf193f3e7ca5a8933497fcef63b7960 | [Original file](https://raw.githubusercontent.com/philshiu/Drosophila_brain_model/91bdd1e7dcf193f3e7ca5a8933497fcef63b7960/Completeness_783.csv) |
| `adult_annotations.tsv` | 8587524c1748ce5ef2080822a2fc890fc03bf597 | [Original file](https://raw.githubusercontent.com/flyconnectome/flywire_annotations/8587524c1748ce5ef2080822a2fc890fc03bf597/supplemental_files/Supplemental_file1_neuron_annotations.tsv) |
| `larva_edges.txt` | 0ff9bbe0515504b88ac827c6a31481db47a92ad2 | [Original file](https://raw.githubusercontent.com/neurodata/bilateral-connectome/0ff9bbe0515504b88ac827c6a31481db47a92ad2/data/elife/G_edgelist.txt) |
| `larva_neurons.csv` | 0ff9bbe0515504b88ac827c6a31481db47a92ad2 | [Original file](https://raw.githubusercontent.com/neurodata/bilateral-connectome/0ff9bbe0515504b88ac827c6a31481db47a92ad2/data/elife/meta_data.csv) |

## C. elegans

[Original study](https://www.nature.com/articles/s41586-019-1352-7)

All 302 annotated hermaphrodite neurons; non-neuronal effectors excluded; absent rows retained as zero connections

Weight units: EM section counts / size-weighted connectivity, not individual synapse counts.

Retained: 302 neurons and 3,709 chemical connections; no isolated nodes.

Model assumptions:

- LIF approximates mostly graded-potential neurons.
- DD/VD/RME/RIS/AVL/DVB inhibitory class proxy; all other chemical signs assumed positive. Receptor-level signs not verified.
- Forward-related AVB/PVC = buy; backward-related AVA/AVD/AVE = sell is an engineered mapping.
- Symmetric electrical table used as directed voltage-difference coupling without duplicating entries.

Reuse terms: Verify original Cook/WormWiring data reuse terms; preserve attribution.

Input/output pool sizes: `{"approach": 4, "avoid": 2, "volume": 2, "volatility": 4, "buy": 4, "sell": 6}`. Both readout pools are reachable from all selected sensory cells through directed paths. This does not establish physiological causality.

## Drosophila adult

[Original study](https://www.nature.com/articles/s41586-024-07763-9)

10000-node induced subgraph: CX + descending seeds + top 64 sensory cells/channel; 3 deterministic weighted neighbourhood expansions over central/sensory/descending/ascending/motor classes

Weight units: Synapse counts aggregated per directed neuron pair.

Retained: 10,000 neurons and 1,328,439 chemical connections; no isolated nodes.

Model assumptions:

- Shiu v783 edge polarities preserved. Predicted transmitter labels are not receptor-level functional validation.
- Removed external inputs are set to zero; recurrent subgraph dynamics are not a reproduction of the full Shiu model.
- Left/right descending pools assigned buy/sell; this is an engineered readout, not native financial behaviour.

Reuse terms: FlyWire data CC BY-NC 4.0; Shiu model code MIT.

Input/output pool sizes: `{"approach": 64, "avoid": 64, "volume": 64, "volatility": 64, "buy": 645, "sell": 646}`. Both readout pools are reachable from all selected sensory cells through directed paths. This does not establish physiological causality.

The source model contains 138,639 neurons and 15,091,983 directed edges; MaleCNS is not used. The induced graph retains about 71.4% of the selected neurons’ original incoming weight on average.

## Drosophila larva

[Original study](https://pmc.ncbi.nlm.nih.gov/articles/PMC7614541/)

For left/right pairing and connection organization, see [Pedigo et al. (2023), eLife](https://elifesciences.org/articles/83739). The view uses the pinned `hemisphere`, `pair_id`, and cell-type annotations; 2,788 cells have pair IDs. The two ribbons and their spacing are organizational coordinates, not measured anatomy or a complete ventral nerve cord. One LIF network simulates both sides and retains cross-side connections from the source table. Each neural card’s **Sources** button and **Method & data sources** list the studies, original tables, and coordinate sources; geometry hashes are also available.

Exact brain_and_inputs annotation (3016 nodes), includes isolates; induced graph from coauthor eLife export

Weight units: Aggregated directed connection weights from coauthor export.

Retained: 3,016 neurons and 107,344 chemical connections; 29 isolated nodes.

Model assumptions:

- Export contains no comprehensive neurotransmitter signs: LNs assigned inhibitory, others excitatory, as an explicit class-level hypothesis.
- Left/right ORNs encode positive/negative channels; left/right descending pools encode buy/sell. These meanings are engineered.
- All compartment connection types collapsed to a single-compartment LIF input; brain dataset is not a complete body model.

Reuse terms: Winding 2023 paper CC BY 4.0; tables distributed by coauthor Pedigo in bilateral-connectome.

Input/output pool sizes: `{"approach": 21, "avoid": 21, "volume": 29, "volatility": 155, "buy": 91, "sell": 91}`. Both readout pools are reachable from all selected sensory cells through directed paths. This does not establish physiological causality.

## Reproducible processing

1. `fetch_data.py` streams downloads and records sources, versions, and SHA-256 hashes.
2. `preprocess.py` selects nodes using original annotations, retains isolates in the selected set, and assigns consistent indices.
3. Preserve directed weighted connections and document sign assumptions; process worm electrical coupling separately.
4. Select sensory and descending/motor readout pools, then verify directed reachability.
5. Export graph NPZ files, complete node JSON, mappings, deterministic display samples, and hash manifests.
6. `calibrate.py` uses eight fixed synthetic stimuli, eight warmup windows, and 32 measurement windows; it saves the protocol, seed, and parameter signature.
7. Startup checks artifact hashes and calibration signatures; each run manifest records the selected data.

The studies and connection tables provide neural structure, not financial decision labels. All buy/sell meanings are engineered mappings. Full processing details are in the code and each model’s `manifest.json`.
