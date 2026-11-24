# GoldenStock: технический словарь данных

Срез кода на 24 ноября 2026. Источник: `src/goldenstock/models.py`.

40 прикладных таблиц. Служебная `alembic_version` учитывается отдельно.
Это описание декларативной схемы, без чтения БД или пользовательских записей. Логические связи внутри JSON payload и серверные ACL не заменяются внешними ключами. Некоторые owner_id/org_id хранятся строками: наличие поля само по себе не обеспечивает изоляцию.

## ai_executions

| Поле | Тип | PK | NULL | Внешний ключ |
|---|---|---|---|---|
| run_id | VARCHAR(32) | да | нет | ai_runs.id |
| attempt | INTEGER | да | нет | — |
| state | VARCHAR(24) |  | нет | — |
| started | FLOAT |  | нет | — |
| finished | FLOAT |  | да | — |
| receipt | TEXT |  | нет | — |

## ai_proposal_batches

| Поле | Тип | PK | NULL | Внешний ключ |
|---|---|---|---|---|
| id | VARCHAR(32) | да | нет | — |
| org_id | VARCHAR(32) |  | нет | organizations.id |
| owner_id | VARCHAR(32) |  | нет | users.id |
| company_id | VARCHAR(32) |  | нет | companies.id |
| version_id | VARCHAR(32) |  | нет | document_versions.id |
| fingerprint | VARCHAR(64) |  | нет | — |
| manifest | TEXT |  | нет | — |
| manifest_hash | VARCHAR(64) |  | нет | — |
| created | FLOAT |  | нет | — |

Уникальность: `owner_id, fingerprint`.

## ai_runs

| Поле | Тип | PK | NULL | Внешний ключ |
|---|---|---|---|---|
| id | VARCHAR(32) | да | нет | — |
| org_id | VARCHAR(32) |  | нет | — |
| owner_id | VARCHAR(32) |  | нет | — |
| company_id | VARCHAR(32) |  | нет | — |
| kind | VARCHAR(24) |  | нет | — |
| profile | VARCHAR(32) |  | нет | — |
| fingerprint | VARCHAR(64) |  | нет | — |
| input | TEXT |  | нет | — |
| output | TEXT |  | нет | — |
| state | VARCHAR(24) |  | нет | — |
| error | VARCHAR(80) |  | нет | — |
| attempts | INTEGER |  | нет | — |
| device | VARCHAR(8) |  | нет | — |
| lease_until | FLOAT |  | нет | — |
| lease_token | VARCHAR(32) |  | нет | — |
| created | FLOAT |  | нет | — |

Уникальность: `owner_id, fingerprint`.

## audit_events

| Поле | Тип | PK | NULL | Внешний ключ |
|---|---|---|---|---|
| id | VARCHAR(32) | да | нет | — |
| org_id | VARCHAR(32) |  | нет | — |
| actor_id | VARCHAR(32) |  | нет | — |
| action | VARCHAR(80) |  | нет | — |
| target | VARCHAR(32) |  | нет | — |
| detail | TEXT |  | нет | — |
| created | FLOAT |  | нет | — |

## calculation_runs

| Поле | Тип | PK | NULL | Внешний ключ |
|---|---|---|---|---|
| id | VARCHAR(32) | да | нет | — |
| org_id | VARCHAR(32) |  | нет | organizations.id |
| owner_id | VARCHAR(32) |  | нет | users.id |
| company_id | VARCHAR(32) |  | нет | companies.id |
| version_id | VARCHAR(32) |  | нет | template_versions.id |
| title | VARCHAR(160) |  | нет | — |
| engine | VARCHAR(32) |  | нет | — |
| idem_key | VARCHAR(100) |  | нет | — |
| request_hash | VARCHAR(64) |  | нет | — |
| input_hash | VARCHAR(64) |  | нет | — |
| result_hash | VARCHAR(64) |  | нет | — |
| input | TEXT |  | нет | — |
| output | TEXT |  | нет | — |
| state | VARCHAR(40) |  | нет | — |
| created | FLOAT |  | нет | — |

Уникальность: `owner_id, idem_key`.

## companies

| Поле | Тип | PK | NULL | Внешний ключ |
|---|---|---|---|---|
| id | VARCHAR(32) | да | нет | — |
| name | VARCHAR(160) |  | нет | — |
| identifier | VARCHAR(120) |  | нет | — |
| candidate | BOOLEAN |  | нет | — |
| source_url | VARCHAR(300) |  | нет | — |
| source_checked | FLOAT |  | да | — |

## document_versions

| Поле | Тип | PK | NULL | Внешний ключ |
|---|---|---|---|---|
| id | VARCHAR(32) | да | нет | — |
| document_id | VARCHAR(32) |  | нет | documents.id |
| org_id | VARCHAR(32) |  | нет | — |
| owner_id | VARCHAR(32) |  | нет | — |
| number | INTEGER |  | нет | — |
| filename | VARCHAR(200) |  | нет | — |
| sha256 | VARCHAR(64) |  | нет | — |
| size | INTEGER |  | нет | — |
| blob_key | VARCHAR(200) |  | нет | — |
| idem_key | VARCHAR(100) |  | нет | — |
| request_hash | VARCHAR(64) |  | нет | — |
| created | FLOAT |  | нет | — |

Уникальность: `document_id, number`; `owner_id, idem_key`.

## documents

| Поле | Тип | PK | NULL | Внешний ключ |
|---|---|---|---|---|
| id | VARCHAR(32) | да | нет | — |
| org_id | VARCHAR(32) |  | нет | organizations.id |
| owner_id | VARCHAR(32) |  | нет | users.id |
| company_id | VARCHAR(32) |  | нет | companies.id |
| shared | BOOLEAN |  | нет | — |
| filename | VARCHAR(200) |  | нет | — |
| revision | INTEGER |  | нет | — |

## extraction_checkpoints

| Поле | Тип | PK | NULL | Внешний ключ |
|---|---|---|---|---|
| version_id | VARCHAR(32) | да | нет | document_versions.id |
| parser_version | VARCHAR(40) |  | нет | — |
| source_sha256 | VARCHAR(64) |  | нет | — |
| completed_pages | INTEGER |  | нет | — |
| total_pages | INTEGER |  | нет | — |
| payload | TEXT |  | нет | — |
| payload_sha256 | VARCHAR(64) |  | нет | — |

## extractions

| Поле | Тип | PK | NULL | Внешний ключ |
|---|---|---|---|---|
| version_id | VARCHAR(32) | да | нет | document_versions.id |
| parser_version | VARCHAR(40) |  | нет | — |
| source_sha256 | VARCHAR(64) |  | нет | — |
| payload | TEXT |  | нет | — |
| created | FLOAT |  | нет | — |

## fact_reviews

| Поле | Тип | PK | NULL | Внешний ключ |
|---|---|---|---|---|
| id | VARCHAR(32) | да | нет | — |
| fact_id | VARCHAR(32) |  | нет | facts.id |
| revision | INTEGER |  | нет | — |
| actor_id | VARCHAR(32) |  | нет | — |
| decision | VARCHAR(20) |  | нет | — |
| note | TEXT |  | нет | — |
| created | FLOAT |  | нет | — |

Уникальность: `fact_id, revision`.

## facts

| Поле | Тип | PK | NULL | Внешний ключ |
|---|---|---|---|---|
| id | VARCHAR(32) | да | нет | — |
| org_id | VARCHAR(32) |  | нет | organizations.id |
| owner_id | VARCHAR(32) |  | нет | users.id |
| company_id | VARCHAR(32) |  | нет | companies.id |
| version_id | VARCHAR(32) |  | нет | document_versions.id |
| fingerprint | VARCHAR(64) |  | нет | — |
| supersedes | VARCHAR(32) |  | да | facts.id |
| payload | TEXT |  | нет | — |
| created | FLOAT |  | нет | — |

Уникальность: `owner_id, fingerprint`; `supersedes`.

## favorites

| Поле | Тип | PK | NULL | Внешний ключ |
|---|---|---|---|---|
| user_id | VARCHAR(32) | да | нет | users.id |
| company_id | VARCHAR(32) | да | нет | companies.id |

## input_snapshots

| Поле | Тип | PK | NULL | Внешний ключ |
|---|---|---|---|---|
| id | VARCHAR(32) | да | нет | — |
| org_id | VARCHAR(32) |  | нет | — |
| owner_id | VARCHAR(32) |  | нет | — |
| company_id | VARCHAR(32) |  | нет | companies.id |
| title | VARCHAR(160) |  | нет | — |
| state_hash | VARCHAR(64) |  | нет | — |
| payload | TEXT |  | нет | — |
| created | FLOAT |  | нет | — |

Уникальность: `owner_id, company_id, state_hash`.

## job_events

| Поле | Тип | PK | NULL | Внешний ключ |
|---|---|---|---|---|
| id | VARCHAR(32) | да | нет | — |
| job_id | VARCHAR(32) |  | нет | jobs.id |
| state | VARCHAR(24) |  | нет | — |
| attempt | INTEGER |  | нет | — |
| created | FLOAT |  | нет | — |

## jobs

| Поле | Тип | PK | NULL | Внешний ключ |
|---|---|---|---|---|
| id | VARCHAR(32) | да | нет | — |
| org_id | VARCHAR(32) |  | нет | — |
| actor_id | VARCHAR(32) |  | нет | — |
| version_id | VARCHAR(32) |  | нет | document_versions.id |
| kind | VARCHAR(24) |  | нет | — |
| state | VARCHAR(24) |  | нет | — |
| attempts | INTEGER |  | нет | — |
| lease_until | FLOAT |  | нет | — |
| lease_token | VARCHAR(32) |  | нет | — |
| available_at | FLOAT |  | нет | — |
| error_code | VARCHAR(40) |  | нет | — |
| created | FLOAT |  | нет | — |

Уникальность: `version_id`.

## lab_annotations

| Поле | Тип | PK | NULL | Внешний ключ |
|---|---|---|---|---|
| id | VARCHAR(32) | да | нет | — |
| experiment_id | VARCHAR(32) |  | нет | lab_experiments.id |
| run_id | VARCHAR(32) |  | нет | ai_runs.id |
| actor_id | VARCHAR(32) |  | нет | users.id |
| revision | INTEGER |  | нет | — |
| verdict | VARCHAR(16) |  | нет | — |
| reason | VARCHAR(1000) |  | нет | — |
| output_hash | VARCHAR(64) |  | нет | — |
| created | FLOAT |  | нет | — |

Уникальность: `run_id, revision`.

## lab_datasets

| Поле | Тип | PK | NULL | Внешний ключ |
|---|---|---|---|---|
| id | VARCHAR(32) | да | нет | — |
| org_id | VARCHAR(32) |  | нет | organizations.id |
| owner_id | VARCHAR(32) |  | нет | users.id |
| parent_id | VARCHAR(32) |  | да | lab_datasets.id |
| revision | INTEGER |  | нет | — |
| title | VARCHAR(160) |  | нет | — |
| split | VARCHAR(16) |  | нет | — |
| kind | VARCHAR(16) |  | нет | — |
| fingerprint | VARCHAR(64) |  | нет | — |
| payload | TEXT |  | нет | — |
| created | FLOAT |  | нет | — |

Уникальность: `owner_id, fingerprint`.

## lab_exchanges

| Поле | Тип | PK | NULL | Внешний ключ |
|---|---|---|---|---|
| id | VARCHAR(32) | да | нет | — |
| org_id | VARCHAR(32) |  | нет | organizations.id |
| owner_id | VARCHAR(32) |  | нет | users.id |
| fingerprint | VARCHAR(64) |  | нет | — |
| payload | TEXT |  | нет | — |
| created | FLOAT |  | нет | — |

Уникальность: `owner_id, fingerprint`.

## lab_experiments

| Поле | Тип | PK | NULL | Внешний ключ |
|---|---|---|---|---|
| id | VARCHAR(32) | да | нет | — |
| org_id | VARCHAR(32) |  | нет | organizations.id |
| owner_id | VARCHAR(32) |  | нет | users.id |
| dataset_id | VARCHAR(32) |  | нет | lab_datasets.id |
| fingerprint | VARCHAR(64) |  | нет | — |
| manifest | TEXT |  | нет | — |
| manifest_hash | VARCHAR(64) |  | нет | — |
| revealed | BOOLEAN |  | нет | — |
| created | FLOAT |  | нет | — |

Уникальность: `owner_id, fingerprint`.

## lab_imports

| Поле | Тип | PK | NULL | Внешний ключ |
|---|---|---|---|---|
| id | VARCHAR(32) | да | нет | — |
| org_id | VARCHAR(32) |  | нет | organizations.id |
| owner_id | VARCHAR(32) |  | нет | users.id |
| exchange_id | VARCHAR(32) |  | нет | lab_exchanges.id |
| sha256 | VARCHAR(64) |  | нет | — |
| original | BLOB |  | нет | — |
| candidate | TEXT |  | нет | — |
| candidate_hash | VARCHAR(64) |  | нет | — |
| dataset_id | VARCHAR(32) |  | да | lab_datasets.id |
| confirmation_note | TEXT |  | нет | — |
| confirmed_at | FLOAT |  | да | — |
| created | FLOAT |  | нет | — |

Уникальность: `exchange_id, sha256`.

## lab_source_splits

| Поле | Тип | PK | NULL | Внешний ключ |
|---|---|---|---|---|
| owner_id | VARCHAR(32) | да | нет | users.id |
| source_hash | VARCHAR(64) | да | нет | — |
| split | VARCHAR(16) |  | нет | — |

## login_sessions

| Поле | Тип | PK | NULL | Внешний ключ |
|---|---|---|---|---|
| token_hash | VARCHAR(64) | да | нет | — |
| user_id | VARCHAR(32) |  | нет | users.id |
| csrf | VARCHAR(64) |  | нет | — |
| expires | FLOAT |  | нет | — |

## model_templates

| Поле | Тип | PK | NULL | Внешний ключ |
|---|---|---|---|---|
| id | VARCHAR(32) | да | нет | — |
| org_id | VARCHAR(32) |  | нет | organizations.id |
| owner_id | VARCHAR(32) |  | нет | users.id |
| title | VARCHAR(160) |  | нет | — |
| shared | BOOLEAN |  | нет | — |
| revision | INTEGER |  | нет | — |

## monitor_events

| Поле | Тип | PK | NULL | Внешний ключ |
|---|---|---|---|---|
| id | VARCHAR(32) | да | нет | — |
| source_id | VARCHAR(40) |  | нет | monitor_sources.id |
| fingerprint | VARCHAR(64) |  | нет | — |
| kind | VARCHAR(32) |  | нет | — |
| payload | TEXT |  | нет | — |
| created | FLOAT |  | нет | — |

Уникальность: `source_id, fingerprint`.

## monitor_fact_versions

| Поле | Тип | PK | NULL | Внешний ключ |
|---|---|---|---|---|
| id | VARCHAR(32) | да | нет | — |
| source_id | VARCHAR(40) |  | нет | monitor_sources.id |
| item_key | VARCHAR(64) |  | нет | — |
| revision | INTEGER |  | нет | — |
| previous_id | VARCHAR(32) |  | да | monitor_fact_versions.id |
| snapshot_id | VARCHAR(32) |  | нет | monitor_snapshots.id |
| reason | VARCHAR(32) |  | нет | — |
| payload | TEXT |  | нет | — |
| payload_sha256 | VARCHAR(64) |  | нет | — |
| created | FLOAT |  | нет | — |

Уникальность: `previous_id`; `source_id, item_key, revision`.

## monitor_observations

| Поле | Тип | PK | NULL | Внешний ключ |
|---|---|---|---|---|
| source_id | VARCHAR(40) | да | нет | monitor_sources.id |
| item_key | VARCHAR(64) | да | нет | — |
| payload | TEXT |  | нет | — |
| snapshot_id | VARCHAR(32) |  | нет | monitor_snapshots.id |
| history_id | VARCHAR(32) |  | да | — |

## monitor_snapshots

| Поле | Тип | PK | NULL | Внешний ключ |
|---|---|---|---|---|
| id | VARCHAR(32) | да | нет | — |
| source_id | VARCHAR(40) |  | нет | monitor_sources.id |
| sha256 | VARCHAR(64) |  | нет | — |
| url | TEXT |  | нет | — |
| payload | TEXT |  | нет | — |
| created | FLOAT |  | нет | — |

Уникальность: `source_id, sha256`.

## monitor_sources

| Поле | Тип | PK | NULL | Внешний ключ |
|---|---|---|---|---|
| id | VARCHAR(40) | да | нет | — |
| company_id | VARCHAR(32) |  | нет | companies.id |
| kind | VARCHAR(16) |  | нет | — |
| next_check | FLOAT |  | нет | — |
| last_attempt | FLOAT |  | да | — |
| last_success | FLOAT |  | да | — |
| error | VARCHAR(80) |  | нет | — |
| failures | INTEGER |  | нет | — |
| snapshot_id | VARCHAR(32) |  | да | — |

## organizations

| Поле | Тип | PK | NULL | Внешний ключ |
|---|---|---|---|---|
| id | VARCHAR(32) | да | нет | — |
| name | VARCHAR(120) |  | нет | — |

## public_snapshots

| Поле | Тип | PK | NULL | Внешний ключ |
|---|---|---|---|---|
| id | VARCHAR(32) | да | нет | — |
| company_id | VARCHAR(32) |  | нет | — |
| sha256 | VARCHAR(64) |  | нет | — |
| url | TEXT |  | нет | — |
| payload | TEXT |  | нет | — |
| created | FLOAT |  | нет | — |
| checked | FLOAT |  | нет | — |

Уникальность: `company_id, sha256`.

## site_notifications

| Поле | Тип | PK | NULL | Внешний ключ |
|---|---|---|---|---|
| id | VARCHAR(32) | да | нет | — |
| org_id | VARCHAR(32) |  | нет | organizations.id |
| owner_id | VARCHAR(32) |  | нет | users.id |
| event_id | VARCHAR(32) |  | нет | monitor_events.id |
| read_at | FLOAT |  | да | — |

Уникальность: `owner_id, event_id`.

## template_notifications

| Поле | Тип | PK | NULL | Внешний ключ |
|---|---|---|---|---|
| id | VARCHAR(32) | да | нет | — |
| org_id | VARCHAR(32) |  | нет | organizations.id |
| owner_id | VARCHAR(32) |  | нет | — |
| publication_id | VARCHAR(32) |  | нет | template_publications.id |
| read_at | FLOAT |  | да | — |

Уникальность: `owner_id, publication_id`.

## template_publications

| Поле | Тип | PK | NULL | Внешний ключ |
|---|---|---|---|---|
| id | VARCHAR(32) | да | нет | — |
| org_id | VARCHAR(32) |  | нет | organizations.id |
| template_id | VARCHAR(32) |  | нет | model_templates.id |
| version_id | VARCHAR(32) |  | нет | template_versions.id |
| publisher_id | VARCHAR(32) |  | нет | users.id |
| payload | TEXT |  | нет | — |
| payload_sha256 | VARCHAR(64) |  | нет | — |
| legacy | BOOLEAN |  | нет | — |
| created | FLOAT |  | нет | — |

Уникальность: `version_id`.

## template_versions

| Поле | Тип | PK | NULL | Внешний ключ |
|---|---|---|---|---|
| id | VARCHAR(32) | да | нет | — |
| template_id | VARCHAR(32) |  | нет | model_templates.id |
| owner_id | VARCHAR(32) |  | нет | — |
| number | INTEGER |  | нет | — |
| idem_key | VARCHAR(100) |  | нет | — |
| request_hash | VARCHAR(64) |  | нет | — |
| sha256 | VARCHAR(64) |  | нет | — |
| clean_sha256 | VARCHAR(64) |  | нет | — |
| blob_key | VARCHAR(200) |  | нет | — |
| clean_key | VARCHAR(200) |  | нет | — |
| contract | TEXT |  | нет | — |
| created | FLOAT |  | нет | — |

Уникальность: `owner_id, idem_key`; `template_id, number`.

## users

| Поле | Тип | PK | NULL | Внешний ключ |
|---|---|---|---|---|
| id | VARCHAR(32) | да | нет | — |
| org_id | VARCHAR(32) |  | нет | organizations.id |
| login | VARCHAR(120) |  | нет | — |
| password_hash | VARCHAR(256) |  | нет | — |
| active | BOOLEAN |  | нет | — |
| account_admin | BOOLEAN |  | нет | — |

Уникальность: `login`.

## valuation_runs

| Поле | Тип | PK | NULL | Внешний ключ |
|---|---|---|---|---|
| id | VARCHAR(32) | да | нет | — |
| org_id | VARCHAR(32) |  | нет | organizations.id |
| owner_id | VARCHAR(32) |  | нет | users.id |
| company_id | VARCHAR(32) |  | нет | companies.id |
| calculation_id | VARCHAR(32) |  | нет | calculation_runs.id |
| title | VARCHAR(160) |  | нет | — |
| method | VARCHAR(16) |  | нет | — |
| policy | VARCHAR(32) |  | нет | — |
| state | VARCHAR(24) |  | нет | — |
| idem_key | VARCHAR(100) |  | нет | — |
| request_hash | VARCHAR(64) |  | нет | — |
| input_hash | VARCHAR(64) |  | нет | — |
| result_hash | VARCHAR(64) |  | нет | — |
| input | TEXT |  | нет | — |
| output | TEXT |  | нет | — |
| created | FLOAT |  | нет | — |

Уникальность: `owner_id, idem_key`.

## workbook_mappings

| Поле | Тип | PK | NULL | Внешний ключ |
|---|---|---|---|---|
| id | VARCHAR(32) | да | нет | — |
| org_id | VARCHAR(32) |  | нет | organizations.id |
| owner_id | VARCHAR(32) |  | нет | users.id |
| parent_id | VARCHAR(32) |  | да | workbook_mappings.id |
| version_id | VARCHAR(32) |  | да | template_versions.id |
| title | VARCHAR(160) |  | нет | — |
| idem_key | VARCHAR(100) |  | нет | — |
| request_hash | VARCHAR(64) |  | нет | — |
| blob_key | VARCHAR(200) |  | нет | — |
| sha256 | VARCHAR(64) |  | нет | — |
| inspection | TEXT |  | нет | — |
| entries | TEXT |  | нет | — |
| revision | INTEGER |  | нет | — |
| created | FLOAT |  | нет | — |

Уникальность: `owner_id, idem_key`; `version_id`.

## worker_heartbeats

| Поле | Тип | PK | NULL | Внешний ключ |
|---|---|---|---|---|
| worker_id | VARCHAR(100) | да | нет | — |
| last_seen | FLOAT |  | нет | — |

## workspace_models

| Поле | Тип | PK | NULL | Внешний ключ |
|---|---|---|---|---|
| id | VARCHAR(32) | да | нет | — |
| org_id | VARCHAR(32) |  | нет | organizations.id |
| owner_id | VARCHAR(32) |  | нет | users.id |
| title | VARCHAR(160) |  | нет | — |
| shared | BOOLEAN |  | нет | — |
| revision | INTEGER |  | нет | — |