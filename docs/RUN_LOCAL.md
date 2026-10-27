Актуально 2026-10-27: нормализация, ручное утверждение входных фактов и локальные AI-сводки реализованы. Финансовый расчёт ещё впереди. См. STAGE_4_REVIEW.md и LOCAL_AI.md. Исторические ограничения ниже относятся к ранним этапам.

# GoldenStock: локальный запуск и первый вход
После извлечения доступна Normalize: создание приватных версий фактов и диагностика конфликтов. Инструкция — [NORMALIZATION.md](NORMALIZATION.md). Нормализация контекста ручная; утверждение и расчёт пока не реализованы.

Работают аккаунты, избранное, черновики, приватные оригиналы, проверка целостности и локальное извлечение PDF/PPTX/XLSX с OCR сканов. Сценарий и ограничения — [EXTRACTION.md](EXTRACTION.md). Нормализация метрик и расчёт ещё не реализованы. Запуск только на loopback; защищённый удалённый доступ — GS-023.

## Первый вход
В PowerShell из папки проекта после запуска контейнеров:
```powershell
wsl -d Ubuntu -- docker compose exec web python -m goldenstock.admin create-admin --login owner
```
Введите новый пароль длиной 12–128 символов и повторите его. Ввод скрыт. Команда создаёт новый фонд и его технического администратора; повторный запуск с тем же логином запрещён. Затем откройте http://127.0.0.1:8081/login и войдите как owner. В Team можно создавать аналитиков и отключать их; отключение сразу отзывает сессии. Не вводите пароль в аргументах команды или в чат.

Сброс пароля локальным оператором: `wsl -d Ubuntu -- docker compose exec web python -m goldenstock.admin reset-password --login owner`. Все прежние сессии аккаунта отзываются. Техническая роль не позволяет читать чужие личные финансовые объекты.

Ни один постоянный пользовательский пароль не создавался автоматически. В браузерной проверке использовался случайный QA-аккаунт в отдельной синтетической организации; после теста он отключён. Синтетические объекты сохраняются в этой организации и не видны пользовательскому фонду.

## Что попробовать
1. Companies → Add to watchlist → Watchlist: избранное личное.
2. Models → Create private draft: пока только название, не расчёт. Владелец может открыть название коллегам своего фонда и отозвать доступ.
3. Files & jobs → выбрать компанию → PDF/XLSX/PPTX до 50 MB → Upload private original.
4. Refresh processing status → succeeded означает совпадение SHA-256, не проверку содержания.
5. Download original возвращает исходные байты. Для новой версии выбрать существующий документ и ту же компанию; предыдущий файл сохраняется.
6. При failed открыть Job history; после устранения причины Retry verification запускает новый цикл до трёх попыток.

Одинаковый Idempotency-Key с тем же запросом возвращает прежнюю версию. Другой запрос с тем же ключом отклоняется. Новая отправка с новым ключом считается отдельной загрузкой; глобальной дедупликации приватных файлов между фондами нет.

## Docker: целевой запуск
Предварительно нужны работающий Docker Engine с Compose и Python 3.12–3.14 для скрипта запуска. На Windows можно использовать Docker Desktop/WSL2 либо уже установленный Docker Engine внутри Ubuntu WSL2.
```powershell
python scripts/bootstrap.py --up
# Если Docker установлен только в Ubuntu WSL2, из папки проекта:
wsl -d Ubuntu -- python3 scripts/bootstrap.py --up
```
Команда создаёт .env со случайным паролем, не перезаписывая существующий, собирает образ и ожидает готовности web/worker/db. Если .env уже создан из пустого .env.example, заполнить POSTGRES_PASSWORD случайным hex-значением: пустой пароль останавливает Compose. Не использовать пароль с URL-спецсимволами без percent-encoding.
Открыть http://127.0.0.1:8080. Только web имеет host port, и только на loopback. PostgreSQL и inference доступны лишь во внутренней сети Compose.

На текущей машине проверенный экземпляр запущен на http://127.0.0.1:8081 командой `wsl -d Ubuntu -- env GS_WEB_PORT=8081 python3 scripts/bootstrap.py --up`. Сохраняйте этот override при повторном запуске, если нужен тот же порт. Если после перезагрузки Docker не работает: `wsl -d Ubuntu -u root -- service docker start`. Для команд docker ниже при работе из Windows используйте префикс `wsl -d Ubuntu --`.

Остановить без удаления данных: `docker compose down`. Не использовать `down -v`: это удаляет volumes.
Журнал: `docker compose logs --tail 100 web worker migrate`. Не публиковать .env или вывод compose config с раскрытыми переменными.

## Локальный ИИ, пока без модели
```powershell
python scripts/bootstrap.py --up --ai
# После проверки WSL/GPU:
python scripts/bootstrap.py --up --gpu
```
Профиль ai запускает отдельный Ollama endpoint. Модель не скачивается автоматически. Внутренняя сеть не имеет выхода в интернет; подготовку/импорт разрешённых весов выполним в GS-013. Нет прокси /api/generate в публичном приложении. Статус no_model_loaded означает доступный сервер без моделей, unavailable — выключенный/недоступный.
Изображения контейнеров загружает Docker daemon при установке. Runtime inference использует private network. Проверка API tags не является тестом качества модели.

## Native smoke без Docker
Это отдельный режим проверки UI/API с SQLite, не замена PostgreSQL-пилота.
```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.lock
.\.venv\Scripts\python.exe scripts/dev.py
```
Открыть http://127.0.0.1:8080. Ctrl+C останавливает web и worker. Данные проверки находятся в data/ и исключены из Git.
Linux/macOS: вместо .venv\Scripts\python.exe использовать .venv/bin/python.

## Состав
- FastAPI: /health/live, /health/ready, /api/v1/status.
- UI: страницы на Python/FastAPI, формы обращаются только к собственному API. Изменение кандидата NiceGUI описано в ADR-0003.
- Alembic: 0001 heartbeat, 0002 организации/аккаунты/черновики/аудит, 0003 каталог/избранное, 0004 документы/версии/очередь.
- Worker: heartbeat, lease 60 секунд, до трёх попыток, backoff, защита от старого исполнителя и повторная проверка действующего аккаунта. Выполняется только verify_original.
- Docker: web, worker, migrate, db; опционально inference. Named volumes сохраняют данные.

Readiness требует актуальную миграцию и свежий worker heartbeat. Liveness означает только работающий процесс. Отсутствие опциональной модели не блокирует просмотр приложения.

## Проверки
```powershell
.\.venv\Scripts\python.exe -m pytest -q
```
36 тестов проходят. Проверка конкурентности на PostgreSQL: `Get-Content -Raw scripts/check_postgres.py | wsl -d Ubuntu -- docker compose exec -T web python -`. Она создаёт и удаляет только собственную временную схему QA. Browser smoke: `.\.venv\Scripts\python.exe scripts/check_browser.py` (требует bundled Chrome/Playwright runtime Codex).

CI содержит тесты, Docker smoke и PostgreSQL concurrency/crash check. Пока исходники не опубликованы, GitHub Actions не запускается. Известен warning TestClient о будущем переходе на httpx2, тесты проходят.

Ограничения: RLS, TLS/VPN, антивирусный движок и полноценная политика ресурсов/резервных копий не реализованы. Типы/размеры/Office ZIP проверяются, но это не гарантия безопасности содержания. Неизменяемость оригинала обеспечивается API и exclusive-create, не аппаратным WORM. При аварии между записью blob и транзакцией возможен недостижимый файл; автоматическое удаление не включено. SSO и несколько фондов у одного аккаунта пока отсутствуют.

## Источники решений
[NiceGUI/FastAPI](https://github.com/zauberzeug/nicegui/tree/main/examples/fastapi), [Compose startup order](https://docs.docker.com/compose/how-tos/startup-order/), [Ollama Docker](https://docs.ollama.com/docker).
