-- Queue system for Gordie devices
create table if not exists queue_entries (
    id uuid primary key default gen_random_uuid(),
    created_at timestamptz not null default now(),

    -- Device this queue is for
    device_id text not null,

    -- User info (collected on QR scan / join)
    display_name text,
    postal_code text,
    riding_name text,
    riding_code text,
    phone text,                          -- optional, for SMS notification
    user_id uuid references auth.users(id) on delete set null,

    -- Queue position
    ticket_number integer not null,       -- sequential per device per day
    status text not null default 'waiting'
        check (status in ('waiting', 'now_serving', 'completed', 'no_show', 'cancelled')),

    -- Timing
    called_at timestamptz,               -- when "now serving" was triggered
    completed_at timestamptz,
    estimated_wait_minutes integer
);

create index idx_queue_device_status on queue_entries(device_id, status);
create index idx_queue_device_ticket on queue_entries(device_id, ticket_number);
create index idx_queue_created on queue_entries(created_at desc);

alter table queue_entries enable row level security;

-- Users can see their own queue entry
create policy "Users can view own queue entries"
    on queue_entries for select
    using (auth.uid() = user_id);

-- Add postal_code to opinions for riding context
alter table opinions add column if not exists postal_code text;
alter table opinions add column if not exists riding_name text;
