# AI Brief PWA

Installable PWA с ежедневным AI-дайджестом.

## Архитектура

- `GitHub Actions` каждый день запускает генератор новостей.
- Генератор пишет JSON в `site/data/`.
- Workflow коммитит обновленные JSON-файлы обратно в репозиторий.
- `GitHub Pages` публикует `site/` как приложение.
- На телефоне сайт ставится как иконка на главный экран.

## Структура

- [site/index.html](/Users/irakoreshkova/Documents/New project/ai-news-pwa/site/index.html:1) — интерфейс приложения
- [site/app.js](/Users/irakoreshkova/Documents/New project/ai-news-pwa/site/app.js:1) — загрузка latest/archive JSON
- [site/sw.js](/Users/irakoreshkova/Documents/New project/ai-news-pwa/site/sw.js:1) — offline shell cache
- [scripts/generate_digest.py](/Users/irakoreshkova/Documents/New project/ai-news-pwa/scripts/generate_digest.py:1) — генерация данных

## Локальный прогон генератора

```bash
cd "/Users/irakoreshkova/Documents/New project"
python3 ai-news-pwa/scripts/generate_digest.py
```

## GitHub Secrets

- `AI_DIGEST_OPENAI_API_KEY` — опционально, для более качественных выжимок

Без этого ключа генератор использует RSS snippets как fallback.
