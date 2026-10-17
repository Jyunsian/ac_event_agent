// Temporary public preview, explicitly requested by the owner. Never exposes source files or internal APIs.
import http from 'node:http';
import { readFile, realpath } from 'node:fs/promises';
import path from 'node:path';

const root = await realpath(new URL('../web/dist', import.meta.url));
const types = { '.html': 'text/html; charset=utf-8', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.png': 'image/png', '.woff2': 'font/woff2', '.ico': 'image/x-icon' };
const server = http.createServer(async (req, res) => {
  res.setHeader('Cache-Control', 'no-store, no-transform');
  res.setHeader('X-Content-Type-Options', 'nosniff');
  res.setHeader('Referrer-Policy', 'no-referrer');
  res.setHeader('X-Frame-Options', 'DENY');
  try {
    const url = new URL(req.url, 'http://localhost');
    const pathname = decodeURIComponent(url.pathname);
    if (pathname.includes('..') || pathname.includes('\\') || pathname.includes('%') || pathname.includes('\0') || pathname.startsWith('/internal')) {
      res.writeHead(404); return res.end();
    }
    if (!['GET', 'HEAD', 'OPTIONS'].includes(req.method) && req.headers.origin && new URL(req.headers.origin).host !== req.headers.host) {
      res.writeHead(403); return res.end();
    }
    if (pathname.startsWith('/api/')) {
      const headers = { ...req.headers, host: '127.0.0.1:8094' };
      delete headers.authorization;
      delete headers.cookie;
      const upstream = http.request({ hostname: '127.0.0.1', port: 8094, path: pathname + url.search, method: req.method, headers }, response => {
        // Preserve byte-level report ETags through the public tunnel.
        res.writeHead(response.statusCode, { ...response.headers, 'cache-control': 'no-store, no-transform' });
        response.pipe(res);
      });
      upstream.on('error', () => { if (!res.headersSent) res.writeHead(502); res.end('Local service unavailable'); });
      upstream.setTimeout(180000, () => upstream.destroy());
      req.pipe(upstream);
      return;
    }
    if (!['GET', 'HEAD'].includes(req.method)) { res.writeHead(405); return res.end(); }
    let target;
    if (pathname === '/' || /^\/(workspace|upload|history|runs)(\/[^/.]+)?\/?$/.test(pathname)) target = path.join(root, 'index.html');
    else if (pathname.startsWith('/assets/') && !pathname.endsWith('.map')) target = await realpath(path.join(root, pathname));
    else { res.writeHead(404); return res.end(); }
    if (!target.startsWith(root + path.sep)) { res.writeHead(404); return res.end(); }
    const body = await readFile(target);
    res.setHeader('Content-Type', types[path.extname(target)] || 'application/octet-stream');
    res.end(req.method === 'HEAD' ? undefined : body);
  } catch { if (!res.headersSent) res.writeHead(404); res.end(); }
});
server.listen(5190, '127.0.0.1', () => console.log('Public preview gateway: http://127.0.0.1:5190'));
