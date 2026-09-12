import type {BioId} from './types';

export const researchSources:Record<BioId,{
  study:string;
  geometry:string;
  links:{label:string;url:string}[];
}>={
  worm:{
    study:'Cook et al. (2019) · Connectome study',
    geometry:'300 of 302 simulated cells have matched NeuroPAL atlas positions. The view follows the body axis, with transverse spacing expanded for readability. AVB / AVA activity drives illustrative body waves; the movement is not a biomechanical reconstruction.',
    links:[
      {label:'WormWiring · Corrected connectivity tables',url:'https://wormwiring.org/si/SI%205%20Connectome%20adjacency%20matrices,%20corrected%20July%202020.xlsx'},
      {label:'NeuroPAL · Atlas coordinates',url:'https://github.com/openworm/NeuroPAL/blob/85783437bea1112c1e4b1cacaac3e5337e7ce4a4/data/CanonicalPositions/LowResAtlasWithHighResHeadsAndTails.csv'},
    ],
  },
  adult:{
    study:'Shiu et al. (2024) · LIF brain model',
    geometry:'14,000 measured FlyWire soma positions: 9,304 simulated cells and 4,696 static visual-system reference cells. The other 696 simulated cells remain in the engine without spatial markers. Reference cells do not receive invented activity.',
    links:[
      {label:'Shiu model · Connectivity v783',url:'https://github.com/philshiu/Drosophila_brain_model/tree/91bdd1e7dcf193f3e7ca5a8933497fcef63b7960'},
      {label:'FlyWire · Soma coordinates and annotations',url:'https://github.com/flyconnectome/flywire_annotations/blob/8587524c1748ce5ef2080822a2fc890fc03bf597/supplemental_files/Supplemental_file1_neuron_annotations.tsv'},
    ],
  },
  larva:{
    study:'Winding et al. (2023) · Larval brain connectome',
    geometry:'3,016 brain and input neurons, arranged using curated left/right identities, homologous pairs and cell types. The two ribbons and their spacing are an organizational layout, not measured anatomical coordinates or a complete ventral nerve cord. Both sides belong to one simulated brain, with cross-side connections preserved.',
    links:[
      {label:'Pedigo et al. (2023) · Bilateral organization',url:'https://elifesciences.org/articles/83739'},
      {label:'Larval dataset · Hemisphere and pair annotations',url:'https://github.com/neurodata/bilateral-connectome/blob/0ff9bbe0515504b88ac827c6a31481db47a92ad2/data/elife/meta_data.csv'},
      {label:'Larval dataset · Connection table',url:'https://github.com/neurodata/bilateral-connectome/blob/0ff9bbe0515504b88ac827c6a31481db47a92ad2/data/elife/G_edgelist.txt'},
    ],
  },
};
