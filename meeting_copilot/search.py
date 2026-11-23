"""Optional Bocha adapter, following Agent2's normalized result shape."""
import hashlib
import ipaddress
import json
import os
import socket
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit, urljoin
import httpx


class TextParser(HTMLParser):
    def __init__(self):super().__init__();self.hidden=0;self.parts=[]
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style'):self.hidden+=1
    def handle_endtag(self,tag):
        if tag in ('script','style'):self.hidden=max(0,self.hidden-1)
    def handle_data(self,data):
        if not self.hidden and data.strip():self.parts.append(data.strip())


def public_url(url):
    parsed=urlsplit(url)
    if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('只读取公网 HTTP(S) 页面')
    addresses=socket.getaddrinfo(parsed.hostname,parsed.port or (443 if parsed.scheme=='https' else 80))
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError('不读取本机或私网地址')
    return url


class SearchProvider:
    def __init__(self,key_file=None):
        self.key=os.getenv('BOCHA_API_KEY','')
        if not self.key and key_file:
            self.key=next((l.strip().split('=',1)[-1].strip() for l in Path(key_file).read_text(encoding='utf-8-sig').splitlines() if l.strip()),'')
        if not self.key:raise ValueError('未配置公开资料搜索')

    def search(self,query,folder):
        with httpx.Client(timeout=30) as c:
            r=c.post('https://api.bochaai.com/v1/web-search',headers={'Authorization':'Bearer '+self.key},
                     json={'query':query,'count':4,'summary':True})
            if not r.is_success:raise RuntimeError(f'公开搜索失败 HTTP {r.status_code}')
            raw=r.json()
        pages=(((raw.get('data') or {}).get('webPages') or {}).get('value')) or []
        items=[{'title':p.get('name',''),'url':p.get('url',''),'text':str(p.get('summary') or p.get('snippet') or '')[:1600]} for p in pages]
        Path(folder).mkdir(parents=True,exist_ok=True)
        (Path(folder)/'search-results.json').write_text(json.dumps({'query':query,'items':items},ensure_ascii=False,indent=2),encoding='utf-8')
        return items

    def read(self,item,folder):
        url=item['url'];text=item['text'];kind='external_summary';error=None
        try:
            with httpx.Client(timeout=15,follow_redirects=False) as c:
                for _ in range(4):
                    public_url(url)
                    with c.stream('GET',url,headers={'User-Agent':'MeetingWatcher research/1.0'}) as r:
                        if r.is_redirect:
                            url=urljoin(url,r.headers['location']);continue
                        r.raise_for_status()
                        if not any(t in r.headers.get('content-type','') for t in ('text/html','text/plain')):
                            raise ValueError('当前仅读取网页文字，其他格式保留搜索摘要')
                        chunks=[];size=0
                        for chunk in r.iter_bytes():
                            size+=len(chunk)
                            if size>1_000_000:raise ValueError('网页超过 1 MB')
                            chunks.append(chunk)
                        parser=TextParser();parser.feed(b''.join(chunks).decode(r.encoding or 'utf-8',errors='replace'))
                        text='\n'.join(parser.parts)[:8000];kind='external_document';break
                else:raise ValueError('页面重定向过多')
        except (httpx.HTTPError,OSError,ValueError) as exc:
            error=type(exc).__name__
        ident='web:'+hashlib.sha256(url.encode()).hexdigest()[:16]
        evidence={'id':ident,'meeting_id':'外部资料','speaker':item['title'],'quote':text,'start_ms':None,'end_ms':None,
                  'source_start_ms':0,'source_end_ms':0,'provenance':kind,'url':url,
                  'retrieved_at':datetime.now(timezone.utc).isoformat(),'read_error':error}
        (Path(folder)/(ident.replace(':','-')+'.json')).write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
        return evidence
