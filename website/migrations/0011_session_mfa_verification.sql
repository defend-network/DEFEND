ALTER TABLE `user` ADD `two_factor_enabled_at` integer;--> statement-breakpoint
UPDATE `user`
SET `two_factor_enabled_at` = (cast(unixepoch('subsecond') * 1000 as integer))
WHERE `two_factor_enabled` = 1 AND `two_factor_enabled_at` IS NULL;