#!/usr/bin/env bash
set -euo pipefail

repository="${1:-https://github.com/Gideon-sam/MULTI-CHANNEL-LEAD-GENERATION-AND-OUTREACH-ENGINE.git}"
branch="${2:-main}"
checkout="/opt/incubrix-growth-engine"
web_root="/var/www/incubrix"

if [[ -d "${checkout}/.git" ]]; then
  sudo git -C "${checkout}" fetch --prune origin "${branch}"
  sudo git -C "${checkout}" checkout "${branch}"
  sudo git -C "${checkout}" pull --ff-only origin "${branch}"
else
  if [[ -e "${checkout}" ]]; then
    printf 'Refusing to replace existing non-Git path: %s\n' "${checkout}" >&2
    exit 1
  fi
  sudo git clone --branch "${branch}" --single-branch "${repository}" "${checkout}"
fi

deploy_python="${checkout}/.deploy-venv/bin/python"
if [[ ! -x "${deploy_python}" ]]; then
  sudo python3 -m venv "${checkout}/.deploy-venv"
fi
sudo "${deploy_python}" -m pip install --quiet --disable-pip-version-check -r "${checkout}/requirements.lock"
sudo "${deploy_python}" -m pip install --quiet --disable-pip-version-check --no-deps "${checkout}"
sudo "${deploy_python}" -m incubrix_engine.public_directory \
  --workbook "${checkout}/IncuBrix_Manual_Review_5000_USER_ATTESTED.xlsx" \
  --out "${checkout}/.published/creators/data"

sudo install -d -m 0755 "${web_root}"
sudo cp -a "${checkout}/.published/." "${web_root}/"
sudo cp -a "${checkout}/deploy/public/." "${web_root}/"
sudo chown -R root:root "${web_root}"
sudo find "${web_root}" -type d -exec chmod 0755 {} +
sudo find "${web_root}" -type f -exec chmod 0644 {} +

sudo install -m 0644 "${checkout}/deploy/nginx/incubrix.conf" /etc/nginx/sites-available/incubrix
sudo ln -sfn /etc/nginx/sites-available/incubrix /etc/nginx/sites-enabled/incubrix
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl enable --now nginx
sudo systemctl reload nginx

revision="$(sudo git -C "${checkout}" rev-parse --short HEAD)"
printf 'Deployed %s at http://incubrix-outreach-engine.eastasia.cloudapp.azure.com/creators/\n' "${revision}"
