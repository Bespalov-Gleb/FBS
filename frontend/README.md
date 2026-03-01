# FBS Frontend MVP

Фронтенд приложения FBS.tools для управления заказами и маркетплейсами.

## Стек

- React 18+
- TypeScript
- Vite
- MUI (Material-UI)
- React Router
- Redux Toolkit
- TanStack Query
- React Hook Form + Zod
- Axios

## Запуск

```bash
npm install
npm run dev
```

Приложение будет доступно на `http://localhost:5173`.

## Переменные окружения

Создайте файл `.env` на основе `env.example`:

```
VITE_API_URL=http://localhost:8000/api/v1
```

## Backend

Убедитесь, что backend запущен на `http://localhost:8000` и в `.env` backend указано:

```
BACKEND_CORS_ORIGINS=["http://localhost:5173"]
```

## Сборка

```bash
npm run build
```

Результат в папке `dist/`.
