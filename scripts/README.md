# Scripts

## Сборка offline UI

`build_ui_archive.sh` запускается в Linux x86_64 или WSL. Скрипт берёт Linux
`node_modules` из существующего UI-архива, накладывает актуальные файлы из
`local_ui/.runtime/deep-agents-ui`, проверяет frontend через Node.js 20, после чего
обновляет:

- `deep-agents-ui-node20-linux-x86_64.tar.gz`;
- части `.part001`, `.part002`, ...;
- корневой `SHA256SUMS`.

```powershell
wsl -d Ubuntu -- bash /mnt/c/path/to/deepagent/scripts/build_ui_archive.sh
```

Локальные проверки и служебные команды проекта. Скрипты не входят в runtime
пакета `deep_agent`.
