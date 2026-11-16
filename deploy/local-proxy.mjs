/** Loopback-only local edge. Fixed destinations; BFF routes always reach Next. */
import http from 'node:http';
import { pathToFileURL } from 'node:url';
const loopback = (url) => url.protocol === 'http:' && ['127.0.0.1','localhost','[::1]'].includes(url.hostname) && !url.username && !url.password && url.pathname === '/' && !url.search && !url.hash;
export function createProxy({ origin, frontend, backend }) {
  const canonical = new URL(origin), next = new URL(frontend), api = new URL(backend);
  if (![canonical,next,api].every(loopback)) throw new Error('Local proxy requires fixed loopback HTTP origins');
  const reject = (response,status,code) => { response.writeHead(status,{'Content-Type':'application/json','Cache-Control':'no-store'}); response.end(JSON.stringify({error:{code}})); };
  const server = http.createServer((request,response) => {
    if (request.headers.host !== canonical.host) {
      let alternate=false;
      try { const candidate = new URL('http://'+request.headers.host); alternate=loopback(candidate) && candidate.port===canonical.port; } catch {}
      if (alternate && request.method==='GET' && request.headers.accept?.includes('text/html')) {
        // Destination is configured. Incoming host never defines trust or target.
        response.writeHead(307,{Location:canonical.origin+request.url,'Cache-Control':'no-store'}); response.end();
      } else reject(response,421,'CANONICAL_ORIGIN_REQUIRED');
      return;
    }
    if (request.url.split('?')[0]==='/live/ws') { reject(response,426,'WEBSOCKET_UPGRADE_REQUIRED'); return; }
    const upstream = http.request({hostname:next.hostname,port:next.port,method:request.method,path:request.url,headers:request.headers},result => {
      response.writeHead(result.statusCode,result.headers); result.pipe(response);
    });
    upstream.setTimeout(45000,() => upstream.destroy());
    upstream.on('error',() => { if (!response.headersSent) reject(response,503,'FRONTEND_UNAVAILABLE'); else response.destroy(); });
    request.on('aborted',() => upstream.destroy());
    request.pipe(upstream);
  });
  const sockets=new Set();
  server.on('connection',socket => { sockets.add(socket);socket.on('close',() => sockets.delete(socket)); });
  server.on('upgrade',(request,socket,head) => {
    if (request.url!=='/live/ws' || request.headers.host!==canonical.host || request.headers.origin!==canonical.origin) {
      socket.end('HTTP/1.1 403 Forbidden\r\nConnection: close\r\n\r\n'); return;
    }
    const headers={...request.headers,host:api.host};
    delete headers.cookie;delete headers.authorization;
    const upstream=http.request({hostname:api.hostname,port:api.port,path:'/live/ws',headers});
    upstream.on('upgrade',(response,remote,remoteHead) => {
      socket.write('HTTP/1.1 101 Switching Protocols\r\n'+Object.entries(response.headers).map(([k,v]) => `${k}: ${v}\r\n`).join('')+'\r\n');
      if (remoteHead.length) socket.write(remoteHead);
      if (head.length) remote.write(head);
      socket.pipe(remote).pipe(socket);
      remote.on('error',() => socket.destroy());socket.on('error',() => remote.destroy());socket.on('close',() => remote.destroy());
    });
    upstream.on('response',response => { socket.end(`HTTP/1.1 ${response.statusCode} Rejected\r\nConnection: close\r\n\r\n`);response.resume(); });
    upstream.on('error',() => socket.destroy());
    socket.on('close',() => upstream.destroy());
    upstream.end();
  });
  server.shutdown=() => { for (const socket of sockets) socket.destroy(); server.close(); };
  return server;
}
if (process.argv[1] && import.meta.url===pathToFileURL(process.argv[1]).href) {
  const origin=process.env.APP_ORIGIN ?? 'http://127.0.0.1:3000';
  const server=createProxy({origin,frontend:process.env.NEXT_INTERNAL_ORIGIN ?? 'http://127.0.0.1:3001',backend:process.env.FASTAPI_BASE_URL ?? 'http://127.0.0.1:8000'});
  server.listen(Number(new URL(origin).port), '127.0.0.1', () => console.log('Canonical browser URL: '+origin));
  for (const signal of ['SIGINT','SIGTERM']) process.on(signal,() => server.shutdown());
}
