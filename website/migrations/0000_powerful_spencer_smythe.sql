CREATE TABLE `account` (
	`id` text PRIMARY KEY NOT NULL,
	`account_id` text NOT NULL,
	`provider_id` text NOT NULL,
	`user_id` text NOT NULL,
	`access_token` text,
	`refresh_token` text,
	`id_token` text,
	`access_token_expires_at` integer,
	`refresh_token_expires_at` integer,
	`scope` text,
	`password` text,
	`created_at` integer DEFAULT (cast(unixepoch('subsecond') * 1000 as integer)) NOT NULL,
	`updated_at` integer DEFAULT (cast(unixepoch('subsecond') * 1000 as integer)) NOT NULL,
	FOREIGN KEY (`user_id`) REFERENCES `user`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE INDEX `account_user_id_idx` ON `account` (`user_id`);--> statement-breakpoint
CREATE UNIQUE INDEX `account_provider_account_idx` ON `account` (`provider_id`,`account_id`);--> statement-breakpoint
CREATE TABLE `rate_limit` (
	`key` text PRIMARY KEY NOT NULL,
	`count` integer NOT NULL,
	`last_request` integer NOT NULL
);
--> statement-breakpoint
CREATE TABLE `session` (
	`id` text PRIMARY KEY NOT NULL,
	`expires_at` integer NOT NULL,
	`token` text NOT NULL,
	`created_at` integer DEFAULT (cast(unixepoch('subsecond') * 1000 as integer)) NOT NULL,
	`updated_at` integer DEFAULT (cast(unixepoch('subsecond') * 1000 as integer)) NOT NULL,
	`ip_address` text,
	`user_agent` text,
	`user_id` text NOT NULL,
	FOREIGN KEY (`user_id`) REFERENCES `user`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE UNIQUE INDEX `session_token_unique` ON `session` (`token`);--> statement-breakpoint
CREATE INDEX `session_user_id_idx` ON `session` (`user_id`);--> statement-breakpoint
CREATE TABLE `two_factor` (
	`id` text PRIMARY KEY NOT NULL,
	`secret` text NOT NULL,
	`backup_codes` text NOT NULL,
	`user_id` text NOT NULL,
	`verified` integer DEFAULT true,
	`failed_verification_count` integer DEFAULT 0,
	`locked_until` integer,
	FOREIGN KEY (`user_id`) REFERENCES `user`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE INDEX `two_factor_secret_idx` ON `two_factor` (`secret`);--> statement-breakpoint
CREATE INDEX `two_factor_user_id_idx` ON `two_factor` (`user_id`);--> statement-breakpoint
CREATE TABLE `user` (
	`id` text PRIMARY KEY NOT NULL,
	`name` text NOT NULL,
	`email` text NOT NULL,
	`email_verified` integer DEFAULT false NOT NULL,
	`image` text,
	`created_at` integer DEFAULT (cast(unixepoch('subsecond') * 1000 as integer)) NOT NULL,
	`updated_at` integer DEFAULT (cast(unixepoch('subsecond') * 1000 as integer)) NOT NULL,
	`two_factor_enabled` integer DEFAULT false
);
--> statement-breakpoint
CREATE UNIQUE INDEX `user_email_unique` ON `user` (`email`);--> statement-breakpoint
CREATE TABLE `verification` (
	`id` text PRIMARY KEY NOT NULL,
	`identifier` text NOT NULL,
	`value` text NOT NULL,
	`expires_at` integer NOT NULL,
	`created_at` integer DEFAULT (cast(unixepoch('subsecond') * 1000 as integer)) NOT NULL,
	`updated_at` integer DEFAULT (cast(unixepoch('subsecond') * 1000 as integer)) NOT NULL
);
--> statement-breakpoint
CREATE INDEX `verification_identifier_idx` ON `verification` (`identifier`);--> statement-breakpoint
CREATE TABLE `admin_audit_events` (
	`id` text PRIMARY KEY NOT NULL,
	`actor_user_id` text,
	`action` text NOT NULL,
	`target_type` text NOT NULL,
	`target_id` text,
	`outcome` text NOT NULL,
	`request_id` text,
	`ip_hash` text,
	`user_agent` text,
	`metadata_json` text DEFAULT '{}' NOT NULL,
	`created_at` integer DEFAULT (cast(unixepoch('subsecond') * 1000 as integer)) NOT NULL,
	FOREIGN KEY (`actor_user_id`) REFERENCES `user`(`id`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE INDEX `admin_audit_events_created_idx` ON `admin_audit_events` (`created_at`);--> statement-breakpoint
CREATE INDEX `admin_audit_events_actor_idx` ON `admin_audit_events` (`actor_user_id`,`created_at`);--> statement-breakpoint
CREATE INDEX `admin_audit_events_action_idx` ON `admin_audit_events` (`action`,`created_at`);--> statement-breakpoint
CREATE TABLE `application_reviews` (
	`id` text PRIMARY KEY NOT NULL,
	`application_id` text NOT NULL,
	`reviewer_id` text NOT NULL,
	`action` text NOT NULL,
	`notes_encrypted` text,
	`created_at` integer DEFAULT (cast(unixepoch('subsecond') * 1000 as integer)) NOT NULL,
	FOREIGN KEY (`application_id`) REFERENCES `membership_applications`(`id`) ON UPDATE no action ON DELETE cascade,
	FOREIGN KEY (`reviewer_id`) REFERENCES `user`(`id`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE INDEX `application_reviews_application_idx` ON `application_reviews` (`application_id`,`created_at`);--> statement-breakpoint
CREATE TABLE `chapters` (
	`id` text PRIMARY KEY NOT NULL,
	`slug` text NOT NULL,
	`name` text NOT NULL,
	`county` text NOT NULL,
	`state` text NOT NULL,
	`status` text DEFAULT 'in_development' NOT NULL,
	`description` text DEFAULT '' NOT NULL,
	`contact_email` text,
	`created_at` integer DEFAULT (cast(unixepoch('subsecond') * 1000 as integer)) NOT NULL,
	`updated_at` integer DEFAULT (cast(unixepoch('subsecond') * 1000 as integer)) NOT NULL
);
--> statement-breakpoint
CREATE UNIQUE INDEX `chapters_slug_unique` ON `chapters` (`slug`);--> statement-breakpoint
CREATE TABLE `contact_messages` (
	`id` text PRIMARY KEY NOT NULL,
	`name` text NOT NULL,
	`email` text NOT NULL,
	`subject` text NOT NULL,
	`message` text NOT NULL,
	`status` text DEFAULT 'new' NOT NULL,
	`created_at` integer DEFAULT (cast(unixepoch('subsecond') * 1000 as integer)) NOT NULL
);
--> statement-breakpoint
CREATE INDEX `contact_messages_created_idx` ON `contact_messages` (`created_at`);--> statement-breakpoint
CREATE TABLE `directory_profiles` (
	`id` text PRIMARY KEY NOT NULL,
	`user_id` text NOT NULL,
	`display_name` text NOT NULL,
	`chapter_id` text,
	`profession` text,
	`business_name` text,
	`skills_json` text DEFAULT '[]' NOT NULL,
	`expertise_json` text DEFAULT '[]' NOT NULL,
	`volunteer_interests_json` text DEFAULT '[]' NOT NULL,
	`visible` integer DEFAULT false NOT NULL,
	`contact_preferences_json` text DEFAULT '{}' NOT NULL,
	`updated_at` integer DEFAULT (cast(unixepoch('subsecond') * 1000 as integer)) NOT NULL,
	FOREIGN KEY (`user_id`) REFERENCES `user`(`id`) ON UPDATE no action ON DELETE cascade,
	FOREIGN KEY (`chapter_id`) REFERENCES `chapters`(`id`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE UNIQUE INDEX `directory_profiles_user_id_idx` ON `directory_profiles` (`user_id`);--> statement-breakpoint
CREATE INDEX `directory_profiles_chapter_visible_idx` ON `directory_profiles` (`chapter_id`,`visible`);--> statement-breakpoint
CREATE TABLE `invitations` (
	`id` text PRIMARY KEY NOT NULL,
	`email` text NOT NULL,
	`token_hash` text NOT NULL,
	`purpose` text DEFAULT 'member_activation' NOT NULL,
	`intended_role` text DEFAULT 'member' NOT NULL,
	`application_id` text,
	`expires_at` integer NOT NULL,
	`consumed_at` integer,
	`revoked_at` integer,
	`created_by` text,
	`created_at` integer DEFAULT (cast(unixepoch('subsecond') * 1000 as integer)) NOT NULL,
	`delivery_status` text DEFAULT 'not_configured' NOT NULL,
	`delivery_error` text,
	FOREIGN KEY (`application_id`) REFERENCES `membership_applications`(`id`) ON UPDATE no action ON DELETE no action,
	FOREIGN KEY (`created_by`) REFERENCES `user`(`id`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE UNIQUE INDEX `invitations_token_hash_unique` ON `invitations` (`token_hash`);--> statement-breakpoint
CREATE INDEX `invitations_email_idx` ON `invitations` (`email`);--> statement-breakpoint
CREATE INDEX `invitations_expires_idx` ON `invitations` (`expires_at`);--> statement-breakpoint
CREATE TABLE `member_profiles` (
	`id` text PRIMARY KEY NOT NULL,
	`user_id` text NOT NULL,
	`legal_first_name` text NOT NULL,
	`legal_last_name` text NOT NULL,
	`preferred_name` text,
	`phone_encrypted` text,
	`city` text,
	`state` text,
	`postal_code` text,
	`chapter_id` text,
	`joined_at` integer,
	`status` text DEFAULT 'pending' NOT NULL,
	`created_at` integer DEFAULT (cast(unixepoch('subsecond') * 1000 as integer)) NOT NULL,
	`updated_at` integer DEFAULT (cast(unixepoch('subsecond') * 1000 as integer)) NOT NULL,
	FOREIGN KEY (`user_id`) REFERENCES `user`(`id`) ON UPDATE no action ON DELETE cascade,
	FOREIGN KEY (`chapter_id`) REFERENCES `chapters`(`id`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE UNIQUE INDEX `member_profiles_user_id_idx` ON `member_profiles` (`user_id`);--> statement-breakpoint
CREATE INDEX `member_profiles_chapter_id_idx` ON `member_profiles` (`chapter_id`);--> statement-breakpoint
CREATE TABLE `membership_applications` (
	`id` text PRIMARY KEY NOT NULL,
	`application_number` text NOT NULL,
	`legal_name` text NOT NULL,
	`preferred_name` text,
	`email` text NOT NULL,
	`phone_encrypted` text,
	`city` text,
	`state` text,
	`postal_code` text,
	`desired_chapter_id` text,
	`interests_json` text DEFAULT '[]' NOT NULL,
	`skills_json` text DEFAULT '[]' NOT NULL,
	`volunteer_interests_json` text DEFAULT '[]' NOT NULL,
	`program_interests_json` text DEFAULT '[]' NOT NULL,
	`policies_accepted_at` integer,
	`privacy_acknowledged_at` integer,
	`status` text DEFAULT 'submitted' NOT NULL,
	`submitted_at` integer DEFAULT (cast(unixepoch('subsecond') * 1000 as integer)) NOT NULL,
	`reviewed_at` integer,
	`reviewed_by` text,
	`decision_notes_encrypted` text,
	`notification_status` text DEFAULT 'pending' NOT NULL,
	`created_at` integer DEFAULT (cast(unixepoch('subsecond') * 1000 as integer)) NOT NULL,
	`updated_at` integer DEFAULT (cast(unixepoch('subsecond') * 1000 as integer)) NOT NULL,
	FOREIGN KEY (`desired_chapter_id`) REFERENCES `chapters`(`id`) ON UPDATE no action ON DELETE no action,
	FOREIGN KEY (`reviewed_by`) REFERENCES `user`(`id`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE UNIQUE INDEX `membership_applications_application_number_unique` ON `membership_applications` (`application_number`);--> statement-breakpoint
CREATE INDEX `membership_applications_status_idx` ON `membership_applications` (`status`,`submitted_at`);--> statement-breakpoint
CREATE INDEX `membership_applications_email_idx` ON `membership_applications` (`email`);--> statement-breakpoint
CREATE INDEX `membership_applications_chapter_idx` ON `membership_applications` (`desired_chapter_id`);--> statement-breakpoint
CREATE TABLE `membership_status_history` (
	`id` text PRIMARY KEY NOT NULL,
	`membership_id` text NOT NULL,
	`from_status` text,
	`to_status` text NOT NULL,
	`reason` text,
	`actor_id` text,
	`created_at` integer DEFAULT (cast(unixepoch('subsecond') * 1000 as integer)) NOT NULL,
	FOREIGN KEY (`membership_id`) REFERENCES `memberships`(`id`) ON UPDATE no action ON DELETE cascade,
	FOREIGN KEY (`actor_id`) REFERENCES `user`(`id`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE INDEX `membership_status_history_membership_idx` ON `membership_status_history` (`membership_id`,`created_at`);--> statement-breakpoint
CREATE TABLE `membership_subscriptions` (
	`id` text PRIMARY KEY NOT NULL,
	`membership_id` text NOT NULL,
	`stripe_customer_id` text,
	`stripe_subscription_id` text,
	`price_id` text,
	`status` text DEFAULT 'not_configured' NOT NULL,
	`current_period_start` integer,
	`current_period_end` integer,
	`cancel_at_period_end` integer DEFAULT false NOT NULL,
	`created_at` integer DEFAULT (cast(unixepoch('subsecond') * 1000 as integer)) NOT NULL,
	`updated_at` integer DEFAULT (cast(unixepoch('subsecond') * 1000 as integer)) NOT NULL,
	FOREIGN KEY (`membership_id`) REFERENCES `memberships`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE UNIQUE INDEX `membership_subscriptions_stripe_subscription_id_unique` ON `membership_subscriptions` (`stripe_subscription_id`);--> statement-breakpoint
CREATE INDEX `membership_subscriptions_membership_idx` ON `membership_subscriptions` (`membership_id`);--> statement-breakpoint
CREATE TABLE `memberships` (
	`id` text PRIMARY KEY NOT NULL,
	`user_id` text NOT NULL,
	`chapter_id` text,
	`member_number` text NOT NULL,
	`status` text DEFAULT 'pending_activation' NOT NULL,
	`joined_at` integer,
	`activated_at` integer,
	`ends_at` integer,
	`created_at` integer DEFAULT (cast(unixepoch('subsecond') * 1000 as integer)) NOT NULL,
	`updated_at` integer DEFAULT (cast(unixepoch('subsecond') * 1000 as integer)) NOT NULL,
	FOREIGN KEY (`user_id`) REFERENCES `user`(`id`) ON UPDATE no action ON DELETE cascade,
	FOREIGN KEY (`chapter_id`) REFERENCES `chapters`(`id`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE UNIQUE INDEX `memberships_member_number_unique` ON `memberships` (`member_number`);--> statement-breakpoint
CREATE INDEX `memberships_user_id_idx` ON `memberships` (`user_id`);--> statement-breakpoint
CREATE INDEX `memberships_chapter_status_idx` ON `memberships` (`chapter_id`,`status`);--> statement-breakpoint
CREATE TABLE `payment_events` (
	`id` text PRIMARY KEY NOT NULL,
	`stripe_event_id` text NOT NULL,
	`type` text NOT NULL,
	`stripe_customer_id` text,
	`stripe_subscription_id` text,
	`amount_cents` integer,
	`currency` text,
	`status` text DEFAULT 'received' NOT NULL,
	`occurred_at` integer,
	`processed_at` integer,
	`payload_summary_json` text DEFAULT '{}' NOT NULL
);
--> statement-breakpoint
CREATE UNIQUE INDEX `payment_events_stripe_event_id_unique` ON `payment_events` (`stripe_event_id`);--> statement-breakpoint
CREATE INDEX `payment_events_subscription_idx` ON `payment_events` (`stripe_subscription_id`);--> statement-breakpoint
CREATE INDEX `payment_events_occurred_idx` ON `payment_events` (`occurred_at`);--> statement-breakpoint
CREATE TABLE `role_assignments` (
	`id` text PRIMARY KEY NOT NULL,
	`user_id` text NOT NULL,
	`role_key` text NOT NULL,
	`scope_type` text DEFAULT 'global' NOT NULL,
	`scope_id` text,
	`granted_by` text,
	`granted_at` integer DEFAULT (cast(unixepoch('subsecond') * 1000 as integer)) NOT NULL,
	`revoked_at` integer,
	`revoked_by` text,
	FOREIGN KEY (`user_id`) REFERENCES `user`(`id`) ON UPDATE no action ON DELETE cascade,
	FOREIGN KEY (`granted_by`) REFERENCES `user`(`id`) ON UPDATE no action ON DELETE no action,
	FOREIGN KEY (`revoked_by`) REFERENCES `user`(`id`) ON UPDATE no action ON DELETE no action
);
--> statement-breakpoint
CREATE INDEX `role_assignments_user_idx` ON `role_assignments` (`user_id`,`revoked_at`);--> statement-breakpoint
CREATE INDEX `role_assignments_scope_idx` ON `role_assignments` (`scope_type`,`scope_id`,`revoked_at`);