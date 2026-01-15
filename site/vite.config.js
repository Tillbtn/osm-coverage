import { defineConfig } from 'vite';
import { resolve, dirname } from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

export default defineConfig({
    build: {
        rollupOptions: {
            input: {
                main: 'addresses.html',
            },
        },
    },
    server: {
        proxy: {
            '/api': 'http://localhost:5000'
        }
    }
},
);
