-- Payment configuration per device (admin-managed)
create table if not exists payment_configs (
    id uuid primary key default gen_random_uuid(),
    device_id text not null references devices(device_id) on delete cascade,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),

    -- Square credentials (per-device, per-merchant)
    square_access_token_encrypted text,     -- encrypted at rest
    square_location_id text,
    square_device_id text,                  -- paired Square Reader device ID
    square_environment text not null default 'sandbox'
        check (square_environment in ('sandbox', 'production')),

    -- Recording fee (Speaker's Corner mode)
    recording_fee_enabled boolean not null default false,
    recording_fee_cents integer not null default 100,        -- $1.00 default (the loonie!)
    recording_fee_currency text not null default 'CAD',
    recording_fee_description text not null default 'Record your opinion — 30 seconds',

    -- Donations
    donation_enabled boolean not null default false,
    donation_preset_amounts_cents jsonb not null default '[200, 500, 1000, 2000]'::jsonb,  -- $2, $5, $10, $20
    donation_custom_amount boolean not null default true,
    donation_min_cents integer not null default 100,
    donation_max_cents integer not null default 50000,
    donation_recipient_name text not null default 'CanadaGPT',
    donation_charity_number text,            -- CRA charity registration number
    donation_tax_receipt boolean not null default false,

    -- Commerce (selling items — merch, books, etc.)
    commerce_enabled boolean not null default false,
    commerce_catalog jsonb not null default '[]'::jsonb,
    -- catalog format: [{"id": "sticker-01", "name": "CanadaGPT Sticker", "price_cents": 500, "image": "..."}]

    unique(device_id)
);

create trigger payment_configs_updated_at
    before update on payment_configs
    for each row execute function update_updated_at();

-- Payment transaction log
create table if not exists payments (
    id uuid primary key default gen_random_uuid(),
    created_at timestamptz not null default now(),

    -- Context
    device_id text not null,
    user_id uuid references auth.users(id) on delete set null,
    riding_code text,

    -- Payment type
    payment_type text not null
        check (payment_type in ('recording_fee', 'donation', 'commerce')),

    -- Amount
    amount_cents integer not null,
    currency text not null default 'CAD',
    tip_cents integer not null default 0,

    -- Square
    square_payment_id text,
    square_order_id text,
    square_receipt_url text,

    -- Status
    status text not null default 'pending'
        check (status in ('pending', 'completed', 'failed', 'refunded', 'cancelled')),
    failure_reason text,

    -- Commerce details (if applicable)
    commerce_items jsonb,   -- [{"id": "sticker-01", "qty": 1, "price_cents": 500}]

    -- Donation details
    donation_receipt_sent boolean not null default false,
    donor_email text,

    -- Link to opinion recording (if recording_fee)
    opinion_id uuid references opinions(id) on delete set null
);

create index idx_payments_device on payments(device_id);
create index idx_payments_type on payments(payment_type);
create index idx_payments_status on payments(status);
create index idx_payments_created on payments(created_at desc);
create index idx_payments_square on payments(square_payment_id) where square_payment_id is not null;

alter table payments enable row level security;

-- RLS on payment_configs — service role only (contains Square tokens)
alter table payment_configs enable row level security;
-- No public policies — all access requires service_role key

-- Users can see their own payments
create policy "Users can view own payments"
    on payments for select
    using (auth.uid() = user_id);
