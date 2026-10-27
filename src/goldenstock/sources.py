"""Versioned public reference metadata. This registry never fetches remote URLs."""
from dataclasses import dataclass, asdict
from datetime import date
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from goldenstock.auth import authenticate

router = APIRouter(prefix='/api/v1')
REVIEWED = '2026-10-22'
REGISTRY_VERSION = '2026-10-22.1'
COMPANY_IDS = frozenset({'sber', 'tinkoff', 'jpm', 'hsbc', 'nu'})
HOSTS = frozenset({'www.sberbank.com', 'e-disclosure.ru', 't-technologies.ru',
                  'www.jpmorganchase.com', 'www.hsbc.com', 'nu.com', 'www.sec.gov'})


def validate_url(url):
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or parsed.hostname not in HOSTS or parsed.username
            or parsed.password or parsed.port is not None or parsed.fragment):
        raise ValueError('Only reviewed HTTPS source hosts are allowed')
    return url


@dataclass(frozen=True)
class Source:
    id: str
    company_id: str
    title: str
    url: str
    kind: str
    availability: str
    english: str
    evidence: str
    terms_status: str = 'not_verified'
    terms_url: str | None = None
    terms_note: str = 'Automated collection and reuse rights have not been established.'
    checked_on: str = REVIEWED

    def __post_init__(self):
        validate_url(self.url)
        if self.terms_url:
            validate_url(self.terms_url)
        if self.company_id not in COMPANY_IDS:
            raise ValueError('Unknown issuer ID')
        date.fromisoformat(self.checked_on)


SOURCES = (
    Source('sber-ir', 'sber', 'Sberbank investor relations',
           'https://www.sberbank.com/en/investor-relations/reports-and-publications/ifrs',
           'issuer_ir', 'unavailable_to_verifier', 'unverified',
           'Attempted IR path could not be opened by the verification tool. This does not prove a global outage or absence of English reports.'),
    Source('sber-disclosure', 'sber', 'Sberbank issuer disclosure',
           'https://e-disclosure.ru/portal/company.aspx?id=3043',
           'issuer_disclosure', 'verified', 'unverified',
           'Issuer identity: INN 7707083893. Russian disclosure index; English report coverage has not been established.'),
    Source('t-results', 'tinkoff', 'T-Technologies holding results',
           'https://t-technologies.ru/results/', 'issuer_ir', 'verified', 'unverified',
           'Russian results index includes 2023–2025 and 2026 reporting. Full English statements remain unverified. Holding, not T-Bank alone.'),
    Source('t-disclosure', 'tinkoff', 'T-Technologies holding disclosure',
           'https://e-disclosure.ru/portal/company.aspx?id=39055',
           'issuer_disclosure', 'verified', 'unverified',
           'Issuer identity: INN 2540283195, OGRN 1242500004383. Russian disclosure page.'),
    Source('jpm-annual', 'jpm', 'JPMorgan Chase & Co. annual reports',
           'https://www.jpmorganchase.com/ir/annual-report', 'issuer_ir', 'verified', 'confirmed',
           'English annual-report index includes FY2025 and archive links. Individual files and all requested periods have not been ingested.',
           'restricted', 'https://www.jpmorganchase.com/legal/terms-and-conditions',
           'Site terms restrict copying, storage and redistribution, subject to stated exceptions. No blanket reuse permission is assumed.'),
    Source('hsbc-group', 'hsbc', 'HSBC Holdings plc group reporting',
           'https://www.hsbc.com/investors/results-and-announcements/all-reporting/group',
           'issuer_ir', 'verified', 'confirmed',
           'English group archive, distinct from subsidiary reporting. FY2025 and interim 2026 listings observed; no files ingested.',
           'restricted', 'https://www.hsbc.com/terms-and-conditions',
           'Site terms limit use and distribution. Additional use requires permission; automated collection remains disabled.'),
    Source('hsbc-sec', 'hsbc', 'HSBC FY2025 SEC filing',
           'https://www.sec.gov/Archives/edgar/data/1089113/000108911326000010/hsbc-20251231.htm',
           'regulator', 'verified', 'confirmed', 'English FY2025 filing, issuer CIK 1089113. Other requested periods unverified.',
           'access_policy_reviewed', 'https://www.sec.gov/about/developer-resources',
           'SEC requires efficient identified access and an aggregate maximum of 10 requests/second. Access policy is not a blanket content reuse licence.'),
    Source('nu-results', 'nu', 'Nu Holdings results center',
           'https://nu.com/en/investors/financials/results-center/', 'issuer_ir', 'verified', 'confirmed',
           'Canonical English investor results center reached from the former investidores.nu site. Individual period files are not ingested.'),
    Source('nu-sec', 'nu', 'Nu Holdings FY2025 SEC statements',
           'https://www.sec.gov/Archives/edgar/data/1691493/000129281426000499/nufs4q25_6k.htm',
           'regulator', 'verified', 'confirmed', 'English FY2025 statements: Nu Holdings Ltd., CIK 1691493, NYSE NU; not a subsidiary bank.',
           'access_policy_reviewed', 'https://www.sec.gov/about/developer-resources',
           'SEC requires efficient identified access and an aggregate maximum of 10 requests/second. Reuse rights still need assessment.'),
)


def source_dict(source, today=None):
    age = ((today or date.today()) - date.fromisoformat(source.checked_on)).days
    return dict(asdict(source), review_freshness='current' if 0 <= age <= 90 else 'stale',
                auto_fetch_enabled=False, financial_data_status='not_ingested',
                coverage_status='incomplete', registry_version=REGISTRY_VERSION)


def registry(company_id=''):
    # Exact internal IDs prevent matching a holding to a similarly named bank.
    if company_id and company_id not in COMPANY_IDS:
        raise HTTPException(404, 'Company not found')
    return [source_dict(s) for s in SOURCES if not company_id or s.company_id == company_id]


@router.get('/sources')
def sources(request: Request, company_id: str = ''):
    authenticate(request)
    return registry(company_id)


@router.get('/sources/{source_id}')
def source(source_id: str, request: Request):
    authenticate(request)
    item = next((s for s in SOURCES if s.id == source_id), None)
    if item is None:
        raise HTTPException(404, 'Source not found')
    return source_dict(item)
