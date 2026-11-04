import json
import pytest
from evaluation.corpus import MANIFEST, check_file, verify, verify_local


def test_published_inventory_contains_only_working_sources():
    summary=verify(json.loads(MANIFEST.read_bytes()))
    assert (summary['originals'],summary['development'],summary['reserved_documents_listed'])==(24,24,0)


def fixture_inventory():
    # Use fictional reserved periods. Actual reserved identities stay in the local bundle.
    import hashlib
    data=json.loads(MANIFEST.read_bytes())
    data['schema']='gs004-issuer-corpus-v1'
    for company in ('jpm','hsbc','nu'):
        template=next(d for d in data['documents'] if d['company']==company)
        for quarter in (1,2):
            key=f'{company}-2099q{quarter}-release'
            source=dict(template,id=key,kind='release',period=f'2099-Q{quarter}',family=f'{company}-2099-q{quarter}-results',
                        split='holdout-reserve',path=f'holdout-reserve/{key}.pdf',format='pdf',
                        sha256=hashlib.sha256(key.encode()).hexdigest(),source_url=template['source_url']+'#'+key)
            source.pop('extraction')
            data['documents'].append(source)
    return data


@pytest.mark.parametrize('problem',['duplicate','family','exposure','path'])
def test_corpus_rejects_contamination_or_misplaced_files(problem):
    data=fixture_inventory()
    documents=data['documents']
    target=next(d for d in documents if d['split']=='holdout-reserve')
    if problem=='duplicate':
        target['sha256']=next(d['sha256'] for d in documents if d['split']=='development')
    elif problem=='family':
        # A different format from the same reporting event remains in the same family.
        target=dict(target,kind='alternate',split='development',extraction=documents[0]['extraction'])
        target['id']=target['id'].rsplit('-',1)[0]+'-alternate'
        target['path']='development/'+target['id']+'.'+target['format']
        target['source_url']+='?alternate=1'
        target['sha256']='1'*64
        documents.append(target)
    elif problem=='exposure':
        target['extraction']={}
    else:
        target['path']='../outside.pdf'
    with pytest.raises(ValueError):
        verify(data)


def test_local_bytes_must_match_digest(tmp_path):
    path=tmp_path/'original.pdf'
    path.write_bytes(b'bad')
    with pytest.raises(ValueError,match='Checksum mismatch'):
        check_file(tmp_path,path.name,'0'*64,3)


def test_local_manifest_is_pinned_to_published_commitment(tmp_path):
    public=json.loads(MANIFEST.read_bytes())
    sample=fixture_inventory()
    assert verify(sample)['reserved_documents_listed']==6
    (tmp_path/'manifest.json').write_text(json.dumps(sample),encoding='utf-8')
    with pytest.raises(ValueError,match='Checksum mismatch'):
        verify_local(public,tmp_path)
