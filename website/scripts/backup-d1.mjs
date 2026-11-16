import { createCipheriv, createHash, randomBytes, randomUUID, scryptSync } from "node:crypto";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { gzipSync } from "node:zlib";

function argument(name, fallback) {
  const prefix = `--${name}=`;
  const found = process.argv.find((value) => value.startsWith(prefix));
  return found ? found.slice(prefix.length) : fallback;
}

const envName = argument("env", "staging");
const local = process.argv.includes("--local");
const stamp = new Date().toISOString().replaceAll(":", "-").replace(/\..+$/, "");
const outDir = path.resolve(argument("out-dir", "backups"));
const passphrase = process.env.BACKUP_PASSPHRASE;
if (!passphrase || passphrase.length < 20) {
  throw new Error("Set BACKUP_PASSPHRASE to a unique passphrase of at least 20 characters.");
}
fs.mkdirSync(outDir, { recursive: true });
const sqlPath = path.join(os.tmpdir(), `defend-d1-${randomUUID()}.sql`);
const wrangler = path.resolve("node_modules/wrangler/bin/wrangler.js");
const args = [wrangler, "d1", "export", "DB", "--output", sqlPath, "--skip-confirmation"];
if (local) {
  args.push("--local");
} else {
  args.push("--remote", "--env", envName);
}
try {
  execFileSync(process.execPath, args, { stdio: "inherit" });
  const sql = fs.readFileSync(sqlPath);
  if (!sql.includes("CREATE TABLE")) throw new Error("D1 export did not contain CREATE TABLE statements.");
  const compressed = gzipSync(sql, { level: 9 });
  const salt = randomBytes(16);
  const iv = randomBytes(12);
  const key = scryptSync(passphrase, salt, 32);
  const cipher = createCipheriv("aes-256-gcm", key, iv);
  const ciphertext = Buffer.concat([cipher.update(compressed), cipher.final()]);
  const payload = Buffer.concat([Buffer.from("DEFEND1"), salt, iv, cipher.getAuthTag(), ciphertext]);
  const filename = `defend-${envName}-${stamp}.sql.gz.enc`;
  const outputPath = path.join(outDir, filename);
  fs.writeFileSync(outputPath, payload);
  const sha256 = createHash("sha256").update(payload).digest("hex");
  const manifest = {
    format: "DEFEND1",
    environment: envName,
    local,
    createdAt: new Date().toISOString(),
    file: filename,
    bytes: payload.length,
    sqlBytes: sql.length,
    sha256,
    encryption: "aes-256-gcm+scrypt",
  };
  fs.writeFileSync(`${outputPath}.json`, `${JSON.stringify(manifest, null, 2)}\n`);
  console.log(JSON.stringify(manifest));
} finally {
  fs.rmSync(sqlPath, { force: true });
}
