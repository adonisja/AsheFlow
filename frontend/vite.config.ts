import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import basicSsl from '@vitejs/plugin-basic-ssl'
import * as fs from 'fs'
import * as path from 'path'

/**
 * Phone testing needs HTTPS, not just `--host`.
 *
 * A LAN IP over plain http is NOT a secure context, and the browser then
 * removes the camera-adjacent APIs outright — measured on 192.168.x over http:
 * `BarcodeDetector` and `navigator.mediaDevices` are both simply ABSENT, while
 * `<input capture>` still works. That combination is the dangerous one: the
 * label scanner would still open the camera and still run OCR, and barcode
 * reading would silently never fire, which reads as "the barcode half is
 * broken" rather than "the page is not on HTTPS".
 *
 * Opt-in via `npm run dev:https` so the default `npm run dev` keeps its
 * existing localhost/proxy behaviour untouched.
 *
 * THE CERT MATTERS, not just the TLS. basic-ssl issues a cert whose
 * subjectAltName lists only localhost / 127.0.0.1 / ::1. Opened at the laptop's
 * real address the host is absent from the cert entirely, and Chrome on iOS
 * then withholds its "Proceed anyway" link — the phone reached the server and
 * still dead-ended on ERR_CERT_AUTHORITY_INVALID with no way through.
 *
 * `scripts/field-cert.sh` writes a cert covering every address this machine
 * currently answers on. When it is present we use it; otherwise fall back to
 * basic-ssl so `dev:https` still works with no setup.
 */
const useHttps = process.env.HTTPS === 'true'

const certDir = path.resolve(__dirname, '.cert')
const certPath = path.join(certDir, 'cert.pem')
const keyPath = path.join(certDir, 'key.pem')
const hasFieldCert = fs.existsSync(certPath) && fs.existsSync(keyPath)

// https://vite.dev/config/
export default defineConfig({
  // Only fall back to basic-ssl when no field cert exists — loading both would
  // let the plugin override the cert that actually covers the phone's address.
  plugins: [react(), ...(useHttps && !hasFieldCert ? [basicSsl()] : [])],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    }
  },
  server: {
    port: 3000,
    // Bind all interfaces only in HTTPS mode — that is the phone-testing path,
    // and exposing the dev server on the LAN by default is a change nobody
    // asked for.
    host: useHttps ? true : undefined,
    open: !useHttps,
    ...(useHttps && hasFieldCert
      ? { https: { cert: fs.readFileSync(certPath), key: fs.readFileSync(keyPath) } }
      : {}),
    /**
     * Dev-only proxy to the staging API.
     *
     * Set `VITE_API_URL=/api/v1` in `.env.local` and the browser calls its OWN
     * origin, so CORS never applies and staging needs no config change. That
     * matters: `config.py` deliberately RAISES if CORS_ORIGINS contains
     * 'localhost' outside development, and CLAUDE.md documents how easily
     * staging's .env gets clobbered. Loosening a security rail for local
     * convenience is the wrong trade; a proxy costs nothing.
     *
     * Why it exists: an empty local DB renders every page as an empty state,
     * so UI work could not be seen before shipping. Four attempts at the crew
     * row shipped unviewed because of this.
     *
     * WRITES GO TO STAGING. Clicking "Mark Present" here marks someone present
     * in staging data. Acceptable for seed data; know it before clicking.
     *
     * Dev server only — `vite preview` serves static files and does not proxy.
     */
    proxy: {
      '/api': {
        // Staging by default so a fresh checkout has a working backend with no
        // setup. Point it at a local API with:
        //
        //   VITE_PROXY_TARGET=http://localhost:8010 npm run dev
        //
        // An env var rather than an edit here: this file is tracked, and
        // flipping it locally means either committing the local address by
        // accident or remembering to revert it every time.
        target: process.env.VITE_PROXY_TARGET || 'https://api-staging.asheflow.com',
        changeOrigin: true,
        // A local API is plain http and has no certificate to verify.
        secure: !process.env.VITE_PROXY_TARGET,
      },
    },
  }
})
