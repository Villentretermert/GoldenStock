# Концепция интерфейса
Обновлено 2026-10-21: интерактивный прототип в design/goldenstock-prototype.html. Все численные значения синтетические; настоящий расчёт, загрузка и экспорт ещё не реализованы. Python UI будет создан в GS-005–007. Сценарии проверены в Chrome автоматически и визуально на 1280px/390px.

```text
GOLDENSTOCK       Companies | Models | Jobs | AI Lab     Analyst
--------------------------------------------------------------
My watchlist                          [Search company]
Sberbank     Summary unavailable       [Research]
Tinkoff      Awaiting source review    [Research]
[+ Add company]                       Notifications (0)

COMPANY / Overview | Facts | Valuations | Sources | Changes
[Upload document] [Research] [Build valuation]
Summary: claims with source links and publication dates
Conflicts: metric / value A / value B / sources / [Review]
Models: template / visibility / version / review status
[Download XLSX] [Download PDF] [Download PPTX]

REVIEW
Source page / highlighted table  |  Extracted metric
                                 |  Period / currency / scale
                                 |  [Correct] [Confirm] [Flag]

MODEL LIBRARY
Name | Version | Owner | Private / Organization | [Use]
[Upload template] [Validate] [Make shared]
```

Сценарий: аналитик выбирает компанию → загружает документ → видит ход обработки → сверяет спорные факты → выбирает шаблон и сценарий → получает расчёт и пояснение → скачивает три согласованных артефакта.
По кнопке Research сервер ищет в разрешённых публичных источниках и формирует сводку с цитатами. Новая отчётность создаёт уведомление; предыдущая утверждённая модель сохраняется.
Обязательные состояния: пустой кабинет, нет английского источника, конфликт, ошибка OCR, очередь GPU, отсутствующий показатель, несовместимый шаблон, истёкшая сессия, отсутствие доступа.
AI Lab: задача/датасет → несколько локальных моделей → сравнительная таблица качества/времени → ручная разметка → выбор версии.

