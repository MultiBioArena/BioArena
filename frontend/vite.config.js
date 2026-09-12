import {defineConfig} from 'vite';
import react from '@vitejs/plugin-react';
export default defineConfig({plugins:[react()],server:{proxy:{'/api/fomo-screens':'http://127.0.0.1:8144','/api/execution':'http://127.0.0.1:8142','/api/challenge':'http://127.0.0.1:8143','/api/market-board':'http://127.0.0.1:8142','/api':'http://127.0.0.1:8140','/ws':{target:'ws://127.0.0.1:8140',ws:true}}}});
