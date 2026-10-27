"""Infrastructure and tenant-owned workspace entities; no financial facts yet."""
import time
import uuid
from sqlalchemy import Float, String, Boolean, Integer, ForeignKey, UniqueConstraint, Text
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
    lease_until: Mapped[float]=mapped_column(Float,default=0)
    lease_token: Mapped[str]=mapped_column(String(32),default='')
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
