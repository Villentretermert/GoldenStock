"""Verify the offline GS-004 evidence inventory. This command never invokes inference."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

DATASETS = Path(__file__).resolve().parent / 'datasets'
MANIFEST = DATASETS / 'issuer-corpus-v0.1' / 'manifest.json'
SOURCE_HOSTS = {'hsbc': 'www.hsbc.com', 'jpm': 'www.jpmorganchase.com', 'nu': 'api.mziq.com'}
NU_DOWNLOAD_PREFIX = '/mzfilemanager/v2/d/59a081d2-0d63-4bb5-b786-4c07ae26bc74/'


def check_file(root, relative, digest, size=None):
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError(f'Missing or misplaced corpus file: {relative}')
    if size is not None and path.stat().st_size != size:
        raise ValueError(f'Original size mismatch: {relative}')
    with path.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != digest:
            raise ValueError(f'Checksum mismatch: {relative}')


def verify(manifest, root=None):
    public = manifest['schema']=='gs004-public-inventory-v1'
    if not public and manifest['schema']!='gs004-issuer-corpus-v1':
        raise ValueError('Unknown corpus schema')
    if public and (root is not None or manifest['reserved_per_issuer']!={c:2 for c in SOURCE_HOSTS}
                   or not re.fullmatch('[0-9a-f]{64}',manifest['private_manifest_sha256'])):
        raise ValueError('Invalid public inventory or commitment')
    root = Path(root).resolve() if root is not None else None
    # These families and source hashes were already used in development before v0.1.
    known = json.loads((DATASETS/'annual-reports-development-v0.1/manifest.json').read_bytes())['sources']
    section = json.loads((DATASETS/'jpm-2025-development-v0.1/manifest.json').read_bytes())['source']
    known_families = {entry['document_family'] for entry in [*known, section]}
    known_hashes = {entry['sha256'] for entry in [*known, section]}
    families, ids, hashes, urls = {}, set(), set(), set()
    splits, formats = Counter(), Counter()
    for doc in manifest['documents']:
        company, split, kind = doc['company'], doc['split'], doc['kind']
        period = re.fullmatch(r'(20[0-9]{2})-Q([1-4])', doc['period'])
        if company not in SOURCE_HOSTS or not period or not re.fullmatch('[a-z]+', kind):
            raise ValueError('Invalid company, reporting period or document kind')
        year, quarter = period.groups()
        key = f'{company}-{year}q{quarter}-{kind}'
        family = f'{company}-{year}-annual-report' if quarter=='4' else f'{company}-{year}-q{quarter}-results'
        if split not in {'development', 'holdout-reserve'} or doc['id']!=key or doc['family']!=family:
            raise ValueError(f'Invalid identity or split: {key}')
        digest = doc['sha256']
        url = urlsplit(doc['source_url'])
        if (url.scheme!='https' or url.netloc!=SOURCE_HOSTS[company] or
                (company=='nu' and not url.path.startswith(NU_DOWNLOAD_PREFIX))):
            raise ValueError(f'Unexpected original URL: {key}')
        if public and split!='development':
            raise ValueError('Reserved sources must stay in the local manifest')
        if key in ids or digest in hashes or doc['source_url'] in urls:
            raise ValueError(f'Duplicate document: {key}')
        if families.setdefault(family,split)!=split:
            raise ValueError(f'Report family crosses splits: {family}')
        if split=='holdout-reserve' and (family in known_families or digest in known_hashes or 'extraction' in doc):
            raise ValueError(f'Previously exposed or extracted reserved document: {key}')
        ext = doc['format']
        relative = f'{split}/{key}.{ext}'
        if (ext not in {'pdf','xlsx','pptx'} or doc['path']!=relative or doc['language']!='en' or
                not re.fullmatch('[0-9a-f]{64}',digest) or not 0<doc['bytes']<=50*1024**2):
            raise ValueError(f'Invalid file metadata: {key}')
        if root is not None:
            check_file(root, relative, digest, doc['bytes'])
        if split=='development':
            receipt = doc['extraction']
            if receipt['items']<=0 or not re.fullmatch('[0-9a-f]{64}',receipt['extraction_sha256']):
                raise ValueError(f'Invalid extraction receipt: {key}')
            if root is not None:
                check_file(root, f'parsed/{key}.json', receipt['extraction_sha256'])
        ids.add(key)
        hashes.add(digest)
        urls.add(doc['source_url'])
        splits[company,split]+=1
        formats[ext]+=1
    reserve_per_issuer=0 if public else 2
    if any(splits[c,'development']!=8 or splits[c,'holdout-reserve']!=reserve_per_issuer for c in SOURCE_HOSTS):
        raise ValueError('Unexpected document counts for the inventory')
    if not public and len({f for f,s in families.items() if s=='holdout-reserve'})!=6:
        raise ValueError('Expected six independent reserved reporting families')
    if root is not None:
        # Extra extracted files in this directory may expose the reserved set.
        expected={f"{d['id']}.json" for d in manifest['documents'] if d['split']=='development'}
        if {p.name for p in (root/'parsed').iterdir()}!=expected:
            raise ValueError('Unexpected or missing working extraction')
        for split in ('development','holdout-reserve'):
            expected={Path(d['path']).name for d in manifest['documents'] if d['split']==split}
            if {p.name for p in (root/split).iterdir()}!=expected:
                raise ValueError(f'Unexpected or missing original in {split}')
    return dict(originals=len(ids), development=24, reserved_documents_listed=reserve_per_issuer*3, families=len(families),
                formats=dict(formats), local_hashes_checked=root is not None)


def verify_local(public, root):
    verify(public)
    root=Path(root).resolve()
    check_file(root,'manifest.json',public['private_manifest_sha256'])
    local=json.loads((root/'manifest.json').read_bytes())
    if [d for d in local['documents'] if d['split']=='development']!=public['documents']:
        raise ValueError('Public development entries differ from frozen private inventory')
    return verify(local,root)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, help='Also verify original bytes and working extraction hashes in this directory')
    args = parser.parse_args()
    try:
        public = json.loads(MANIFEST.read_bytes())
        summary = verify_local(public,args.root) if args.root else verify(public)
    except (KeyError, TypeError, OSError, ValueError) as exc:
        parser.exit(1, f'Corpus verification failed: {exc}\n')
    print(json.dumps(summary, indent=2))


if __name__=='__main__':
    main()
