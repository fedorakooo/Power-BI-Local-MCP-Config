"""Vendor the exact Microsoft PBIR schemas and their dependencies for offline validation."""
import hashlib
import json
from pathlib import Path
from urllib.parse import urldefrag, urljoin, urlsplit
import httpx

ROOT = Path(__file__).resolve().parents[1] / 'schemas'
BASE = 'https://developer.microsoft.com/json-schemas/fabric/item/report/definition/'
pending = [BASE + x + '/schema.json' for x in ['page/2.1.0', 'pagesMetadata/1.1.0', 'visualContainer/2.12.0']]
documents = {}


def refs(node):
    if isinstance(node, dict):
        for k, v in node.items():
            if k == '$ref':
                yield v
            else:
                yield from refs(v)
    elif isinstance(node, list):
        for v in node:
            yield from refs(v)


with httpx.Client(timeout=30, follow_redirects=True) as client:
    while pending:
        url = pending.pop()
        if url in documents:
            continue
        if urlsplit(url).netloc != 'developer.microsoft.com' or '/json-schemas/' not in url:
            raise RuntimeError('Unexpected schema dependency: ' + url)
        source_url = 'https://raw.githubusercontent.com/microsoft/json-schemas/main/' + urlsplit(url).path.removeprefix('/json-schemas/')
        response = client.get(source_url)
        response.raise_for_status()
        document = response.json()
        documents[url] = document
        for ref in refs(document):
            if not ref.startswith('#'):
                dependency = urldefrag(urljoin(url, ref))[0]
                if dependency not in documents:
                    pending.append(dependency)
ROOT.mkdir(exist_ok=True)
manifest = {}
for url, document in sorted(documents.items()):
    filename = hashlib.sha256(url.encode()).hexdigest()[:16] + '.json'
    payload = json.dumps(document, indent=2).encode()
    (ROOT / filename).write_bytes(payload)
    manifest[url] = {'file': filename, 'sha256': hashlib.sha256(payload).hexdigest()}
(ROOT / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
print('Vendored ' + str(len(documents)) + ' Microsoft schemas with SHA256 manifest')
