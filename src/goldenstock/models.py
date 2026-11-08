"""Infrastructure and tenant-owned workspace entities; no financial facts yet."""
import time
import uuid
from sqlalchemy import Float, String, Boolean, Integer, ForeignKey, UniqueConstraint, Text, LargeBinary
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeats"
    worker_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    last_seen: Mapped[float] = mapped_column(Float, nullable=False)


def new_id():
    return uuid.uuid4().hex


class Organization(Base):
    __tablename__ = 'organizations'
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120))


class User(Base):
    __tablename__ = 'users'
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    org_id: Mapped[str] = mapped_column(ForeignKey('organizations.id'), index=True)
    login: Mapped[str] = mapped_column(String(120), unique=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    account_admin: Mapped[bool] = mapped_column(Boolean, default=False)


class LoginSession(Base):
    __tablename__ = 'login_sessions'
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    csrf: Mapped[str] = mapped_column(String(64))
    expires: Mapped[float] = mapped_column(Float)


class AuditEvent(Base):
    __tablename__ = 'audit_events'
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    org_id: Mapped[str] = mapped_column(String(32), index=True)
    actor_id: Mapped[str] = mapped_column(String(32))
    action: Mapped[str] = mapped_column(String(80))
    target: Mapped[str] = mapped_column(String(32))
    detail: Mapped[str] = mapped_column(Text, default='')
    created: Mapped[float] = mapped_column(Float, default=time.time)


class WorkspaceModel(Base):
    """Access-controlled model draft metadata; no financial calculations yet."""
    __tablename__ = 'workspace_models'
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    org_id: Mapped[str] = mapped_column(ForeignKey('organizations.id'), index=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    title: Mapped[str] = mapped_column(String(160))
    shared: Mapped[bool] = mapped_column(Boolean, default=False)
    revision: Mapped[int] = mapped_column(Integer, default=1)


class Company(Base):
    __tablename__ = 'companies'
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    identifier: Mapped[str] = mapped_column(String(120))
    candidate: Mapped[bool] = mapped_column(Boolean)
    source_url: Mapped[str] = mapped_column(String(300), default='')
    source_checked: Mapped[float | None] = mapped_column(Float, nullable=True)


class Favorite(Base):
    __tablename__ = 'favorites'
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), primary_key=True)
    company_id: Mapped[str] = mapped_column(ForeignKey('companies.id'), primary_key=True)


class Document(Base):
    __tablename__ = 'documents'
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    org_id: Mapped[str] = mapped_column(ForeignKey('organizations.id'), index=True)
    owner_id: Mapped[str] = mapped_column(ForeignKey('users.id'))
    company_id: Mapped[str] = mapped_column(ForeignKey('companies.id'))
    shared: Mapped[bool] = mapped_column(Boolean, default=False)
    filename: Mapped[str] = mapped_column(String(200))
    revision: Mapped[int] = mapped_column(Integer, default=1)


class DocumentVersion(Base):
    __tablename__ = 'document_versions'
    __table_args__ = (UniqueConstraint('document_id','number'), UniqueConstraint('owner_id','idem_key'))
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    document_id: Mapped[str] = mapped_column(ForeignKey('documents.id'), index=True)
    org_id: Mapped[str] = mapped_column(String(32))
    owner_id: Mapped[str] = mapped_column(String(32))
    number: Mapped[int] = mapped_column(Integer)
    filename: Mapped[str] = mapped_column(String(200))
    sha256: Mapped[str] = mapped_column(String(64))
    size: Mapped[int] = mapped_column(Integer)
    blob_key: Mapped[str] = mapped_column(String(200))
    idem_key: Mapped[str] = mapped_column(String(100))
    request_hash: Mapped[str] = mapped_column(String(64))
    created: Mapped[float] = mapped_column(Float, default=time.time)


class Job(Base):
    __tablename__ = 'jobs'
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    org_id: Mapped[str] = mapped_column(String(32), index=True)
    actor_id: Mapped[str] = mapped_column(String(32))
    version_id: Mapped[str] = mapped_column(ForeignKey('document_versions.id'), unique=True)
    kind: Mapped[str] = mapped_column(String(24), default='verify_original')
    state: Mapped[str] = mapped_column(String(24), default='queued')
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    lease_until: Mapped[float] = mapped_column(Float, default=0)
    lease_token: Mapped[str] = mapped_column(String(32), default='')
    available_at: Mapped[float] = mapped_column(Float, default=0)
    error_code: Mapped[str] = mapped_column(String(40), default='')
    created: Mapped[float] = mapped_column(Float, default=time.time)


class JobEvent(Base):
    __tablename__ = 'job_events'
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(ForeignKey('jobs.id'), index=True)
    state: Mapped[str] = mapped_column(String(24))
    attempt: Mapped[int] = mapped_column(Integer)
    created: Mapped[float] = mapped_column(Float, default=time.time)


class Extraction(Base):
    __tablename__ = 'extractions'
    version_id: Mapped[str] = mapped_column(ForeignKey('document_versions.id'), primary_key=True)
    parser_version: Mapped[str] = mapped_column(String(40))
    source_sha256: Mapped[str] = mapped_column(String(64))
    payload: Mapped[str] = mapped_column(Text)
    created: Mapped[float] = mapped_column(Float, default=time.time)


class ExtractionCheckpoint(Base):
    """Incomplete raw evidence is never exposed as an Extraction."""
    __tablename__ = 'extraction_checkpoints'
    version_id: Mapped[str] = mapped_column(ForeignKey('document_versions.id'), primary_key=True)
    parser_version: Mapped[str] = mapped_column(String(40))
    source_sha256: Mapped[str] = mapped_column(String(64))
    completed_pages: Mapped[int] = mapped_column(Integer)
    total_pages: Mapped[int] = mapped_column(Integer)
    payload: Mapped[str] = mapped_column(Text)
    payload_sha256: Mapped[str] = mapped_column(String(64))


class Fact(Base):
    __tablename__='facts'
    __table_args__=(UniqueConstraint('owner_id','fingerprint'),)
    id: Mapped[str]=mapped_column(String(32),primary_key=True,default=new_id)
    org_id: Mapped[str]=mapped_column(ForeignKey('organizations.id'))
    owner_id: Mapped[str]=mapped_column(ForeignKey('users.id'))
    company_id: Mapped[str]=mapped_column(ForeignKey('companies.id'))
    version_id: Mapped[str]=mapped_column(ForeignKey('document_versions.id'))
    fingerprint: Mapped[str]=mapped_column(String(64))
    supersedes: Mapped[str | None]=mapped_column(ForeignKey('facts.id'),unique=True,nullable=True)
    payload: Mapped[str]=mapped_column(Text)
    created: Mapped[float]=mapped_column(Float,default=time.time)


class FactReview(Base):
    __tablename__='fact_reviews'
    __table_args__=(UniqueConstraint('fact_id','revision'),)
    id: Mapped[str]=mapped_column(String(32),primary_key=True,default=new_id)
    fact_id: Mapped[str]=mapped_column(ForeignKey('facts.id'))
    revision: Mapped[int]=mapped_column(Integer)
    actor_id: Mapped[str]=mapped_column(String(32))
    decision: Mapped[str]=mapped_column(String(20))
    note: Mapped[str]=mapped_column(Text)
    created: Mapped[float]=mapped_column(Float,default=time.time)


class InputSnapshot(Base):
    __tablename__='input_snapshots'
    __table_args__=(UniqueConstraint('owner_id','company_id','state_hash'),)
    id: Mapped[str]=mapped_column(String(32),primary_key=True,default=new_id)
    org_id: Mapped[str]=mapped_column(String(32))
    owner_id: Mapped[str]=mapped_column(String(32))
    company_id: Mapped[str]=mapped_column(ForeignKey('companies.id'))
    title: Mapped[str]=mapped_column(String(160))
    state_hash: Mapped[str]=mapped_column(String(64))
    payload: Mapped[str]=mapped_column(Text)
    created: Mapped[float]=mapped_column(Float,default=time.time)


class AIRun(Base):
    __tablename__='ai_runs'
    __table_args__=(UniqueConstraint('owner_id','fingerprint'),)
    id: Mapped[str]=mapped_column(String(32),primary_key=True,default=new_id)
    org_id: Mapped[str]=mapped_column(String(32))
    owner_id: Mapped[str]=mapped_column(String(32))
    company_id: Mapped[str]=mapped_column(String(32))
    kind: Mapped[str]=mapped_column(String(24))
    profile: Mapped[str]=mapped_column(String(32))
    fingerprint: Mapped[str]=mapped_column(String(64))
    input: Mapped[str]=mapped_column(Text)
    output: Mapped[str]=mapped_column(Text,default='{}')
    state: Mapped[str]=mapped_column(String(24),default='queued')
    error: Mapped[str]=mapped_column(String(80),default='')
    attempts: Mapped[int]=mapped_column(Integer,default=0)
    device: Mapped[str]=mapped_column(String(8),default='gpu',server_default='gpu')
    lease_until: Mapped[float]=mapped_column(Float,default=0)
    lease_token: Mapped[str]=mapped_column(String(32),default='')
    created: Mapped[float]=mapped_column(Float,default=time.time)


class AIExecution(Base):
    """One receipt per attempt, retained across resource decisions and retries."""
    __tablename__='ai_executions'
    run_id: Mapped[str]=mapped_column(ForeignKey('ai_runs.id'),primary_key=True)
    attempt: Mapped[int]=mapped_column(Integer,primary_key=True)
    state: Mapped[str]=mapped_column(String(24))
    started: Mapped[float]=mapped_column(Float)
    finished: Mapped[float|None]=mapped_column(Float,nullable=True)
    receipt: Mapped[str]=mapped_column(Text)


class AIProposalBatch(Base):
    """Private immutable manifest grouping bounded AIRun inputs."""
    __tablename__='ai_proposal_batches'
    __table_args__=(UniqueConstraint('owner_id','fingerprint'),)
    id: Mapped[str]=mapped_column(String(32),primary_key=True,default=new_id)
    org_id: Mapped[str]=mapped_column(ForeignKey('organizations.id'),index=True)
    owner_id: Mapped[str]=mapped_column(ForeignKey('users.id'))
    company_id: Mapped[str]=mapped_column(ForeignKey('companies.id'))
    version_id: Mapped[str]=mapped_column(ForeignKey('document_versions.id'))
    fingerprint: Mapped[str]=mapped_column(String(64))
    manifest: Mapped[str]=mapped_column(Text)
    manifest_hash: Mapped[str]=mapped_column(String(64))
    created: Mapped[float]=mapped_column(Float,default=time.time)


class LabDataset(Base):
    """Immutable reference labels and inputs; a revision creates a new row."""
    __tablename__='lab_datasets'
    __table_args__=(UniqueConstraint('owner_id','fingerprint'),)
    id: Mapped[str]=mapped_column(String(32),primary_key=True,default=new_id)
    org_id: Mapped[str]=mapped_column(ForeignKey('organizations.id'),index=True)
    owner_id: Mapped[str]=mapped_column(ForeignKey('users.id'))
    parent_id: Mapped[str | None]=mapped_column(ForeignKey('lab_datasets.id'),nullable=True)
    revision: Mapped[int]=mapped_column(Integer,default=1)
    title: Mapped[str]=mapped_column(String(160))
    split: Mapped[str]=mapped_column(String(16))
    kind: Mapped[str]=mapped_column(String(16))
    fingerprint: Mapped[str]=mapped_column(String(64))
    payload: Mapped[str]=mapped_column(Text)
    created: Mapped[float]=mapped_column(Float,default=time.time)


class LabExchange(Base):
    """An unlabelled workbook draft never counts as an accepted reference."""
    __tablename__='lab_exchanges'
    __table_args__=(UniqueConstraint('owner_id','fingerprint'),)
    id: Mapped[str]=mapped_column(String(32),primary_key=True,default=new_id)
    org_id: Mapped[str]=mapped_column(ForeignKey('organizations.id'),index=True)
    owner_id: Mapped[str]=mapped_column(ForeignKey('users.id'))
    fingerprint: Mapped[str]=mapped_column(String(64))
    payload: Mapped[str]=mapped_column(Text)
    created: Mapped[float]=mapped_column(Float,default=time.time)


class LabImport(Base):
    __tablename__='lab_imports'
    __table_args__=(UniqueConstraint('exchange_id','sha256'),)
    id: Mapped[str]=mapped_column(String(32),primary_key=True,default=new_id)
    org_id: Mapped[str]=mapped_column(ForeignKey('organizations.id'),index=True)
    owner_id: Mapped[str]=mapped_column(ForeignKey('users.id'))
    exchange_id: Mapped[str]=mapped_column(ForeignKey('lab_exchanges.id'))
    sha256: Mapped[str]=mapped_column(String(64))
    original: Mapped[bytes]=mapped_column(LargeBinary)
    candidate: Mapped[str]=mapped_column(Text)
    candidate_hash: Mapped[str]=mapped_column(String(64))
    dataset_id: Mapped[str|None]=mapped_column(ForeignKey('lab_datasets.id'),nullable=True)
    confirmation_note: Mapped[str]=mapped_column(Text,default='')
    confirmed_at: Mapped[float|None]=mapped_column(Float,nullable=True)
    created: Mapped[float]=mapped_column(Float,default=time.time)


class LabSourceSplit(Base):
    __tablename__='lab_source_splits'
    owner_id: Mapped[str]=mapped_column(ForeignKey('users.id'),primary_key=True)
    source_hash: Mapped[str]=mapped_column(String(64),primary_key=True)
    split: Mapped[str]=mapped_column(String(16))


class LabExperiment(Base):
    __tablename__='lab_experiments'
    __table_args__=(UniqueConstraint('owner_id','fingerprint'),)
    id: Mapped[str]=mapped_column(String(32),primary_key=True,default=new_id)
    org_id: Mapped[str]=mapped_column(ForeignKey('organizations.id'),index=True)
    owner_id: Mapped[str]=mapped_column(ForeignKey('users.id'))
    dataset_id: Mapped[str]=mapped_column(ForeignKey('lab_datasets.id'))
    fingerprint: Mapped[str]=mapped_column(String(64))
    manifest: Mapped[str]=mapped_column(Text)
    manifest_hash: Mapped[str]=mapped_column(String(64))
    revealed: Mapped[bool]=mapped_column(Boolean,default=False)
    created: Mapped[float]=mapped_column(Float,default=time.time)


class LabAnnotation(Base):
    __tablename__='lab_annotations'
    __table_args__=(UniqueConstraint('run_id','revision'),)
    id: Mapped[str]=mapped_column(String(32),primary_key=True,default=new_id)
    experiment_id: Mapped[str]=mapped_column(ForeignKey('lab_experiments.id'))
    run_id: Mapped[str]=mapped_column(ForeignKey('ai_runs.id'))
    actor_id: Mapped[str]=mapped_column(ForeignKey('users.id'))
    revision: Mapped[int]=mapped_column(Integer)
    verdict: Mapped[str]=mapped_column(String(16))
    reason: Mapped[str]=mapped_column(String(1000))
    output_hash: Mapped[str]=mapped_column(String(64))
    created: Mapped[float]=mapped_column(Float,default=time.time)


class PublicSnapshot(Base):
    __tablename__='public_snapshots'
    __table_args__=(UniqueConstraint('company_id','sha256'),)
    id: Mapped[str]=mapped_column(String(32),primary_key=True,default=new_id)
    company_id: Mapped[str]=mapped_column(String(32))
    sha256: Mapped[str]=mapped_column(String(64))
    url: Mapped[str]=mapped_column(Text)
    payload: Mapped[str]=mapped_column(Text)
    created: Mapped[float]=mapped_column(Float,default=time.time)
    checked: Mapped[float]=mapped_column(Float,default=time.time)


class MonitorSource(Base):
    __tablename__='monitor_sources'
    id: Mapped[str]=mapped_column(String(40),primary_key=True)
    company_id: Mapped[str]=mapped_column(ForeignKey('companies.id'))
    kind: Mapped[str]=mapped_column(String(16))
    next_check: Mapped[float]=mapped_column(Float,default=0)
    last_attempt: Mapped[float | None]=mapped_column(Float,nullable=True)
    last_success: Mapped[float | None]=mapped_column(Float,nullable=True)
    error: Mapped[str]=mapped_column(String(80),default='')
    failures: Mapped[int]=mapped_column(Integer,default=0)
    snapshot_id: Mapped[str | None]=mapped_column(String(32),nullable=True)


class MonitorSnapshot(Base):
    __tablename__='monitor_snapshots'
    __table_args__=(UniqueConstraint('source_id','sha256'),)
    id: Mapped[str]=mapped_column(String(32),primary_key=True,default=new_id)
    source_id: Mapped[str]=mapped_column(ForeignKey('monitor_sources.id'))
    sha256: Mapped[str]=mapped_column(String(64))
    url: Mapped[str]=mapped_column(Text)
    payload: Mapped[str]=mapped_column(Text)
    created: Mapped[float]=mapped_column(Float,default=time.time)


class MonitorObservation(Base):
    __tablename__='monitor_observations'
    source_id: Mapped[str]=mapped_column(ForeignKey('monitor_sources.id'),primary_key=True)
    item_key: Mapped[str]=mapped_column(String(64),primary_key=True)
    payload: Mapped[str]=mapped_column(Text)
    snapshot_id: Mapped[str]=mapped_column(ForeignKey('monitor_snapshots.id'))
    history_id: Mapped[str | None]=mapped_column(String(32),nullable=True)


class MonitorFactVersion(Base):
    __tablename__='monitor_fact_versions'
    __table_args__=(UniqueConstraint('source_id','item_key','revision'),UniqueConstraint('previous_id'))
    id: Mapped[str]=mapped_column(String(32),primary_key=True,default=new_id)
    source_id: Mapped[str]=mapped_column(ForeignKey('monitor_sources.id'),index=True)
    item_key: Mapped[str]=mapped_column(String(64))
    revision: Mapped[int]=mapped_column(Integer)
    previous_id: Mapped[str | None]=mapped_column(ForeignKey('monitor_fact_versions.id'),nullable=True)
    snapshot_id: Mapped[str]=mapped_column(ForeignKey('monitor_snapshots.id'))
    reason: Mapped[str]=mapped_column(String(32))
    payload: Mapped[str]=mapped_column(Text)
    payload_sha256: Mapped[str]=mapped_column(String(64))
    created: Mapped[float]=mapped_column(Float,default=time.time)


class MonitorEvent(Base):
    __tablename__='monitor_events'
    __table_args__=(UniqueConstraint('source_id','fingerprint'),)
    id: Mapped[str]=mapped_column(String(32),primary_key=True,default=new_id)
    source_id: Mapped[str]=mapped_column(ForeignKey('monitor_sources.id'))
    fingerprint: Mapped[str]=mapped_column(String(64))
    kind: Mapped[str]=mapped_column(String(32))
    payload: Mapped[str]=mapped_column(Text)
    created: Mapped[float]=mapped_column(Float,default=time.time)


class SiteNotification(Base):
    __tablename__='site_notifications'
    __table_args__=(UniqueConstraint('owner_id','event_id'),)
    id: Mapped[str]=mapped_column(String(32),primary_key=True,default=new_id)
    org_id: Mapped[str]=mapped_column(ForeignKey('organizations.id'),index=True)
    owner_id: Mapped[str]=mapped_column(ForeignKey('users.id'))
    event_id: Mapped[str]=mapped_column(ForeignKey('monitor_events.id'))
    read_at: Mapped[float | None]=mapped_column(Float,nullable=True)


class ModelTemplate(Base):
    __tablename__='model_templates'
    id: Mapped[str]=mapped_column(String(32),primary_key=True,default=new_id)
    org_id: Mapped[str]=mapped_column(ForeignKey('organizations.id'),index=True)
    owner_id: Mapped[str]=mapped_column(ForeignKey('users.id'))
    title: Mapped[str]=mapped_column(String(160))
    shared: Mapped[bool]=mapped_column(Boolean,default=False)
    revision: Mapped[int]=mapped_column(Integer,default=1)


class TemplateVersion(Base):
    __tablename__='template_versions'
    __table_args__=(UniqueConstraint('template_id','number'),UniqueConstraint('owner_id','idem_key'))
    id: Mapped[str]=mapped_column(String(32),primary_key=True,default=new_id)
    template_id: Mapped[str]=mapped_column(ForeignKey('model_templates.id'),index=True)
    owner_id: Mapped[str]=mapped_column(String(32))
    number: Mapped[int]=mapped_column(Integer)
    idem_key: Mapped[str]=mapped_column(String(100))
    request_hash: Mapped[str]=mapped_column(String(64))
    sha256: Mapped[str]=mapped_column(String(64))
    clean_sha256: Mapped[str]=mapped_column(String(64))
    blob_key: Mapped[str]=mapped_column(String(200))
    clean_key: Mapped[str]=mapped_column(String(200))
    contract: Mapped[str]=mapped_column(Text)
    created: Mapped[float]=mapped_column(Float,default=time.time)


class CalculationRun(Base):
    __tablename__='calculation_runs'
    __table_args__=(UniqueConstraint('owner_id','idem_key'),)
    id: Mapped[str]=mapped_column(String(32),primary_key=True,default=new_id)
    org_id: Mapped[str]=mapped_column(ForeignKey('organizations.id'),index=True)
    owner_id: Mapped[str]=mapped_column(ForeignKey('users.id'))
    company_id: Mapped[str]=mapped_column(ForeignKey('companies.id'))
    version_id: Mapped[str]=mapped_column(ForeignKey('template_versions.id'))
    title: Mapped[str]=mapped_column(String(160))
    engine: Mapped[str]=mapped_column(String(32))
    idem_key: Mapped[str]=mapped_column(String(100))
    request_hash: Mapped[str]=mapped_column(String(64))
    input_hash: Mapped[str]=mapped_column(String(64))
    result_hash: Mapped[str]=mapped_column(String(64))
    input: Mapped[str]=mapped_column(Text)
    output: Mapped[str]=mapped_column(Text)
    state: Mapped[str]=mapped_column(String(40))
    created: Mapped[float]=mapped_column(Float,default=time.time)


class ValuationRun(Base):
    __tablename__='valuation_runs'
    __table_args__=(UniqueConstraint('owner_id','idem_key'),)
    id: Mapped[str]=mapped_column(String(32),primary_key=True,default=new_id)
    org_id: Mapped[str]=mapped_column(ForeignKey('organizations.id'),index=True)
    owner_id: Mapped[str]=mapped_column(ForeignKey('users.id'))
    company_id: Mapped[str]=mapped_column(ForeignKey('companies.id'))
    calculation_id: Mapped[str]=mapped_column(ForeignKey('calculation_runs.id'))
    title: Mapped[str]=mapped_column(String(160))
    method: Mapped[str]=mapped_column(String(16))
    policy: Mapped[str]=mapped_column(String(32))
    state: Mapped[str]=mapped_column(String(24))
    idem_key: Mapped[str]=mapped_column(String(100))
    request_hash: Mapped[str]=mapped_column(String(64))
    input_hash: Mapped[str]=mapped_column(String(64))
    result_hash: Mapped[str]=mapped_column(String(64))
    input: Mapped[str]=mapped_column(Text)
    output: Mapped[str]=mapped_column(Text)
    created: Mapped[float]=mapped_column(Float,default=time.time)
