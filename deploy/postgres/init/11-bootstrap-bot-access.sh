#!/bin/sh
set -eu

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<EOSQL
CREATE SCHEMA IF NOT EXISTS bot_access AUTHORIZATION ${POSTGRES_USER};

CREATE TABLE IF NOT EXISTS bot_access.users (
  id BIGSERIAL PRIMARY KEY,
  phone_number VARCHAR(32) NOT NULL UNIQUE,
  name TEXT,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS user_phone_equivalent_number_uidx
  ON bot_access.users ((
    CASE
      WHEN LEFT(REGEXP_REPLACE(COALESCE(phone_number, ''), '\D+', '', 'g'), 2) = '55'
      THEN CASE
        WHEN LENGTH(REGEXP_REPLACE(COALESCE(phone_number, ''), '\D+', '', 'g')) = 13
          AND SUBSTRING(REGEXP_REPLACE(COALESCE(phone_number, ''), '\D+', '', 'g'), 5, 1) = '9'
        THEN LEFT(REGEXP_REPLACE(COALESCE(phone_number, ''), '\D+', '', 'g'), 4)
          || SUBSTRING(REGEXP_REPLACE(COALESCE(phone_number, ''), '\D+', '', 'g'), 6)
        ELSE REGEXP_REPLACE(COALESCE(phone_number, ''), '\D+', '', 'g')
      END
      WHEN LENGTH(REGEXP_REPLACE(COALESCE(phone_number, ''), '\D+', '', 'g')) = 11
      THEN CASE
        WHEN SUBSTRING(REGEXP_REPLACE(COALESCE(phone_number, ''), '\D+', '', 'g'), 3, 1) = '9'
        THEN '55'
          || LEFT(REGEXP_REPLACE(COALESCE(phone_number, ''), '\D+', '', 'g'), 2)
          || SUBSTRING(REGEXP_REPLACE(COALESCE(phone_number, ''), '\D+', '', 'g'), 4)
        ELSE '55' || REGEXP_REPLACE(COALESCE(phone_number, ''), '\D+', '', 'g')
      END
      WHEN LENGTH(REGEXP_REPLACE(COALESCE(phone_number, ''), '\D+', '', 'g')) = 10
      THEN '55' || REGEXP_REPLACE(COALESCE(phone_number, ''), '\D+', '', 'g')
      ELSE REGEXP_REPLACE(COALESCE(phone_number, ''), '\D+', '', 'g')
    END
  ));

CREATE TABLE IF NOT EXISTS bot_access.roles (
  id BIGSERIAL PRIMARY KEY,
  name VARCHAR(80) NOT NULL UNIQUE,
  description TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS bot_access.permissions (
  id BIGSERIAL PRIMARY KEY,
  name VARCHAR(80) NOT NULL UNIQUE,
  description TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS bot_access.user_roles (
  user_id BIGINT NOT NULL REFERENCES bot_access.users(id) ON DELETE CASCADE,
  role_id BIGINT NOT NULL REFERENCES bot_access.roles(id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (user_id, role_id)
);

CREATE TABLE IF NOT EXISTS bot_access.role_permissions (
  role_id BIGINT NOT NULL REFERENCES bot_access.roles(id) ON DELETE CASCADE,
  permission_id BIGINT NOT NULL REFERENCES bot_access.permissions(id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (role_id, permission_id)
);

CREATE TABLE IF NOT EXISTS bot_access.user_sectors (
  user_id BIGINT NOT NULL REFERENCES bot_access.users(id) ON DELETE CASCADE,
  sector_code VARCHAR(32) NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (user_id, sector_code)
);

CREATE TABLE IF NOT EXISTS bot_access.user_gv_vdes (
  user_id BIGINT NOT NULL REFERENCES bot_access.users(id) ON DELETE CASCADE,
  gv_vde_code VARCHAR(32) NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (user_id, gv_vde_code)
);

CREATE TABLE IF NOT EXISTS bot_access.security_audit_log (
  id BIGSERIAL PRIMARY KEY,
  channel VARCHAR(40) NOT NULL,
  path TEXT NOT NULL,
  event_type VARCHAR(80) NOT NULL,
  decision VARCHAR(40) NOT NULL,
  phone_number VARCHAR(32),
  area VARCHAR(80),
  reason VARCHAR(120),
  metadata JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS bot_access.denied_reply_state (
  phone_number VARCHAR(32) PRIMARY KEY,
  last_reason VARCHAR(120) NOT NULL,
  last_reply_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS security_audit_log_created_idx
  ON bot_access.security_audit_log (created_at DESC);
CREATE INDEX IF NOT EXISTS security_audit_log_phone_idx
  ON bot_access.security_audit_log (phone_number, created_at DESC);
CREATE INDEX IF NOT EXISTS security_audit_log_path_idx
  ON bot_access.security_audit_log (channel, path, created_at DESC);
EOSQL
