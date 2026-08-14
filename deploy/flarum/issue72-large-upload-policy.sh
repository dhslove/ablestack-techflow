#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${FLARUM_APP_DIR:-/var/www/html}"
APP_USER="${FLARUM_RUN_USER:-www-data}"
BACKUP_ROOT="${TECHFLOW_UPLOAD_BACKUP_ROOT:-/var/backups/techflow-flarum}"
PHP_OVERRIDE="/etc/php/8.3/fpm/conf.d/99-techflow-upload.ini"
NGINX_OVERRIDE="/etc/nginx/conf.d/techflow-upload.conf"
MAX_KIB=51200

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
        "fof-upload.maxFileSize" => "51200",
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
assert values.get("fof-upload.maxFileSize") == "51200", values
mime = json.loads(values["fof-upload.mimeTypes"])
joined = " ".join(mime)
for expected in ("image", "text", "zip", "gzip"):
    assert expected in joined, (expected, joined)
for blocked in ("7z", "rar", "iso", "bzip", "stuffit", "lha", "arj"):
    assert blocked not in joined, (blocked, joined)
PY
  local fpm_info
  fpm_info=$(php-fpm8.3 -i 2>/dev/null)
  grep -q '^upload_max_filesize => 64M => 64M' <<<"$fpm_info"
  grep -q '^post_max_size => 64M => 64M' <<<"$fpm_info"
  curl --fail --silent --show-error --max-time 20 \
    "${TECHFLOW_COMMUNITY_VERIFY_URL:-https://community.ablecloud.io/}" >/dev/null
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

  cat > "$PHP_OVERRIDE" <<'EOF'
upload_max_filesize=64M
post_max_size=64M
max_execution_time=300
max_input_time=300
memory_limit=256M
EOF
  chmod 0644 "$PHP_OVERRIDE"
  cat > "$NGINX_OVERRIDE" <<'EOF'
client_body_timeout 300s;
fastcgi_read_timeout 300s;
EOF
  chmod 0644 "$NGINX_OVERRIDE"

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
