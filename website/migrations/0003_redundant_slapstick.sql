CREATE TABLE `application_update_tokens` (
	`id` text PRIMARY KEY NOT NULL,
	`application_id` text NOT NULL,
	`token_hash` text NOT NULL,
	`expires_at` integer NOT NULL,
	`consumed_at` integer,
	`created_by` text,
	`created_at` integer DEFAULT (cast(unixepoch('subsecond') * 1000 as integer)) NOT NULL,
	FOREIGN KEY (`application_id`) REFERENCES `membership_applications`(`id`) ON UPDATE no action ON DELETE cascade,
	FOREIGN KEY (`created_by`) REFERENCES `user`(`id`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE UNIQUE INDEX `application_update_tokens_token_hash_unique` ON `application_update_tokens` (`token_hash`);--> statement-breakpoint
CREATE INDEX `application_update_tokens_application_idx` ON `application_update_tokens` (`application_id`,`created_at`);--> statement-breakpoint
CREATE TABLE `email_delivery_events` (
	`id` text PRIMARY KEY NOT NULL,
	`recipient` text NOT NULL,
	`template_key` text NOT NULL,
	`provider` text NOT NULL,
	`provider_message_id` text,
	`status` text NOT NULL,
	`error_code` text,
	`created_at` integer DEFAULT (cast(unixepoch('subsecond') * 1000 as integer)) NOT NULL
);
--> statement-breakpoint
CREATE INDEX `email_delivery_events_created_idx` ON `email_delivery_events` (`created_at`);--> statement-breakpoint
CREATE INDEX `email_delivery_events_recipient_idx` ON `email_delivery_events` (`recipient`);--> statement-breakpoint
CREATE TABLE `email_outbox` (
	`id` text PRIMARY KEY NOT NULL,
	`recipient` text NOT NULL,
	`subject` text NOT NULL,
	`text_body` text NOT NULL,
	`html_body` text,
	`template_key` text NOT NULL,
	`created_at` integer DEFAULT (cast(unixepoch('subsecond') * 1000 as integer)) NOT NULL
);
--> statement-breakpoint
CREATE INDEX `email_outbox_created_idx` ON `email_outbox` (`created_at`);--> statement-breakpoint
CREATE TABLE `event_checkins` (
	`id` text PRIMARY KEY NOT NULL,
	`event_id` text NOT NULL,
	`user_id` text NOT NULL,
	`checked_in_at` integer DEFAULT (cast(unixepoch('subsecond') * 1000 as integer)) NOT NULL,
	`checked_in_by` text,
	`method` text DEFAULT 'qr' NOT NULL,
	FOREIGN KEY (`event_id`) REFERENCES `events`(`id`) ON UPDATE no action ON DELETE cascade,
	FOREIGN KEY (`user_id`) REFERENCES `user`(`id`) ON UPDATE no action ON DELETE cascade,
	FOREIGN KEY (`checked_in_by`) REFERENCES `user`(`id`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE UNIQUE INDEX `event_checkins_event_user_idx` ON `event_checkins` (`event_id`,`user_id`);--> statement-breakpoint
CREATE TABLE `event_registrations` (
	`id` text PRIMARY KEY NOT NULL,
	`event_id` text NOT NULL,
	`user_id` text NOT NULL,
	`status` text DEFAULT 'registered' NOT NULL,
	`created_at` integer DEFAULT (cast(unixepoch('subsecond') * 1000 as integer)) NOT NULL,
	`updated_at` integer DEFAULT (cast(unixepoch('subsecond') * 1000 as integer)) NOT NULL,
	FOREIGN KEY (`event_id`) REFERENCES `events`(`id`) ON UPDATE no action ON DELETE cascade,
	FOREIGN KEY (`user_id`) REFERENCES `user`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE UNIQUE INDEX `event_registrations_event_user_idx` ON `event_registrations` (`event_id`,`user_id`);--> statement-breakpoint
CREATE INDEX `event_registrations_event_status_idx` ON `event_registrations` (`event_id`,`status`);--> statement-breakpoint
CREATE TABLE `events` (
	`id` text PRIMARY KEY NOT NULL,
	`slug` text NOT NULL,
	`title` text NOT NULL,
	`summary` text DEFAULT '' NOT NULL,
	`description` text DEFAULT '' NOT NULL,
	`chapter_id` text,
	`starts_at` integer NOT NULL,
	`ends_at` integer,
	`location_name` text,
	`address` text,
	`capacity` integer,
	`status` text DEFAULT 'draft' NOT NULL,
	`registration_opens_at` integer,
	`registration_closes_at` integer,
	`created_by` text,
	`created_at` integer DEFAULT (cast(unixepoch('subsecond') * 1000 as integer)) NOT NULL,
	`updated_at` integer DEFAULT (cast(unixepoch('subsecond') * 1000 as integer)) NOT NULL,
	FOREIGN KEY (`chapter_id`) REFERENCES `chapters`(`id`) ON UPDATE no action ON DELETE no action,
	FOREIGN KEY (`created_by`) REFERENCES `user`(`id`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE UNIQUE INDEX `events_slug_unique` ON `events` (`slug`);--> statement-breakpoint
CREATE INDEX `events_chapter_status_idx` ON `events` (`chapter_id`,`status`);--> statement-breakpoint
CREATE INDEX `events_starts_at_idx` ON `events` (`starts_at`);--> statement-breakpoint
CREATE TABLE `request_rate_limits` (
	`key` text PRIMARY KEY NOT NULL,
	`count` integer NOT NULL,
	`window_start` integer NOT NULL,
	`expires_at` integer NOT NULL
);
--> statement-breakpoint
CREATE TABLE `volunteer_opportunities` (
	`id` text PRIMARY KEY NOT NULL,
	`chapter_id` text,
	`event_id` text,
	`title` text NOT NULL,
	`description` text DEFAULT '' NOT NULL,
	`slots` integer,
	`status` text DEFAULT 'draft' NOT NULL,
	`created_at` integer DEFAULT (cast(unixepoch('subsecond') * 1000 as integer)) NOT NULL,
	`updated_at` integer DEFAULT (cast(unixepoch('subsecond') * 1000 as integer)) NOT NULL,
	FOREIGN KEY (`chapter_id`) REFERENCES `chapters`(`id`) ON UPDATE no action ON DELETE no action,
	FOREIGN KEY (`event_id`) REFERENCES `events`(`id`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE INDEX `volunteer_opportunities_chapter_status_idx` ON `volunteer_opportunities` (`chapter_id`,`status`);--> statement-breakpoint
CREATE TABLE `volunteer_registrations` (
	`id` text PRIMARY KEY NOT NULL,
	`opportunity_id` text NOT NULL,
	`user_id` text NOT NULL,
	`status` text DEFAULT 'registered' NOT NULL,
	`created_at` integer DEFAULT (cast(unixepoch('subsecond') * 1000 as integer)) NOT NULL,
	FOREIGN KEY (`opportunity_id`) REFERENCES `volunteer_opportunities`(`id`) ON UPDATE no action ON DELETE cascade,
	FOREIGN KEY (`user_id`) REFERENCES `user`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE UNIQUE INDEX `volunteer_registrations_opportunity_user_idx` ON `volunteer_registrations` (`opportunity_id`,`user_id`);--> statement-breakpoint
PRAGMA foreign_keys=OFF;--> statement-breakpoint
CREATE TABLE `__new_rate_limit` (
	`id` text PRIMARY KEY NOT NULL,
	`key` text NOT NULL,
	`count` integer NOT NULL,
	`last_request` integer NOT NULL
);
--> statement-breakpoint
INSERT INTO `__new_rate_limit`("id", "key", "count", "last_request") SELECT "id", "key", "count", "last_request" FROM `rate_limit`;--> statement-breakpoint
DROP TABLE `rate_limit`;--> statement-breakpoint
ALTER TABLE `__new_rate_limit` RENAME TO `rate_limit`;--> statement-breakpoint
PRAGMA foreign_keys=ON;--> statement-breakpoint
CREATE UNIQUE INDEX `rate_limit_key_unique` ON `rate_limit` (`key`);--> statement-breakpoint
ALTER TABLE `member_profiles` ADD `notification_preferences_json` text DEFAULT '{}' NOT NULL;--> statement-breakpoint
ALTER TABLE `membership_applications` ADD `recommended_chapter_id` text REFERENCES chapters(id);--> statement-breakpoint
ALTER TABLE `membership_applications` ADD `info_request_encrypted` text;--> statement-breakpoint
ALTER TABLE `membership_applications` ADD `info_requested_at` integer;--> statement-breakpoint
ALTER TABLE `memberships` ADD `application_id` text REFERENCES membership_applications(id);--> statement-breakpoint
ALTER TABLE `memberships` ADD `dues_status` text DEFAULT 'not_started' NOT NULL;--> statement-breakpoint
CREATE UNIQUE INDEX `memberships_application_id_unique` ON `memberships` (`application_id`);