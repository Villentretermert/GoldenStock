# Права, сущности и контракты
Дата: 2026-10-21. Проектные требования, не работающая защита.

## Матрица доступа
| Объект/операция | Владелец | Коллега того же фонда | Другой фонд |
|---|---|---|---|
| Публичный каталог компаний | читать | читать | читать |
| Личное избранное | менять | нет | нет |
| Приватный документ/факт | читать/создавать версию | нет | нет |
| Личная модель/шаблон | читать/создавать версию/публиковать | нет | нет |
| Общая модель фонда | читать/новая версия автора | читать/копировать | нет |
| Общие источники фонда | по выданным правам | читать | нет |
| Export/Job/Notification | по ACL исходного объекта | только при доступе | нет |
| Разметка AI Lab | разрешённый dataset | разрешённый dataset | нет |

Публикация создаёт новую snapshot-версию и аудит. Нельзя просто менять флаг на template с чужими скрытыми листами. Все факты и вложения должны быть доступны целевой аудитории. Пользователь видит список раскрываемых данных до подтверждения. Если часть источников приватна, публикация блокируется либо аналитик создаёт очищенную копию.
Общая версия не допускает перезаписи коллегой. Отзыв общего доступа не удаляет уже скачанные файлы; это явно отражается в интерфейсе. Технический администратор управляет учётными записями, но не получает автоматическое право читать финансовые документы.

## Сущности и ключи
Organization(id); User(id); Membership(organization_id,user_id,status); Company(id,legal_name,identifiers); Watchlist(tenant_id,user_id,company_id).
DocumentVersion(id,tenant_id,owner_id,visibility,sha256,blob_key,source_id,published_at,ingested_at,language,revision).
FactVersion(id,tenant_id,company_id,metric_code,value_decimal,unit,currency,scale,period_start,period_end,period_type,accounting_basis,scope,evidence_id,review_status,revision).
Evidence(id,document_version_id,page,table,cell,excerpt,bbox); Review(id,fact_version_id,reviewer,decision,reason,created_at).
TemplateVersion(id,tenant_id,owner_id,visibility,input_contract,output_contract,formula_hash); ModelRun(id,tenant_id,template_version_id,input_snapshot_hash,assumptions,engine_version,status).
Job(id,tenant_id,actor_id,type,input_hash,config_hash,state,lease_until,attempts,error_code); Export(id,run_id,format,artifact_hash); AuditEvent(id,tenant_id,actor,action,target,time).
ModelConfig(id,weights_digest,quantization,context_limit,license); PromptVersion(id,digest); DatasetVersion(id,digest,split,review_state); ExperimentRun(id,dataset_version_id,model_config_id,prompt_version_id,metrics).

## Изоляция по всей цепочке
tenant_id приходит из проверенной сервером сессии, не из поля формы. Запросы к объекту проверяют tenant и ACL. Workers повторно проверяют действующее членство и разрешения до чтения и перед выдачей артефакта. PostgreSQL RLS — дополнительная граница; служебная роль приложения не BYPASSRLS, tenant context задаётся внутри транзакции, тестируется pool reuse.
Индексы RAG, cache keys, blob paths, jobs, search snippets и логи разделены по tenant и ACL. Общий корпус содержит только явно публичные источники. Дедупликация приватных документов не раскрывает существование совпадения в другом фонде. Скачивание через backend с повторной проверкой доступа, а не по угадываемому пути.

## API-контракты для GS-005 и далее
POST /documents: файл+company_id, сервер назначает tenant; ответ document_id/job_id.
GET /jobs/{id}: authorized state/progress/error, без сырых секретов и документов в тексте ошибки.
POST /facts/{id}/reviews: decision+reason+expected_revision; конкурентное изменение даёт conflict.
POST /model-runs: template_version_id+fact_snapshot+scenario; missing/critical inputs возвращают validation errors.
POST /models/{id}/publish: expected_revision+acknowledged_evidence_ids; проверка provenance и прав.
POST /companies/{id}/research: только разрешённые источники, задача в очередь.
GET /exports/{id}: access recheck; проверка связи с run и tenant.
Все записи аудируются. Idempotency-Key хранится в tenant scope. Версия схемы API /v1 задаётся при реализации.

## Разбор сценариев угроз
| Сценарий | Проектная защита | Будущий тест |
|---|---|---|
| Аналитик B угадывает ID A | tenant+ACL до чтения | GET, search, export не раскрывают объект |
| Другой фонд использует job ID | контекст tenant и actor в worker | отказ и отсутствие данных в error |
| Документ приказывает отправить файлы | документ всегда untrusted data; allowlist инструментов | prompt injection не вызывает сетевую отправку |
| Публикация раскрывает hidden sheet | проверка всех зависимостей/листы/metadata | блокировка приватного provenance |
| Браузер вызывает inference | порт не публикуется, нет client credentials | запрос снаружи недоступен |
| Worker падает после экспорта | lease+idem key+атомарная регистрация | один конечный артефакт/версия |
| URL ведёт в localhost/metadata | allowlist и проверка redirect/DNS на каждом переходе | SSRF test GS-009 |
| Уволенный сотрудник скачивает старый export | актуальная membership и ACL | немедленный отказ после отзыва |

В GS-002 проведена статическая проверка этих сценариев. Их эксплуатационная проверка возможна только после реализации GS-006–015.
