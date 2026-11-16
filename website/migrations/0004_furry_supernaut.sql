DROP INDEX `memberships_user_id_idx`;--> statement-breakpoint
CREATE UNIQUE INDEX `memberships_user_id_unique` ON `memberships` (`user_id`);