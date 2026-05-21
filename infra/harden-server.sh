#!/usr/bin/env bash
# Server hardening for 152-ФЗ compliance.
#
# Запускается ОДИН РАЗ на проде от root:
#   curl -fsSL https://raw.githubusercontent.com/broowq/baza/main/infra/harden-server.sh | bash
# либо вручную после ssh:
#   bash /opt/baza/infra/harden-server.sh
#
# Что делает:
#   1) ufw (firewall) — закрывает всё кроме 22/80/443
#   2) Отключает парольную аутентификацию SSH (требует существующий
#      ssh-ключ в ~/.ssh/authorized_keys — иначе скрипт остановится,
#      чтобы не залочить тебя самого)
#   3) Устанавливает fail2ban против брутфорса SSH
#   4) Включает unattended-upgrades для security-патчей
#   5) Включает auto-backup Postgres каждый день в 03:00, c шифрованием,
#      хранение 30 дней. Папка /opt/baza/backups.
#   6) Закрывает zabbix-agent наружу (10050)
#
# Скрипт идемпотентен — можно гнать повторно без побочных эффектов.

set -euo pipefail

[[ $EUID -eq 0 ]] || { echo "Запускай от root"; exit 1; }

echo "==[ 1/6 ]== ufw firewall"
apt-get install -y -q ufw >/dev/null
ufw --force reset >/dev/null
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp     comment 'SSH'
ufw allow 80/tcp     comment 'HTTP redirect'
ufw allow 443/tcp    comment 'HTTPS'
# Zabbix-agent (10050) специально НЕ открываем — мониторинг от Timeweb
# работает по их внутренней сети, не наружу.
ufw --force enable
ufw status verbose

echo "==[ 2/6 ]== SSH hardening"
# Проверяем что есть авторизованный ключ — иначе залочим сами себя.
if [[ ! -s /root/.ssh/authorized_keys ]]; then
  echo
  echo "  ⚠️  У root нет ~/.ssh/authorized_keys — отключение пароля прервано."
  echo "      Сначала добавь свой публичный ключ:"
  echo "         echo 'ssh-ed25519 AAAA...' >> /root/.ssh/authorized_keys"
  echo "         chmod 600 /root/.ssh/authorized_keys"
  echo "      Затем перезапусти этот скрипт."
  echo
else
  # Backup main config
  cp /etc/ssh/sshd_config /etc/ssh/sshd_config.bak.$(date +%F)
  sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
  sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config
  sed -i 's/^#\?KbdInteractiveAuthentication.*/KbdInteractiveAuthentication no/' /etc/ssh/sshd_config

  # CRITICAL: cloud providers (Timeweb, Reg.Cloud, etc.) ship a drop-in
  # /etc/ssh/sshd_config.d/50-cloud-init.conf with `PasswordAuthentication yes`
  # that OVERRIDES the main config — the first match in the Include chain wins.
  # Editing only sshd_config silently leaves password auth ENABLED. We must
  # neutralise the cloud-init drop-in AND add our own high-priority drop-in
  # that survives future cloud-init regeneration.
  if [[ -d /etc/ssh/sshd_config.d ]]; then
    for f in /etc/ssh/sshd_config.d/*cloud-init*.conf; do
      [[ -e "$f" ]] || continue
      sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' "$f"
    done
    cat > /etc/ssh/sshd_config.d/99-baza-hardening.conf <<'SSHEOF'
# 152-ФЗ: вход только по ключу. Высший приоритет — переживает cloud-init.
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
PubkeyAuthentication yes
SSHEOF
    chmod 600 /etc/ssh/sshd_config.d/99-baza-hardening.conf
  fi

  # Validate before reload — broken config must NOT take down sshd.
  if sshd -t; then
    systemctl reload ssh 2>/dev/null || systemctl reload sshd 2>/dev/null
    EFFECTIVE=$(sshd -T 2>/dev/null | grep -i '^passwordauthentication' || echo '?')
    echo "  ✓ Парольная аутентификация SSH отключена ($EFFECTIVE)."
  else
    echo "  ⚠️  sshd config невалиден — reload пропущен, проверь вручную."
  fi
fi

echo "==[ 3/6 ]== fail2ban"
apt-get install -y -q fail2ban >/dev/null
cat > /etc/fail2ban/jail.local <<'EOF'
[DEFAULT]
bantime  = 24h
findtime = 10m
maxretry = 5
backend  = systemd

[sshd]
enabled = true
port    = ssh
filter  = sshd
logpath = /var/log/auth.log
EOF
systemctl enable --now fail2ban
fail2ban-client status sshd 2>/dev/null || true

echo "==[ 4/6 ]== unattended-upgrades"
apt-get install -y -q unattended-upgrades apt-listchanges >/dev/null
cat > /etc/apt/apt.conf.d/52unattended-upgrades-baza <<'EOF'
Unattended-Upgrade::Allowed-Origins {
    "${distro_id}:${distro_codename}-security";
    "${distro_id}ESMApps:${distro_codename}-apps-security";
    "${distro_id}ESM:${distro_codename}-infra-security";
};
Unattended-Upgrade::AutoFixInterruptedDpkg "true";
Unattended-Upgrade::MinimalSteps "true";
Unattended-Upgrade::Automatic-Reboot "false";
EOF
dpkg-reconfigure -f noninteractive unattended-upgrades

echo "==[ 5/6 ]== Postgres backups (cron)"
mkdir -p /opt/baza/backups
chmod 700 /opt/baza/backups
# Скрипт делает дамп → шифрует ChaCha20 ключом из /opt/baza/.backup_key
# (генерируется один раз) → удаляет архивы старше 30 дней.
cat > /opt/baza/backups/run-backup.sh <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
TS=$(date +%F_%H%M)
DIR=/opt/baza/backups
KEYFILE="$DIR/.backup_key"
[[ -s "$KEYFILE" ]] || { openssl rand -hex 32 > "$KEYFILE"; chmod 600 "$KEYFILE"; }
PASS=$(cat "$KEYFILE")
docker exec baza-postgres-1 pg_dump -U lead -d lead --no-owner --clean --if-exists \
  | gzip -9 \
  | openssl enc -aes-256-cbc -pbkdf2 -salt -pass "pass:$PASS" \
  > "$DIR/baza-$TS.sql.gz.enc"
# retention: 30 дней
find "$DIR" -name 'baza-*.sql.gz.enc' -mtime +30 -delete
echo "$(date -Iseconds) backup OK: $(ls -lh $DIR/baza-$TS.sql.gz.enc | awk '{print $5}')" \
  >> /var/log/baza-backup.log
EOF
chmod 750 /opt/baza/backups/run-backup.sh

# Cron на 03:00 каждый день
cat > /etc/cron.d/baza-backup <<'EOF'
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
# Postgres backup ежедневно в 03:00 МСК (00:00 UTC)
0 0 * * * root /opt/baza/backups/run-backup.sh >/dev/null 2>&1
EOF
chmod 644 /etc/cron.d/baza-backup
echo "  ✓ Бэкапы настроены — первый прогон в ближайшие 24ч."
echo "  Восстановление:"
echo "    openssl enc -d -aes-256-cbc -pbkdf2 -pass \"pass:\$(cat /opt/baza/backups/.backup_key)\" \\"
echo "      -in /opt/baza/backups/baza-XXXX.sql.gz.enc | gunzip | docker exec -i baza-postgres-1 psql -U lead -d lead"

echo "==[ 6/6 ]== Готово."
echo "Проверь:"
echo "  ufw status            — должны быть 22/80/443"
echo "  systemctl status fail2ban"
echo "  systemctl status unattended-upgrades"
echo "  ls /etc/cron.d/baza-backup"
echo
echo "💡 Сохрани файл /opt/baza/backups/.backup_key В НАДЁЖНОМ МЕСТЕ"
echo "   (например 1Password). Без него зашифрованные бэкапы прочитать нельзя."
