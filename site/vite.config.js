import { defineConfig } from 'vite';
import { resolve } from 'path';

export default defineConfig({
    build: {
        rollupOptions: {
            input: {
                main: resolve(__dirname, 'index.html'),
                addresses: resolve(__dirname, 'addresses.html'),
                buildings: resolve(__dirname, 'buildings.html'),
                nds: resolve(__dirname, 'nds.html'),
                nrw: resolve(__dirname, 'nrw.html'),
                rlp: resolve(__dirname, 'rlp.html'),
            },
        },
    },
});
