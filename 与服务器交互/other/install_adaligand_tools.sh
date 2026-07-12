#!/usr/bin/env bash
# AdaLigand 外部工具幂等安装：仅写 penghongen 用户目录和已授权的项目 Conda 环境。
# Chimera 下载遵循用户已确认的非商业许可；下载后同时核对官方 size 与 MD5。
set -euo pipefail

PYTHON=/home/penghongen/anaconda3/envs/AdaLigand_stage1_py310/bin/python
OPT_ROOT=/home/penghongen/.local/opt
DOWNLOAD_ROOT=${OPT_ROOT}/downloads
CHIMERA_ROOT=${OPT_ROOT}/UCSF-Chimera64-1.19
CHIMERA_BIN=${CHIMERA_ROOT}/bin/chimera
CHIMERA_INSTALLER=${DOWNLOAD_ROOT}/chimera-1.19-linux_x86_64_osmesa.bin
CHIMERA_EXPECTED_SIZE=149448194
CHIMERA_EXPECTED_MD5=aace74cbbbb3dfc5acc7d88b2851ae44
CHIMERA_LICENSE_ENDPOINT=https://www.cgl.ucsf.edu/chimera/cgi-bin/secure/chimera-get.py
CHIMERA_REMOTE_FILE=linux_x86_64_osmesa/chimera-1.19-linux_x86_64_osmesa.bin

MAPQ_COMMIT=c3bdf305677f5f9fc4b69aa404b834d9d3a75937
MAPQ_ROOT=${OPT_ROOT}/mapq-2.9.7-c3bdf305
MAPQ_ZIP=${DOWNLOAD_ROOT}/mapq_v2.9.7.zip
MAPQ_ZIP_URL=https://raw.githubusercontent.com/gregdp/mapq/${MAPQ_COMMIT}/download/mapq_v2.9.7.zip
MAPQ_EXPECTED_SHA256=ee004e19f0ca2bf1f439365d64b8463d2e8bd18c8827c28e9b2ccfe3a538fe55
MAPQ_CMD=${MAPQ_ROOT}/mapq/mapq_cmd.py
MANIFEST=${OPT_ROOT}/adaligand_tools_manifest.json

if [ "$(id -un)" != penghongen ]; then
    echo "[ConfigError] expected user penghongen, got $(id -un)" >&2
    exit 64
fi
for command_name in curl unzip md5sum sha256sum sed grep mktemp; do
    command -v "${command_name}" >/dev/null 2>&1 || {
        echo "[ConfigError] missing command: ${command_name}" >&2
        exit 64
    }
done
test -x "${PYTHON}"
mkdir -p "${DOWNLOAD_ROOT}"

valid_chimera_installer() {
    [ -f "${CHIMERA_INSTALLER}" ] || return 1
    [ "$(wc -c <"${CHIMERA_INSTALLER}")" -eq "${CHIMERA_EXPECTED_SIZE}" ] || return 1
    [ "$(md5sum "${CHIMERA_INSTALLER}" | awk '{print $1}')" = "${CHIMERA_EXPECTED_MD5}" ]
}

download_chimera_installer() {
    if valid_chimera_installer; then
        echo "[Skip] verified Chimera installer already exists"
        return
    fi
    local notice_file cookie_file temporary_file download_path download_url
    notice_file=$(mktemp "${DOWNLOAD_ROOT}/chimera-license.XXXXXX.html")
    cookie_file=$(mktemp "${DOWNLOAD_ROOT}/chimera-cookie.XXXXXX.txt")
    temporary_file=$(mktemp "${DOWNLOAD_ROOT}/chimera-download.XXXXXX.bin")
    trap 'rm -f -- "${notice_file:-}" "${cookie_file:-}" "${temporary_file:-}"' RETURN
    curl --fail --silent --show-error --retry 3 --retry-delay 2 \
        --cookie-jar "${cookie_file}" \
        --data-urlencode "file=${CHIMERA_REMOTE_FILE}" \
        --data-urlencode 'choice=Accept' \
        --output "${notice_file}" \
        "${CHIMERA_LICENSE_ENDPOINT}"
    download_path=$(
        sed -n 's/.*content="[0-9][0-9]*;url=\([^"]*\)".*/\1/p' "${notice_file}" \
            | head -n 1 \
            | sed 's/&amp;/\&/g'
    )
    if [ -z "${download_path}" ]; then
        echo '[DownloadError] Chimera temporary download URL was not present' >&2
        exit 65
    fi
    case "${download_path}" in
        https://*) download_url=${download_path} ;;
        /*) download_url="https://www.cgl.ucsf.edu${download_path}" ;;
        *) echo "[DownloadError] unexpected Chimera URL: ${download_path}" >&2; exit 65 ;;
    esac
    curl --fail --location --silent --show-error --retry 3 --retry-delay 2 \
        --cookie "${cookie_file}" \
        --output "${temporary_file}" \
        "${download_url}"
    if [ "$(wc -c <"${temporary_file}")" -ne "${CHIMERA_EXPECTED_SIZE}" ]; then
        echo '[ChecksumError] Chimera installer size mismatch' >&2
        exit 66
    fi
    if [ "$(md5sum "${temporary_file}" | awk '{print $1}')" != "${CHIMERA_EXPECTED_MD5}" ]; then
        echo '[ChecksumError] Chimera installer MD5 mismatch' >&2
        exit 66
    fi
    chmod 700 "${temporary_file}"
    mv -f -- "${temporary_file}" "${CHIMERA_INSTALLER}"
    chmod 700 "${CHIMERA_INSTALLER}"
    trap - RETURN
    rm -f -- "${notice_file}" "${cookie_file}"
    echo "[InstalledInput] Chimera installer verified at ${CHIMERA_INSTALLER}"
}

install_chimera() {
    if [ -x "${CHIMERA_BIN}" ]; then
        echo "[Skip] Chimera executable already exists"
        return
    fi
    if [ -e "${CHIMERA_ROOT}" ] && [ -n "$(find "${CHIMERA_ROOT}" -mindepth 1 -print -quit)" ]; then
        echo "[SafetyError] non-empty incomplete Chimera root requires inspection: ${CHIMERA_ROOT}" >&2
        exit 67
    fi
    mkdir -p "$(dirname "${CHIMERA_ROOT}")"
    chmod 700 "${CHIMERA_INSTALLER}"
    # 内部安装器依次询问：安装位置、是否创建命令链接；外层最后读取一次回车。
    printf '%s\n0\n\n' "${CHIMERA_ROOT}" | "${CHIMERA_INSTALLER}"
    test -x "${CHIMERA_BIN}"
    echo "[Installed] Chimera root=${CHIMERA_ROOT}"
}

install_mapq() {
    if [ ! -f "${MAPQ_ZIP}" ] || [ "$(sha256sum "${MAPQ_ZIP}" | awk '{print $1}')" != "${MAPQ_EXPECTED_SHA256}" ]; then
        local temporary_zip
        temporary_zip=$(mktemp "${DOWNLOAD_ROOT}/mapq-download.XXXXXX.zip")
        trap 'rm -f -- "${temporary_zip:-}"' RETURN
        curl --fail --location --silent --show-error --retry 3 --retry-delay 2 \
            --output "${temporary_zip}" "${MAPQ_ZIP_URL}"
        if [ "$(sha256sum "${temporary_zip}" | awk '{print $1}')" != "${MAPQ_EXPECTED_SHA256}" ]; then
            echo '[ChecksumError] MapQ zip SHA-256 mismatch' >&2
            exit 66
        fi
        mv -f -- "${temporary_zip}" "${MAPQ_ZIP}"
        trap - RETURN
    fi

    if [ ! -f "${MAPQ_CMD}" ]; then
        local temporary_root
        temporary_root=$(mktemp -d "${OPT_ROOT}/mapq-extract.XXXXXX")
        trap 'rm -rf -- "${temporary_root:-}"' RETURN
        unzip -q "${MAPQ_ZIP}" -d "${temporary_root}"
        test -f "${temporary_root}/mapq/mapq_cmd.py"
        if [ -e "${MAPQ_ROOT}" ]; then
            echo "[SafetyError] incomplete MapQ root requires inspection: ${MAPQ_ROOT}" >&2
            exit 67
        fi
        mv -- "${temporary_root}" "${MAPQ_ROOT}"
        trap - RETURN
    fi

    # 官方 install.py 把插件注册进当前 Chimera 的 share/mapq；其返回码不可靠，随后强校验。
    if [ ! -f "${CHIMERA_ROOT}/share/mapq/mapq_cmd.py" ] || \
        [ "$(sha256sum "${CHIMERA_ROOT}/share/mapq/mapq_cmd.py" | awk '{print $1}')" != \
          "$(sha256sum "${MAPQ_CMD}" | awk '{print $1}')" ]; then
        (
            cd "${MAPQ_ROOT}/mapq"
            "${PYTHON}" install.py "${CHIMERA_ROOT}"
        )
    else
        echo '[Skip] matching MapQ plugin is already registered in Chimera'
    fi
    test -f "${CHIMERA_ROOT}/share/mapq/qscores.py"
    test "$(sha256sum "${CHIMERA_ROOT}/share/mapq/mapq_cmd.py" | awk '{print $1}')" = \
        "$(sha256sum "${MAPQ_CMD}" | awk '{print $1}')"
    echo "[Installed] MapQ source=${MAPQ_ROOT} plugin=${CHIMERA_ROOT}/share/mapq"
}

install_python_dependency() {
    if "${PYTHON}" -c 'import mrcfile; raise SystemExit(0 if mrcfile.__version__ == "1.5.4" else 1)' \
        >/dev/null 2>&1; then
        echo '[Skip] mrcfile==1.5.4 already installed'
        return
    fi
    "${PYTHON}" -m pip install --disable-pip-version-check --no-deps 'mrcfile==1.5.4'
    "${PYTHON}" -c 'import mrcfile; assert mrcfile.__version__ == "1.5.4"'
}

verify_tools() {
    local probe_dir probe_script chimera_version mapq_banner
    probe_dir=$(mktemp -d "${OPT_ROOT}/adaligand-tool-probe.XXXXXX")
    trap 'rm -rf -- "${probe_dir:-}"' RETURN
    probe_script=${probe_dir}/probe_mapq.py
    printf '%s\n' \
        'from mapq import qscores' \
        'from mapq import mmcif' \
        'print("ADALIGAND_MAPQ_IMPORT_OK")' \
        'from chimera import runCommand as rc' \
        'rc("stop now")' >"${probe_script}"
    chimera_version=$("${CHIMERA_BIN}" --version 2>&1)
    chimera_version=${chimera_version%%$'\n'*}
    "${CHIMERA_BIN}" --nogui --silent --script "${probe_script}" \
        >"${probe_dir}/mapq_import.stdout.log" 2>"${probe_dir}/mapq_import.stderr.log"
    grep -F 'ADALIGAND_MAPQ_IMPORT_OK' "${probe_dir}/mapq_import.stdout.log" >/dev/null
    mapq_banner=$(
        "${PYTHON}" "${MAPQ_CMD}" --version 2>&1 \
            | grep -i 'MapQ Version' \
            | sed -n '1p'
    )
    printf '[Verified] %s\n[Verified] %s\n' "${chimera_version}" "${mapq_banner}"

    CHIMERA_VERSION=${chimera_version} MAPQ_BANNER=${mapq_banner} \
    CHIMERA_INSTALLER_SHA256=$(sha256sum "${CHIMERA_INSTALLER}" | awk '{print $1}') \
    MAPQ_CMD_SHA256=$(sha256sum "${MAPQ_CMD}" | awk '{print $1}') \
    "${PYTHON}" - "${MANIFEST}" <<'PY'
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

path = Path(sys.argv[1])
payload = {
    "installed_at": datetime.now(timezone.utc).isoformat(),
    "chimera": {
        "root": "/home/penghongen/.local/opt/UCSF-Chimera64-1.19",
        "version": os.environ["CHIMERA_VERSION"],
        "installer_size": 149448194,
        "installer_md5": "aace74cbbbb3dfc5acc7d88b2851ae44",
        "installer_sha256": os.environ["CHIMERA_INSTALLER_SHA256"],
        "license_scope": "user-confirmed noncommercial project use",
    },
    "mapq": {
        "root": "/home/penghongen/.local/opt/mapq-2.9.7-c3bdf305",
        "commit": "c3bdf305677f5f9fc4b69aa404b834d9d3a75937",
        "zip_sha256": "ee004e19f0ca2bf1f439365d64b8463d2e8bd18c8827c28e9b2ccfe3a538fe55",
        "mapq_cmd_sha256": os.environ["MAPQ_CMD_SHA256"],
        "cli_banner": os.environ["MAPQ_BANNER"],
        "plugin_import_verified": True,
    },
    "python": {
        "executable": "/home/penghongen/anaconda3/envs/AdaLigand_stage1_py310/bin/python",
        "mrcfile": "1.5.4",
    },
}
temporary = path.with_name(path.name + ".tmp")
temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
temporary.replace(path)
PY
    trap - RETURN
    rm -rf -- "${probe_dir}"
    echo "[Manifest] ${MANIFEST}"
}

download_chimera_installer
install_chimera
install_mapq
install_python_dependency
verify_tools
