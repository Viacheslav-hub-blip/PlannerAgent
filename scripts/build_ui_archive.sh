#!/usr/bin/env bash
#
# Собирает offline-архив Deep Agents UI для Linux x86_64 и Node.js 20.
#
# Функции:
# - require_file: проверяет наличие обязательного файла;
# - download_node: загружает и проверяет закреплённый Node.js;
# - prepare_frontend: создаёт Linux staging-каталог с актуальными исходниками;
# - validate_frontend: запускает production build и ESLint;
# - create_archive: создаёт воспроизводимый tar.gz, части и SHA256SUMS;
# - main: выполняет полный цикл сборки.

set -euo pipefail

ARCHIVE_NAME="deep-agents-ui-node20-linux-x86_64.tar.gz"
NODE_VERSION="v20.19.4"
PART_SIZE="90m"
SOURCE_DATE_EPOCH="1781452800"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
FRONTEND_ROOT="${PROJECT_ROOT}/local_ui/.runtime/deep-agents-ui"
SEED_ARCHIVE="${PROJECT_ROOT}/${ARCHIVE_NAME}"
BUILD_ROOT="${TMPDIR:-/tmp}/deepagent-ui-build"
NODE_ROOT="${TMPDIR:-/tmp}/deepagent-node20"
OUTPUT_ROOT="${TMPDIR:-/tmp}/deepagent-ui-output"

require_file() {
    # Проверяет наличие обязательного файла.
    #
    # Args:
    #   $1: путь к обязательному файлу.
    #
    # Returns:
    #   0, если файл существует; иначе завершает скрипт.
    local path="$1"
    if [[ ! -f "${path}" ]]; then
        printf 'Не найден обязательный файл: %s\n' "${path}" >&2
        exit 1
    fi
}

download_node() {
    # Загружает официальный Node.js 20 и проверяет SHA256.
    #
    # Returns:
    #   None. Node.js распаковывается в NODE_ROOT.
    local archive="node-${NODE_VERSION}-linux-x64.tar.xz"
    local download_root="${TMPDIR:-/tmp}/deepagent-node-download"

    rm -rf "${NODE_ROOT}" "${download_root}"
    mkdir -p "${NODE_ROOT}" "${download_root}"
    (
        cd "${download_root}"
        curl -fsSLO "https://nodejs.org/dist/${NODE_VERSION}/${archive}"
        curl -fsSLO "https://nodejs.org/dist/${NODE_VERSION}/SHASUMS256.txt"
        grep " ${archive}\$" SHASUMS256.txt | sha256sum -c -
        tar -xJf "${archive}" -C "${NODE_ROOT}" --strip-components=1
    )
    rm -rf "${download_root}"
}

prepare_frontend() {
    # Создаёт Linux staging-каталог с актуальными исходниками frontend.
    #
    # Returns:
    #   None. Результат находится в BUILD_ROOT.
    require_file "${SEED_ARCHIVE}"
    require_file "${FRONTEND_ROOT}/package.json"

    rm -rf "${BUILD_ROOT}"
    mkdir -p "${BUILD_ROOT}"
    tar -xzf "${SEED_ARCHIVE}" -C "${BUILD_ROOT}"

    rsync -a --delete \
        --exclude='.git/' \
        --exclude='.next/' \
        --exclude='node_modules/' \
        --exclude='.env.local' \
        --exclude='tsconfig.tsbuildinfo' \
        "${FRONTEND_ROOT}/" "${BUILD_ROOT}/"

    rm -rf \
        "${BUILD_ROOT}/.git" \
        "${BUILD_ROOT}/.next" \
        "${BUILD_ROOT}/.env.local" \
        "${BUILD_ROOT}/tsconfig.tsbuildinfo"
}

validate_frontend() {
    # Проверяет frontend production-сборкой и ESLint на Node.js 20.
    #
    # Returns:
    #   None. Любая ошибка завершает скрипт.
    local node="${NODE_ROOT}/bin/node"

    "${node}" --version
    (
        cd "${BUILD_ROOT}"
        export PATH="${NODE_ROOT}/bin:${PATH}"
        NEXT_TELEMETRY_DISABLED=1 "${node}" node_modules/next/dist/bin/next build
        NEXT_TELEMETRY_DISABLED=1 "${node}" node_modules/eslint/bin/eslint.js .
    )
    rm -rf \
        "${BUILD_ROOT}/.next" \
        "${BUILD_ROOT}/.env.local" \
        "${BUILD_ROOT}/tsconfig.tsbuildinfo"
}

create_archive() {
    # Создаёт tar.gz, части по 90 MiB и файл SHA256SUMS.
    #
    # Returns:
    #   None. Артефакты копируются в корень проекта.
    rm -rf "${OUTPUT_ROOT}"
    mkdir -p "${OUTPUT_ROOT}"

    (
        cd "${BUILD_ROOT}"
        tar \
            --sort=name \
            --mtime="@${SOURCE_DATE_EPOCH}" \
            --owner=0 \
            --group=0 \
            --numeric-owner \
            -cf - . |
            gzip -9n >"${OUTPUT_ROOT}/${ARCHIVE_NAME}"
    )

    split \
        --bytes="${PART_SIZE}" \
        --numeric-suffixes=1 \
        --suffix-length=3 \
        "${OUTPUT_ROOT}/${ARCHIVE_NAME}" \
        "${OUTPUT_ROOT}/${ARCHIVE_NAME}.part"

    (
        cd "${OUTPUT_ROOT}"
        sha256sum "${ARCHIVE_NAME}" >SHA256SUMS
    )

    rm -f \
        "${PROJECT_ROOT}/${ARCHIVE_NAME}" \
        "${PROJECT_ROOT}/${ARCHIVE_NAME}.part"??? \
        "${PROJECT_ROOT}/SHA256SUMS"
    cp "${OUTPUT_ROOT}/${ARCHIVE_NAME}" "${PROJECT_ROOT}/${ARCHIVE_NAME}"
    cp "${OUTPUT_ROOT}/${ARCHIVE_NAME}.part"??? "${PROJECT_ROOT}/"
    cp "${OUTPUT_ROOT}/SHA256SUMS" "${PROJECT_ROOT}/SHA256SUMS"
}

main() {
    # Выполняет полный цикл сборки и печатает итоговые контрольные суммы.
    #
    # Returns:
    #   0 при успешной сборке.
    prepare_frontend
    download_node
    validate_frontend
    create_archive

    printf 'Архив собран: %s\n' "${PROJECT_ROOT}/${ARCHIVE_NAME}"
    cat "${PROJECT_ROOT}/SHA256SUMS"
    ls -lh "${PROJECT_ROOT}/${ARCHIVE_NAME}" "${PROJECT_ROOT}/${ARCHIVE_NAME}.part"???
}

main "$@"
