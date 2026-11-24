"""Context remains a cited suggestion, never a silently invented financial input."""
import hashlib
import json
import httpx
import pytest
from goldenstock.ai_context import validate_context, POLICY
from goldenstock.inference import (ContextProposal, ContextProposals, OllamaProvider,
    InferenceError, PROFILES, context_prompt, context_schema, inference_spec)
from goldenstock.config import Settings
from goldenstock.normalization import CURRENCIES


def proposal(**changes):
    return ContextProposal(**(dict(evidence_id='v:0',quote='Net profit 120',number_text='120',
        metric='profit',currency='USD',scale='millions',period='2025',
        perimeter='Consolidated group',definition='Net profit',context_ids=['ctx:0']) | changes))


PRIMARY='Net profit 120'
HEADER='Consolidated group. USD millions; year ended 2025.'


def test_explicit_header_and_verbatim_definition():
    validate_context(proposal(),PRIMARY,[HEADER])
    validate_context(proposal(currency=None,scale=None,period=None,perimeter=None,definition=None),PRIMARY,[])
    validate_context(proposal(currency='EUR',scale='thousands',period='2024'),
                     PRIMARY+' EUR thousands FY 2024 consolidated group',[HEADER])


@pytest.mark.parametrize('changes', [
    dict(currency='EUR'),dict(currency='ZZZ'),dict(scale='billions'),dict(scale='made-up'),
    dict(period='2026'),dict(period='FY2025'),dict(perimeter='Parent bank only'),
    dict(definition='Profit after tax and interest expenses'),dict(currency=''),dict(period=''),
])
def test_uncited_or_invented_context_rejected(changes):
    with pytest.raises(ValueError): validate_context(proposal(**changes),PRIMARY,[HEADER])


def test_uncited_header_cannot_supply_values_and_conflicts_cannot_be_hidden():
    with pytest.raises(ValueError): validate_context(proposal(),PRIMARY,[],[HEADER])
    for other in ('EUR millions; year ended 2025', 'USD billions; year ended 2025',
                  'USD millions; year ended 2024'):
        with pytest.raises(ValueError): validate_context(proposal(),PRIMARY,[HEADER],[HEADER,other])
    # Abstention is valid even when the neighbouring statements disagree.
    validate_context(proposal(currency=None,scale=None,period=None,perimeter=None),PRIMARY,
                     [HEADER],[HEADER,'EUR billions year ended 2024'])


def test_primary_context_cannot_be_overridden_by_a_neighbour():
    with pytest.raises(ValueError):
        validate_context(proposal(),PRIMARY+' EUR thousands FY 2024',[HEADER])


def test_singular_source_scale_preserved_without_weakening_magnitude_check():
    value=proposal(scale='million')
    validate_context(value,PRIMARY,[HEADER.replace('millions','million')])
    assert value.scale=='million'
    with pytest.raises(ValueError): validate_context(value,PRIMARY,[HEADER.replace('millions','billion')])
    with pytest.raises(ValueError): validate_context(value,PRIMARY,[],[HEADER])


def test_currency_does_not_attach_to_ratios_and_percent_is_not_a_money_scale():
    ratio=proposal(metric='roe',quote='ROE 12.5%',number_text='12.5%',currency=None,
                   scale='percent',definition='ROE')
    validate_context(ratio,'ROE 12.5%',[HEADER])
    for bad in (ratio.model_copy(update={'currency':'USD'}), ratio.model_copy(update={'scale':'millions'})):
        with pytest.raises(ValueError): validate_context(bad,'ROE 12.5%',[HEADER])
    with pytest.raises(ValueError): validate_context(proposal(scale='percent'),PRIMARY+' 12%',[HEADER])


def test_period_is_literal_and_cannot_choose_a_comparative_year():
    with pytest.raises(ValueError): validate_context(proposal(),PRIMARY,[HEADER+' Comparative 2024.'])
    with pytest.raises(ValueError): validate_context(proposal(period='2024'),PRIMARY+' FY2025',[HEADER+' 2024'])
    validate_context(proposal(period='year ended 2025'),PRIMARY,[HEADER])
    # Boundary matching does not turn 12025 into the year 2025.
    with pytest.raises(ValueError): validate_context(proposal(period='2025'),PRIMARY,[HEADER.replace('2025','12025')])


def test_context_schema_and_prompt_are_bounded_and_versioned():
    spec=inference_spec('context_proposals','qwen4')
    assert spec['context_validation']==POLICY
    assert spec['prompt_version']=='metric-proposal-context-v3-schema'
    assert spec['prompt_sha256']==hashlib.sha256(context_prompt().encode()).hexdigest()
    schema=context_schema()
    assert schema['$defs']['ContextProposal']['properties']['currency']['enum']==[*CURRENCIES,None]
    assert len(context_prompt()) < 4000
    assert 'Response JSON schema:' in context_prompt()
    assert 'context_validation' not in inference_spec('proposals','qwen4')
    assert 'context_validation' not in inference_spec('summary','qwen4')


def test_provider_verifies_cited_fields_and_receipt_matches_sent_prompt():
    sent=[]
    value=proposal()
    def handle(request):
        if request.url.path=='/api/tags':
            return httpx.Response(200,json={'models':[dict(name=p.model,digest=p.digest) for p in PROFILES.values()]})
        body=json.loads(request.content);sent.append(body)
        return httpx.Response(200,json={'message':{'content':json.dumps(dict(proposals=[value.model_dump()]))}})
    adapter=OllamaProvider(Settings(_env_file=None),httpx.MockTransport(handle))
    result=adapter.propose_context([dict(id='v:0',text=PRIMARY)],[dict(id='ctx:0',text=HEADER)])
    assert result['context_validation']==POLICY and result['status']=='unreviewed'
    assert result['prompt_sha256']==hashlib.sha256(sent[0]['messages'][0]['content'].encode()).hexdigest()
    # The static prompt never embeds document-specific token or citation IDs.
    assert 'v:0' not in sent[0]['messages'][0]['content']
    value=value.model_copy(update={'definition':'A generic invented financial explanation'})
    with pytest.raises(InferenceError,match='unsupported_context'):
        adapter.propose_context([dict(id='v:0',text=PRIMARY)],[dict(id='ctx:0',text=HEADER)])
