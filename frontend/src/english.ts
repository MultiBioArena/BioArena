import type {BioId} from './types';

export const displayNames:Record<BioId,string>=new Proxy<Record<string,string>>({worm:'Worm',adult:'Fly',larva:'Larva'},{get:(names,key)=>typeof key==='string'?(Object.hasOwn(names,key)?names[key]:key.replace(/[_-]/g,' ').replace(/^./,c=>c.toUpperCase())):undefined});

export const subtitles:Record<BioId,string>={
  worm:'C. elegans · Adult hermaphrodite',
  adult:'D. melanogaster · Adult · FlyWire v783',
  larva:'D. melanogaster · First-instar larva',
};

export const englishReason=(text:string)=>text;
