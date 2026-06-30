---
name: offline-ui-transfer
description: "Собирай, проверяй и переноси Deep Agents UI в закрытую Linux x86_64 среду без npm registry и доступа в интернет. Используй при изменениях frontend, package.json, yarn.lock или локального UI patch, а также для создания частей архива, проверки SHA-256, распаковки и запуска UI на целевой машине с Node.js 20."
---

# Offline-перенос Deep Agents UI

Использовать `scripts/build_ui_archive.sh` как единственный штатный способ обновления
Linux-архива UI. Скрипт берёт `node_modules` из предыдущего проверенного архива,
накладывает текущие файлы `local_ui/.runtime/deep-agents-ui`, запускает production build
и ESLint под закреплённым Node.js 20, затем создаёт новый архив и части по 90 MiB.

## Сборка

1. Проверить наличие:
   - `local_ui/.runtime/deep-agents-ui/package.json`;
   - `local_ui/.runtime/deep-agents-ui/yarn.lock`;
   - предыдущего `deep-agents-ui-node20-linux-x86_64.tar.gz`.
2. Запустить из Windows через WSL:

```powershell
wsl -d Ubuntu -- bash -lc "cd /mnt/c/path/to/deepagent && bash scripts/build_ui_archive.sh"
```

3. Считать сборку успешной только если:
   - `next build` завершился без ошибок;
   - ESLint не сообщил ошибок; warnings допустимы;
   - созданы полный архив, все `.partNNN` и `SHA256SUMS`.
4. Не включать в архив `.git`, `.next`, `.env.local` и `tsconfig.tsbuildinfo`.
5. Для GitHub передавать части `.partNNN` и `SHA256SUMS`. Полный архив больше лимита
   обычного GitHub-файла.

## Проверка перед переносом

```powershell
Get-FileHash .\deep-agents-ui-node20-linux-x86_64.tar.gz -Algorithm SHA256
Get-Item .\deep-agents-ui-node20-linux-x86_64.tar.gz.part*
```

Хэш полного архива должен совпадать со значением в `SHA256SUMS`.

## Восстановление в закрытом Linux

В каталоге с частями выполнить:

```bash
cat deep-agents-ui-node20-linux-x86_64.tar.gz.part* \
  > deep-agents-ui-node20-linux-x86_64.tar.gz

sha256sum -c SHA256SUMS
```

Не распаковывать архив при несовпадении хэша.

Из корня проекта, содержащего `run_ui.py`:

```bash
rm -rf local_ui/.runtime/deep-agents-ui
mkdir -p local_ui/.runtime/deep-agents-ui

tar -xzf /path/to/deep-agents-ui-node20-linux-x86_64.tar.gz \
  -C local_ui/.runtime/deep-agents-ui
```

Проверить runtime:

```bash
uname -m
node --version
local_ui/.runtime/deep-agents-ui/node_modules/.bin/yarn --version
local_ui/.runtime/deep-agents-ui/node_modules/.bin/next --version
```

Ожидаются Linux `x86_64`, Node.js 20, Yarn 1.22.22 и доступный Next.js.

## Запуск

Локальный доступ:

```bash
python run_ui.py
```

Доступ по hostname сервера:

```bash
python run_ui.py \
  --agent-host 0.0.0.0 \
  --agent-port 9090 \
  --ui-host 0.0.0.0 \
  --ui-port 8090
```

В браузере использовать реальный hostname, а не `0.0.0.0`. Порт LangGraph Agent
Server также должен быть доступен браузеру. При блокировке Next.js dev-ресурсов добавить
hostname в `allowedDevOrigins` файла `next.config.ts` и пересобрать архив.

## Ограничения

- Не переносить `node_modules`, созданный на Windows.
- Не запускать `npm install` или `yarn install` в закрытой среде.
- Не включать `.env`, API-ключи, токены и пароли в архив или Git.
- Не считать предупреждение Google Fonts ошибкой запуска: при отсутствии сети Next.js
  использует fallback-шрифт.
