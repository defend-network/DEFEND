CREATE TABLE `feature_releases` (
	`id` text PRIMARY KEY NOT NULL,
	`module_key` text NOT NULL,
	`name` text NOT NULL,
	`state` text DEFAULT 'implemented' NOT NULL,
	`notes` text DEFAULT '' NOT NULL,
	`updated_by` text,
	`created_at` integer DEFAULT (cast(unixepoch('subsecond') * 1000 as integer)) NOT NULL,
	`updated_at` integer DEFAULT (cast(unixepoch('subsecond') * 1000 as integer)) NOT NULL,
	FOREIGN KEY (`updated_by`) REFERENCES `user`(`id`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE UNIQUE INDEX `feature_releases_module_key_unique` ON `feature_releases` (`module_key`);--> statement-breakpoint
CREATE INDEX `feature_releases_state_idx` ON `feature_releases` (`state`);--> statement-breakpoint
CREATE TABLE `household_members` (
	`id` text PRIMARY KEY NOT NULL,
	`household_id` text NOT NULL,
	`user_id` text NOT NULL,
	`relationship` text DEFAULT 'member' NOT NULL,
	`is_primary` integer DEFAULT false NOT NULL,
	`created_at` integer DEFAULT (cast(unixepoch('subsecond') * 1000 as integer)) NOT NULL,
	FOREIGN KEY (`household_id`) REFERENCES `households`(`id`) ON UPDATE no action ON DELETE cascade,
	FOREIGN KEY (`user_id`) REFERENCES `user`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE UNIQUE INDEX `household_members_household_user_unique` ON `household_members` (`household_id`,`user_id`);--> statement-breakpoint
CREATE INDEX `household_members_user_idx` ON `household_members` (`user_id`);--> statement-breakpoint
CREATE TABLE `households` (
	`id` text PRIMARY KEY NOT NULL,
	`name` text NOT NULL,
	`primary_contact_user_id` text,
	`chapter_id` text,
	`created_at` integer DEFAULT (cast(unixepoch('subsecond') * 1000 as integer)) NOT NULL,
	`updated_at` integer DEFAULT (cast(unixepoch('subsecond') * 1000 as integer)) NOT NULL,
	FOREIGN KEY (`primary_contact_user_id`) REFERENCES `user`(`id`) ON UPDATE no action ON DELETE no action,
	FOREIGN KEY (`chapter_id`) REFERENCES `chapters`(`id`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE TABLE `member_entitlement_overrides` (
	`id` text PRIMARY KEY NOT NULL,
	`membership_id` text NOT NULL,
	`entitlement_key` text NOT NULL,
	`enabled` integer DEFAULT true NOT NULL,
	`reason` text,
	`created_by` text,
	`expires_at` integer,
	`created_at` integer DEFAULT (cast(unixepoch('subsecond') * 1000 as integer)) NOT NULL,
	FOREIGN KEY (`membership_id`) REFERENCES `memberships`(`id`) ON UPDATE no action ON DELETE cascade,
	FOREIGN KEY (`created_by`) REFERENCES `user`(`id`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE UNIQUE INDEX `member_entitlement_overrides_member_key_unique` ON `member_entitlement_overrides` (`membership_id`,`entitlement_key`);--> statement-breakpoint
CREATE TABLE `membership_tier_prices` (
	`id` text PRIMARY KEY NOT NULL,
	`tier_id` text NOT NULL,
	`interval` text NOT NULL,
	`amount_cents` integer NOT NULL,
	`stripe_price_id` text,
	`effective_from` integer NOT NULL,
	`effective_to` integer,
	`active` integer DEFAULT true NOT NULL,
	`created_at` integer DEFAULT (cast(unixepoch('subsecond') * 1000 as integer)) NOT NULL,
	FOREIGN KEY (`tier_id`) REFERENCES `membership_tiers`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE INDEX `membership_tier_prices_tier_interval_idx` ON `membership_tier_prices` (`tier_id`,`interval`,`active`);--> statement-breakpoint
CREATE INDEX `membership_tier_prices_effective_idx` ON `membership_tier_prices` (`effective_from`);--> statement-breakpoint
CREATE TABLE `membership_tiers` (
	`id` text PRIMARY KEY NOT NULL,
	`key` text NOT NULL,
	`name` text NOT NULL,
	`description` text DEFAULT '' NOT NULL,
	`rank` integer DEFAULT 0 NOT NULL,
	`minimum_monthly_cents` integer DEFAULT 0 NOT NULL,
	`allows_custom_amount` integer DEFAULT false NOT NULL,
	`active` integer DEFAULT true NOT NULL,
	`created_at` integer DEFAULT (cast(unixepoch('subsecond') * 1000 as integer)) NOT NULL,
	`updated_at` integer DEFAULT (cast(unixepoch('subsecond') * 1000 as integer)) NOT NULL
);
--> statement-breakpoint
CREATE UNIQUE INDEX `membership_tiers_key_unique` ON `membership_tiers` (`key`);--> statement-breakpoint
CREATE TABLE `tier_entitlements` (
	`id` text PRIMARY KEY NOT NULL,
	`tier_id` text NOT NULL,
	`entitlement_key` text NOT NULL,
	`enabled` integer DEFAULT true NOT NULL,
	`created_at` integer DEFAULT (cast(unixepoch('subsecond') * 1000 as integer)) NOT NULL,
	FOREIGN KEY (`tier_id`) REFERENCES `membership_tiers`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE UNIQUE INDEX `tier_entitlements_tier_key_unique` ON `tier_entitlements` (`tier_id`,`entitlement_key`);--> statement-breakpoint
ALTER TABLE `member_profiles` ADD `household_id` text REFERENCES households(id);--> statement-breakpoint
ALTER TABLE `membership_subscriptions` ADD `tier_id` text REFERENCES membership_tiers(id);--> statement-breakpoint
ALTER TABLE `membership_subscriptions` ADD `billing_interval` text;--> statement-breakpoint
ALTER TABLE `memberships` ADD `tier_id` text REFERENCES membership_tiers(id);--> statement-breakpoint
INSERT OR IGNORE INTO membership_tiers
  (id, key, name, description, rank, minimum_monthly_cents, allows_custom_amount, active)
VALUES
  ('tier_free', 'free', 'Free', 'Announcements and eligible public events.', 0, 0, 0, 1),
  ('tier_standard', 'standard', 'Standard', 'Core paid membership.', 1, 1000, 0, 1),
  ('tier_supporter', 'supporter', 'Supporter', 'Enhanced support and configurable benefits.', 2, 2500, 0, 1),
  ('tier_patron', 'patron', 'Patron', 'Higher-level recurring support with a member-selected amount.', 3, 5000, 1, 1);--> statement-breakpoint
INSERT OR IGNORE INTO membership_tier_prices
  (id, tier_id, interval, amount_cents, stripe_price_id, effective_from, effective_to, active)
VALUES
  ('price_free_month', 'tier_free', 'month', 0, NULL, (cast(unixepoch('subsecond') * 1000 as integer)), NULL, 1),
  ('price_free_year', 'tier_free', 'year', 0, NULL, (cast(unixepoch('subsecond') * 1000 as integer)), NULL, 1),
  ('price_standard_month', 'tier_standard', 'month', 1000, NULL, (cast(unixepoch('subsecond') * 1000 as integer)), NULL, 1),
  ('price_standard_year', 'tier_standard', 'year', 10800, NULL, (cast(unixepoch('subsecond') * 1000 as integer)), NULL, 1),
  ('price_supporter_month', 'tier_supporter', 'month', 2500, NULL, (cast(unixepoch('subsecond') * 1000 as integer)), NULL, 1),
  ('price_supporter_year', 'tier_supporter', 'year', 27000, NULL, (cast(unixepoch('subsecond') * 1000 as integer)), NULL, 1),
  ('price_patron_month_min', 'tier_patron', 'month', 5000, NULL, (cast(unixepoch('subsecond') * 1000 as integer)), NULL, 1),
  ('price_patron_year_min', 'tier_patron', 'year', 54000, NULL, (cast(unixepoch('subsecond') * 1000 as integer)), NULL, 1);--> statement-breakpoint
INSERT OR IGNORE INTO tier_entitlements (id, tier_id, entitlement_key, enabled) VALUES
  ('te_free_announcements', 'tier_free', 'announcements', 1),
  ('te_free_public_events', 'tier_free', 'public_events', 1),
  ('te_standard_announcements', 'tier_standard', 'announcements', 1),
  ('te_standard_public_events', 'tier_standard', 'public_events', 1),
  ('te_standard_workshops', 'tier_standard', 'workshops', 1),
  ('te_standard_gym', 'tier_standard', 'gym', 1),
  ('te_standard_volunteering', 'tier_standard', 'volunteering', 1),
  ('te_standard_directory', 'tier_standard', 'directory', 1),
  ('te_supporter_announcements', 'tier_supporter', 'announcements', 1),
  ('te_supporter_public_events', 'tier_supporter', 'public_events', 1),
  ('te_supporter_workshops', 'tier_supporter', 'workshops', 1),
  ('te_supporter_gym', 'tier_supporter', 'gym', 1),
  ('te_supporter_volunteering', 'tier_supporter', 'volunteering', 1),
  ('te_supporter_directory', 'tier_supporter', 'directory', 1),
  ('te_supporter_benefits', 'tier_supporter', 'supporter_benefits', 1),
  ('te_patron_announcements', 'tier_patron', 'announcements', 1),
  ('te_patron_public_events', 'tier_patron', 'public_events', 1),
  ('te_patron_workshops', 'tier_patron', 'workshops', 1),
  ('te_patron_gym', 'tier_patron', 'gym', 1),
  ('te_patron_volunteering', 'tier_patron', 'volunteering', 1),
  ('te_patron_directory', 'tier_patron', 'directory', 1),
  ('te_patron_supporter_benefits', 'tier_patron', 'supporter_benefits', 1),
  ('te_patron_benefits', 'tier_patron', 'patron_benefits', 1);--> statement-breakpoint
INSERT OR IGNORE INTO feature_releases (id, module_key, name, state, notes) VALUES
  ('fr_auth', 'foundation.auth', 'Authentication and sessions', 'implemented', 'Better Auth, invitation-only activation, TOTP MFA.'),
  ('fr_audit', 'foundation.audit', 'Audit logging', 'implemented', 'Append-only audit triggers and redaction.'),
  ('fr_applications', 'membership.applications', 'Membership applications', 'implemented', 'Application queue, review, invitations, activation.'),
  ('fr_portal', 'membership.portal', 'Member portal', 'implemented', 'Dashboard, profile, card, directory, volunteers.'),
  ('fr_documents', 'documents.library', 'Document library', 'implemented', 'Upload, versioning, archive, authorized download.'),
  ('fr_events', 'events.registration', 'Event registration and check-in', 'implemented', 'Published events, registration, QR check-in.'),
  ('fr_newsletter', 'newsletter.unsubscribe', 'Newsletter unsubscribe', 'staging_validated', 'Signed unsubscribe flow verified locally and on staging.'),
  ('fr_stripe', 'payments.subscriptions', 'Membership subscriptions', 'implemented', 'Checkout, portal, and webhook code; live charging disabled.'),
  ('fr_email', 'communications.email', 'Transactional email', 'implemented', 'Development outbox; real delivery not configured.'),
  ('fr_tiers', 'membership.tiers', 'Membership tiers and pricing', 'implemented', 'Tier, price, and entitlement contracts; UI pending.'),
  ('fr_release_registry', 'platform.release_registry', 'Feature release registry', 'implemented', 'Seven-state release tracking contract.');