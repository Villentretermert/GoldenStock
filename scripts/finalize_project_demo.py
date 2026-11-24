"""Validate the local MP4 and create an offline chapter player and visual samples."""
from pathlib import Path
import html
import json
import re
import subprocess


def timestamp(seconds):
    value = int(seconds)
    return f'{value // 60:02}:{value % 60:02}'


def main():
    root = Path.cwd()
    build = root / '.build-overview'
    output = root / 'deliverables'
    data = json.loads((build / 'demo-chapters.json').read_text(encoding='utf-8'))
    video = output / 'GoldenStock-Project-Demo-2026-11-24.mp4'
    ffmpeg = next((build / 'media-runtime/imageio_ffmpeg/binaries').glob('ffmpeg-*.exe'))
    # Decode the complete finished stream, not just the first frame or container header.
    check = subprocess.run([str(ffmpeg), '-v', 'error', '-i', str(video), '-f', 'null', '-'],
                           capture_output=True, text=True)
    if check.returncode or check.stderr.strip():
        raise RuntimeError('Video decoding failed: ' + check.stderr[-1000:])
    metadata = subprocess.run([str(ffmpeg), '-i', str(video)], capture_output=True, text=True).stderr
    match = re.search(r'Duration: (\d+):(\d+):(\d+\.\d+)', metadata)
    if not match:
        raise RuntimeError('Video duration was not found')
    hours, minutes, seconds = map(float, match.groups())
    actual = hours * 3600 + minutes * 60 + seconds
    if abs(actual - data['duration']) > 0.3:
        raise RuntimeError('Video duration does not match recorded frames')
    samples = build / 'video-frames'
    samples.mkdir(exist_ok=True)
    for index, chapter in enumerate(data['chapters'], 1):
        subprocess.run([str(ffmpeg), '-v', 'error', '-ss', str(chapter['start'] + 2),
                        '-i', str(video), '-frames:v', '1', '-y', str(samples / f'chapter-{index:02}.png')],
                       check=True, capture_output=True)
    buttons = ''.join(f'<button data-time="{c["start"]}"><time>{timestamp(c["start"])}</time> '
                      f'{html.escape(c["title"])}</button>' for c in data['chapters'])
    player = f'''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>GoldenStock · видеодемо</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#f5f5ef;color:#193b30;font:17px/1.5 Arial,sans-serif}}
header{{padding:24px 4vw}}h1{{margin:0 0 8px}}p{{margin:6px 0}}main{{display:grid;grid-template-columns:minmax(0,3fr) minmax(280px,1fr);gap:24px;padding:0 4vw 40px}}
video{{width:100%;background:#193b30;border:1px solid #ccd8cf}}nav{{max-height:72vh;overflow:auto}}button{{display:block;width:100%;text-align:left;border:0;border-bottom:1px solid #ccd8cf;padding:13px;background:transparent;color:inherit;cursor:pointer;font:inherit}}button:hover,button:focus{{background:#e0eade}}time{{font-weight:bold;color:#8a5c13}}
@media(max-width:900px){{main{{display:block}}nav{{max-height:none}}}}
</style><header><h1>GoldenStock: визуальное видеодемо</h1>
<p>Реальный локальный интерфейс · 24 ноября 2026 · {timestamp(actual)} · {len(data['chapters'])} глав</p>
<p>Учебный кабинет и синтетические числа. Русские пояснения в кадре, без звуковой дорожки.</p>
<p>Данные подготовлены перед записью. В кадре выполняются публикация структуры, replay и скачивание трёх экспортов.</p></header>
<main><section><video id="tour" controls preload="metadata" src="{video.name}"></video>
<p>Для автономного просмотра оставьте этот HTML и MP4 в одной папке. Главы справа перемещают запись к нужному экрану.</p>
<p>32/36 задач завершены технически. Реальные 95%, десятиминутное обновление и полевая приёмка остаются открытыми.</p></section><nav aria-label="Главы видеодемо">{buttons}</nav></main>
<script>document.querySelectorAll('[data-time]').forEach(b=>b.onclick=()=>{{const v=document.getElementById('tour');v.currentTime=Number(b.dataset.time);v.play();}});</script></html>'''
    (output / 'GoldenStock-Project-Demo-2026-11-24.html').write_text(player, encoding='utf-8')
    chapters = ['# Видеодемо GoldenStock',
                'Дата: 24 ноября 2026. Реальный локальный интерфейс, подготовленные синтетические данные. '
                'Без звука, с русскими пояснениями в кадре. Настоящие финансовые факты и подписи пользователя не создавались.',
                f'Длительность: {timestamp(actual)}. Глав: {len(data["chapters"])}.',
                'В начале подготовки GPU admission отказал из-за резерва. Для учебного пакета явно выбран CPU. '
                'Время подготовки до записи не включено в видео и не является замером десятиминутного обновления.',
                f'Фактическое состояние ИИ в записи: `{data.get("aiState")}`; код: `{data.get("aiError") or "none"}`. '
                'Неудачная попытка показана как отказ. Для дальнейших шагов использован отдельный заранее подготовленный '
                'набор синтетических фактов, а не принятый результат этого ИИ-запуска.',
                '## Навигация']
    chapters += [f'- {timestamp(c["start"])} — {c["title"]}. {c["body"]}' for c in data['chapters']]
    chapters += ['\n## Локальные файлы',
                 '- `deliverables/GoldenStock-Project-Demo-2026-11-24.mp4`',
                 '- `deliverables/GoldenStock-Project-Demo-2026-11-24.html` — автономный проигрыватель с главами.',
                 '\n## Повтор записи',
                 'Установить `GS_RUNTIME_ROOT` по bundled runtime. Для записи нужны Playwright/Chrome, '
                 'локальный Docker-стенд и FFmpeg в `.build-overview/media-runtime/imageio_ffmpeg/binaries`. '
                 'В этой записи использован imageio-ffmpeg 0.6.0 в изолированной build-папке. '
                 '`GS_DEMO_CPU=1` явно разрешает выбор CPU только для синтетических заданий. '
                 'Запустить `scripts/record_project_demo.py`, затем `scripts/finalize_project_demo.py`. '
                 'Существующий MP4 не перезаписывается. Синтетический аккаунт отзывается в finally.',
                 '\n## Проверка',
                 'Готовый MP4 полностью декодирован FFmpeg без ошибок. Длительность сверена со счётчиком кадров. '
                 'Кадры каждой главы извлечены для визуального просмотра. Приложение не изменялось ради записи. '
                 'Код сценария, этот текст и техническая документация публикуются, видео и скриншоты остаются локальными.']
    (root / 'docs/PROJECT_DEMO.md').write_text('\n\n'.join(chapters), encoding='utf-8')
    (build / 'media-validation.json').write_text(json.dumps(dict(duration=actual, chapters=len(data['chapters']),
        frames=data['duration'] * 8, full_decode='passed', synthetic=True,
        ai_state=data.get('aiState'),ai_error=data.get('aiError')), indent=2), encoding='utf-8')
    print(json.dumps(dict(duration=actual, chapters=len(data['chapters']), full_decode='passed')))


if __name__ == '__main__':
    main()
