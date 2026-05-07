# Быстрая замена UI на Windows

В корне проекта:

```powershell
cd C:\Users\Slav4ik\PycharmProjects\AnaliticAgenticPlatform

if (Test-Path .\ui\analyst_ui_backup_v13) { Remove-Item -Recurse -Force .\ui\analyst_ui_backup_v13 }
Rename-Item .\ui\analyst_ui .\analyst_ui_backup_v13
New-Item -ItemType Directory .\ui\analyst_ui
```

Распакуйте содержимое архива внутрь:

```text
C:\Users\Slav4ik\PycharmProjects\AnaliticAgenticPlatform\ui\analyst_ui
```

Потом:

```powershell
cd .\ui\analyst_ui

if (Test-Path .\node_modules) { Remove-Item -Recurse -Force .\node_modules }
if (Test-Path .\package-lock.json) { Remove-Item -Force .\package-lock.json }

npm install
npm run dev
```

Backend:

```powershell
.\.venv\Scripts\python.exe -m uvicorn main_ui_agent_server:create_app_with_agent --factory --host 127.0.0.1 --port 8000
```

UI:

```text
http://127.0.0.1:5173
```
