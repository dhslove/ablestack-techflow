#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${FLARUM_APP_DIR:-/var/www/html}"
APP_USER="${FLARUM_RUN_USER:-www-data}"
BACKUP_ROOT="${TECHFLOW_UPLOAD_BACKUP_ROOT:-/var/backups/techflow-flarum}"
PHP_OVERRIDE="/etc/php/8.3/fpm/conf.d/99-techflow-upload.ini"
NGINX_OVERRIDE="/etc/nginx/conf.d/techflow-upload.conf"
FLARUM_EXTEND="${APP_DIR}/extend.php"
POLICY_EXTENDER="${APP_DIR}/techflow-upload-policy.extend.php"
PHP_UPLOAD_TMP="/var/lib/flarum-upload-tmp"
NGINX_BODY_TMP="/var/lib/nginx/techflow-body"
REGULAR_MAX_BYTES=1073741824
ARCHIVE_MAX_BYTES=10737418240
MAX_KIB=10485760

nginx_site_file() {
  if [[ -n ${TECHFLOW_NGINX_SITE_FILE:-} ]]; then
    readlink -f "$TECHFLOW_NGINX_SITE_FILE"
    return
  fi
  local candidate
  candidate=$(grep -lR 'server_name[[:space:]].*community\.ablecloud\.io' /etc/nginx/sites-enabled 2>/dev/null | head -n1)
  [[ -n $candidate ]] || { echo "Community nginx site file not found" >&2; exit 2; }
  readlink -f "$candidate"
}

require_root() {
  if [[ ${EUID} -ne 0 ]]; then
    echo "root privileges are required" >&2
    exit 2
  fi
}

settings_php() {
  runuser -u "$APP_USER" -- php -r '
    require $argv[1]."/vendor/autoload.php";
    $config = include $argv[1]."/config.php";
    $db = $config["database"];
    $dsn = "mysql:host={$db["host"]};port=".($db["port"] ?? 3306).";dbname={$db["database"]};charset=utf8mb4";
    $pdo = new PDO($dsn, $db["username"], $db["password"], [PDO::ATTR_ERRMODE => PDO::ERRMODE_EXCEPTION]);
    $prefix = $db["prefix"] ?? "";
    $mode = $argv[2];
    if ($mode === "export") {
      $stmt = $pdo->prepare("SELECT `key`,value FROM {$prefix}settings WHERE `key` IN (?,?) ORDER BY `key`");
      $stmt->execute(["fof-upload.maxFileSize", "fof-upload.mimeTypes"]);
      echo json_encode($stmt->fetchAll(PDO::FETCH_KEY_PAIR), JSON_UNESCAPED_SLASHES), PHP_EOL;
      exit;
    }
    if ($mode === "policy") {
      $values = [
        "fof-upload.maxFileSize" => "10485760",
        "fof-upload.mimeTypes" => json_encode([
          "^image\\/(jpeg|png|gif|webp|avif|bmp|tiff|svg\\+xml)$" => ["adapter" => "local", "template" => "image-preview"],
          "^text\\/(plain|csv)$" => ["adapter" => "local", "template" => "file"],
          "^application\\/(zip|x-zip-compressed|gzip|x-gzip|pdf)$" => ["adapter" => "local", "template" => "file"],
        ], JSON_UNESCAPED_SLASHES),
      ];
    } else {
      $values = json_decode(stream_get_contents(STDIN), true, 512, JSON_THROW_ON_ERROR);
    }
    $stmt = $pdo->prepare("INSERT INTO {$prefix}settings (`key`,value) VALUES (?,?) ON DUPLICATE KEY UPDATE value=VALUES(value)");
    $pdo->beginTransaction();
    foreach ($values as $key => $value) { $stmt->execute([$key, (string)$value]); }
    $pdo->commit();
  ' "$APP_DIR" "$1"
}

backup_file() {
  local source=$1 target=$2
  if [[ -e "$source" ]]; then
    cp -a "$source" "$target"
  else
    : > "${target}.absent"
  fi
}

restore_file() {
  local source=$1 target=$2
  if [[ -e "${source}.absent" ]]; then
    rm -f "$target"
  else
    install -o root -g root -m 0644 "$source" "$target"
  fi
}

verify() {
  php-fpm8.3 -t >/dev/null
  nginx -t >/dev/null
  local settings
  settings=$(settings_php export)
  SETTINGS_JSON="$settings" python3 - <<'PY'
import json, os
values = json.loads(os.environ["SETTINGS_JSON"])
assert values.get("fof-upload.maxFileSize") == "10485760", values
mime = json.loads(values["fof-upload.mimeTypes"])
joined = " ".join(mime)
for expected in ("image", "text", "zip", "gzip"):
    assert expected in joined, (expected, joined)
for blocked in ("7z", "rar", "iso", "bzip", "stuffit", "lha", "arj"):
    assert blocked not in joined, (blocked, joined)
PY
  local fpm_info
  fpm_info=$(php-fpm8.3 -i 2>/dev/null)
  grep -q '^upload_max_filesize => 10G => 10G' <<<"$fpm_info"
  grep -q '^post_max_size => 11G => 11G' <<<"$fpm_info"
  grep -q '^upload_tmp_dir => /var/lib/flarum-upload-tmp => /var/lib/flarum-upload-tmp' <<<"$fpm_info"
  nginx -T 2>&1 | grep -q 'client_max_body_size 11G;'
  php -l "$POLICY_EXTENDER" >/dev/null
  grep -q 'techflow-upload-policy.extend.php' "$FLARUM_EXTEND"
  runuser -u "$APP_USER" -- php -r '
    require $argv[1]."/vendor/autoload.php";
    require $argv[1]."/techflow-upload-policy.extend.php";
    assert(techflow_upload_limit("service.log", "text/plain") === 1073741824);
    assert(techflow_upload_limit("support.zip", "application/zip") === 10737418240);
  ' "$APP_DIR"
  curl --fail --silent --show-error --max-time 20 \
    --header 'Host: community.ablecloud.io' \
    "${TECHFLOW_COMMUNITY_VERIFY_URL:-http://127.0.0.1/}" >/dev/null
  echo "issue72_upload_policy=verified max_file_kib=${MAX_KIB}"
}

apply_policy() {
  require_root
  install -d -o root -g root -m 0700 "$BACKUP_ROOT"
  local stamp backup
  stamp=$(date -u +%Y%m%dT%H%M%SZ)
  backup="${BACKUP_ROOT}/issue72-${stamp}"
  install -d -o root -g root -m 0700 "$backup"
  settings_php export > "${backup}/settings.json"
  chmod 0600 "${backup}/settings.json"
  backup_file "$PHP_OVERRIDE" "${backup}/php-upload.ini"
  backup_file "$NGINX_OVERRIDE" "${backup}/nginx-upload.conf"
  backup_file "$FLARUM_EXTEND" "${backup}/extend.php"
  backup_file "$POLICY_EXTENDER" "${backup}/techflow-upload-policy.extend.php"
  local nginx_site
  nginx_site=$(nginx_site_file)
  backup_file "$nginx_site" "${backup}/nginx-site.conf"
  printf '%s\n' "$nginx_site" > "${backup}/nginx-site.path"

  cat > "$PHP_OVERRIDE" <<'EOF'
upload_max_filesize=10G
post_max_size=11G
max_execution_time=7200
max_input_time=7200
memory_limit=512M
max_file_uploads=5
upload_tmp_dir=/var/lib/flarum-upload-tmp
EOF
  chmod 0644 "$PHP_OVERRIDE"
  cat > "$NGINX_OVERRIDE" <<'EOF'
client_body_timeout 7200s;
fastcgi_read_timeout 7200s;
client_body_buffer_size 1m;
client_body_temp_path /var/lib/nginx/techflow-body 1 2;
EOF
  chmod 0644 "$NGINX_OVERRIDE"
  install -d -o "$APP_USER" -g "$APP_USER" -m 0700 "$PHP_UPLOAD_TMP"
  install -d -o www-data -g www-data -m 0700 "$NGINX_BODY_TMP"

  NGINX_SITE="$nginx_site" python3 - <<'PY'
import os, pathlib, re
path = pathlib.Path(os.environ["NGINX_SITE"])
text = path.read_text(encoding="utf-8")
if re.search(r"client_max_body_size\s+[^;]+;", text):
    text = re.sub(r"client_max_body_size\s+[^;]+;", "client_max_body_size 11G;", text, count=1)
else:
    text = re.sub(r"(server_name\s+[^;]+;)", r"\1\n    client_max_body_size 11G;", text, count=1)
path.write_text(text, encoding="utf-8")
PY

  cat > "$POLICY_EXTENDER" <<'PHP'
<?php

use Flarum\Extend;
use Flarum\Foundation\ValidationException;
use FoF\Upload\Events\File\WillBeUploaded;

function techflow_upload_limit(string $name, string $mime): int
{
    $name = strtolower($name);
    $archive = in_array($mime, [
        'application/zip', 'application/x-zip-compressed', 'application/gzip',
        'application/x-gzip', 'application/octet-stream',
    ], true) && preg_match('/\.(zip|gz|tgz|tar\.gz)$/', $name);

    return $archive ? 10737418240 : 1073741824;
}

return [
    (new Extend\Event())->listen(WillBeUploaded::class, function (WillBeUploaded $event): void {
        $limit = techflow_upload_limit($event->uploadedFile->getClientOriginalName(), $event->mime);
        $size = $event->uploadedFile->getSize();
        if ($size === false || $size < 1 || $size > $limit) {
            $label = $limit === 10737418240 ? '압축파일은 10GiB 이하' : '일반 파일은 1GiB 이하';
            throw new ValidationException(['upload' => "{$label}만 업로드할 수 있습니다."]);
        }
    }),
];
PHP
  chown "$APP_USER:$APP_USER" "$POLICY_EXTENDER"
  chmod 0644 "$POLICY_EXTENDER"
  POLICY_EXTENDER="$POLICY_EXTENDER" FLARUM_EXTEND="$FLARUM_EXTEND" python3 - <<'PY'
import os, pathlib
path = pathlib.Path(os.environ["FLARUM_EXTEND"])
text = path.read_text(encoding="utf-8")
marker = "techflow-upload-policy.extend.php"
if marker not in text:
    before, token, after = text.partition("return [")
    if not token:
        raise SystemExit("Flarum extend.php return array not found")
    text = before + "return array_merge(require __DIR__.'/" + marker + "', [" + after
    index = text.rfind("];" )
    if index < 0:
        raise SystemExit("Flarum extend.php closing array not found")
    text = text[:index] + "]);" + text[index + 2:]
    path.write_text(text, encoding="utf-8")
PY
  chown "$APP_USER:$APP_USER" "$FLARUM_EXTEND"

  settings_php policy </dev/null
  (cd "$APP_DIR" && runuser -u "$APP_USER" -- php flarum cache:clear)
  systemctl reload php8.3-fpm
  systemctl reload nginx
  verify
  echo "issue72_backup=${backup}"
}

rollback() {
  require_root
  local backup=${1:?rollback requires a backup directory}
  [[ "$backup" == "$BACKUP_ROOT"/issue72-* && -d "$backup" ]] || {
    echo "invalid Issue #72 backup path" >&2
    exit 2
  }
  restore_file "${backup}/php-upload.ini" "$PHP_OVERRIDE"
  restore_file "${backup}/nginx-upload.conf" "$NGINX_OVERRIDE"
  restore_file "${backup}/extend.php" "$FLARUM_EXTEND"
  restore_file "${backup}/techflow-upload-policy.extend.php" "$POLICY_EXTENDER"
  local nginx_site
  nginx_site=$(cat "${backup}/nginx-site.path")
  restore_file "${backup}/nginx-site.conf" "$nginx_site"
  settings_php import < "${backup}/settings.json"
  (cd "$APP_DIR" && runuser -u "$APP_USER" -- php flarum cache:clear)
  php-fpm8.3 -t >/dev/null
  nginx -t >/dev/null
  systemctl reload php8.3-fpm
  systemctl reload nginx
  echo "issue72_upload_policy=rolled_back backup=${backup}"
}

case "${1:-}" in
  apply) apply_policy ;;
  verify) verify ;;
  rollback) rollback "${2:-}" ;;
  *) echo "usage: $0 {apply|verify|rollback BACKUP_DIR}" >&2; exit 2 ;;
esac
