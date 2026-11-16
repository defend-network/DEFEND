import { createDecipheriv, createHash, scryptSync } from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { gunzipSync } from "node:zlib";

function argument(name) {
  const prefix = `--${name}=`;
  const found = process.argv.find((value) => value.startsWith(prefix));
  return found ? found.slice(prefix.length) : undefined;
}

const file = argument("file");
const output = argument("out");
const passphrase = process.env.BACKUP_PASSPHRASE;
if (!file || !output) throw new Error("Usage: node scripts/verify-backup.mjs --file=backup.enc --out=restored.sql");
if (!passphrase || passphrase.length < 20) throw new Error("Set BACKUP_PASSPHRASE.");
const payload = fs.readFileSync(path.resolve(file));
if (payload.subarray(0, 7).toString() !== "DEFEND1") throw new Error("Not a DEFEND backup.");
const salt = payload.subarray(7, 23);
const iv = payload.subarray(23, 35);
const tag = payload.subarray(35, 51);
const ciphertext = payload.subarray(51);
const decipher = createDecipheriv("aes-256-gcm", scryptSync(passphrase, salt, 32), iv);
decipher.setAuthTag(tag);
const sql = gunzipSync(Buffer.concat([decipher.update(ciphertext), decipher.final()]));
const digest = createHash("sha256").update(payload).digest("hex");
const manifestPath = `${path.resolve(file)}.json`;
const manifest = fs.existsSync(manifestPath) ? JSON.parse(fs.readFileSync(manifestPath, "utf8")) : null;
if (manifest?.sha256 && manifest.sha256 !== digest) throw new Error("Backup checksum does not match manifest.");
if (!sql.includes("CREATE TABLE")) throw new Error("Restored SQL is missing table definitions.");
fs.writeFileSync(path.resolve(output), sql);
console.log(JSON.stringify({ ok: true, bytes: sql.length, sha256: digest, output: path.resolve(output) }));
