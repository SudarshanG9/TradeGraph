import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import { createProxy } from './local-proxy.mjs';
const listen = server => new Promise(resolve => server.listen(0,'127.0.0.1',() => resolve(server.address().port)));
const request = (port,path,headers={},method='GET') => new Promise((resolve,reject) => {
  const req=http.request({host:'127.0.0.1',port,path,headers,method},res => {let body='';res.on('data',c=>body+=c);res.on('end',()=>resolve({status:res.statusCode,headers:res.headers,body}));});req.on('error',reject);req.end();
});
test('proxy keeps every API behind Next and redirects only safe loopback navigation',async () => {
  const next=http.createServer((req,res)=>res.end('next:'+req.url));
  const backend=http.createServer((req,res)=>res.end('backend'));
  const nextPort=await listen(next), backendPort=await listen(backend);
  // Use a reserved listener to choose the public port before constructing policy.
  const reservation=http.createServer();const port=await listen(reservation);await new Promise(r=>reservation.close(r));
  const proxy=createProxy({origin:`http://127.0.0.1:${port}`,frontend:`http://127.0.0.1:${nextPort}`,backend:`http://127.0.0.1:${backendPort}`});
  await new Promise(r=>proxy.listen(port,'127.0.0.1',r));
  try {
    assert.equal((await request(port,'/api/backend/account/me')).body,'next:/api/backend/account/me');
    assert.equal((await request(port,'/live/ws')).status,426);
    const wrong={Host:`localhost:${port}`,Accept:'text/html'};
    const navigation=await request(port,'/auth',wrong);
    assert.equal(navigation.status,307);assert.equal(navigation.headers.location,`http://127.0.0.1:${port}/auth`);
    assert.equal((await request(port,'/api/backend/login',wrong,'POST')).status,421);
    assert.equal((await request(port,'/auth',{Host:'evil.test',Accept:'text/html'})).status,421);
  } finally {proxy.shutdown();next.close();backend.close();}
});

test('WebSocket upgrades use fixed backend and strip browser credentials', async () => {
  let received;
  const backend=http.createServer();
  backend.on('upgrade',(req,socket) => {
    received=req.headers;
    socket.write('HTTP/1.1 101 Switching Protocols\r\nConnection: Upgrade\r\nUpgrade: websocket\r\nSec-WebSocket-Protocol: tradegraph.v1\r\n\r\n');
    socket.on('data',bytes=>socket.write(bytes));
  });
  const backendPort=await listen(backend);
  const reservation=http.createServer();const port=await listen(reservation);await new Promise(r=>reservation.close(r));
  const origin=`http://127.0.0.1:${port}`;
  const proxy=createProxy({origin,frontend:'http://127.0.0.1:1',backend:`http://127.0.0.1:${backendPort}`});
  await new Promise(r=>proxy.listen(port,'127.0.0.1',r));
  try {
    await new Promise((resolve,reject) => {
      const req=http.request(origin+'/live/ws',{headers:{Connection:'Upgrade',Upgrade:'websocket',Origin:origin,Cookie:'private-cookie',Authorization:'private-token','Sec-WebSocket-Protocol':'tradegraph.v1, ticket.private'}});
      req.on('upgrade',(res,socket)=>{
        assert.equal(res.statusCode,101);assert.equal(res.headers['sec-websocket-protocol'],'tradegraph.v1');
        assert.equal(received.cookie,undefined);assert.equal(received.authorization,undefined);
        socket.on('data',data=>{assert.equal(data.toString(),'ping');socket.destroy();resolve();});socket.write('ping');
      });req.on('error',reject);req.end();
    });
  } finally {proxy.shutdown();backend.close();}
});
