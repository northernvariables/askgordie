-- Device registry: tracks all Gordie appliances, their keys, config, and location
create table if not exists devices (
    id uuid primary key default gen_random_uuid(),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),

    -- Identity
    device_id text unique not null,                -- human-readable slug: gordie-001, gordie-toronto-lib
    hardware_serial text,                          -- Pi serial from /proc/cpuinfo
    label text,                                    -- admin-friendly name: "Toronto Public Library Kiosk"

    -- Activation / API key exchange
    activation_code text unique,                   -- 8-char code shown on first boot, admin enters in panel
    activated_at timestamptz,
    status text not null default 'pending'
        check (status in ('pending', 'activated', 'suspended', 'decommissioned')),

    -- API keys — rotatable, per-device
    api_key_hash text,                             -- bcrypt hash of the device's API key
    api_key_prefix text,                           -- first 8 chars for identification: "grd_a1b2..."
    api_key_issued_at timestamptz,
    api_key_last_used_at timestamptz,

    -- Geolocation / riding
    latitude double precision,
    longitude double precision,
    address text,                                  -- human-readable: "483 Bay St, Toronto ON"
    postal_code text,                              -- used for riding lookup
    riding_name text,                              -- resolved: "University—Rosedale"
    riding_code text,                              -- Elections Canada code: "35110"
    province text,
    riding_resolved_at timestamptz,

    -- Heartbeat
    last_heartbeat_at timestamptz,
    heartbeat_data jsonb not null default '{}'::jsonb,  -- uptime, cpu_temp, recording_count, error_count, etc.

    -- Remote config (admin pushes, device pulls)
    config_override jsonb not null default '{}'::jsonb,  -- overrides for default.yaml sections
    config_version integer not null default 0,
    device_config_version integer not null default 0,    -- what the device last acknowledged

    -- Software
    software_version text,
    os_version text
);

create index idx_devices_status on devices(status);
create index idx_devices_activation on devices(activation_code) where activation_code is not null;
create index idx_devices_api_key_prefix on devices(api_key_prefix) where api_key_prefix is not null;
create index idx_devices_riding on devices(riding_code) where riding_code is not null;
create index idx_devices_heartbeat on devices(last_heartbeat_at desc);

-- Also add device_id FK to opinions table
alter table opinions
    add column if not exists device_riding_code text,
    add column if not exists device_riding_name text;

-- RLS
alter table devices enable row level security;

-- Only service role can access devices (admin panel + device API)
-- No public policies — all access via service_role key

-- Function to auto-update updated_at
create or replace function update_updated_at()
returns trigger as $$
begin
    new.updated_at = now();
    return new;
end;
$$ language plpgsql;

create trigger devices_updated_at
    before update on devices
    for each row execute function update_updated_at();
