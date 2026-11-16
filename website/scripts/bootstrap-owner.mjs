import { execFileSync } from "node:child_process";
import crypto from "node:crypto";
import path from "node:path";
import readline from "node:readline/promises";

import { hashPassword } from "better-auth/crypto";

const wranglerBin = path.resolve("node_modules/wrangler/bin/wrangler.js");

function argument(name) {
  const prefix = `--${name}=`;
  const found = process.argv.find((value) => value.startsWith(prefix));
  return found ? found.slice(prefix.length) : undefined;
}

function hasFlag(name) {
  return process.argv.includes(`--${name}`);
}

function sqlString(value) {
  return `'${String(value).replaceAll("'", "''")}'`;
}

function wrangler(args) {
  return execFileSync(process.execPath, [wranglerBin, ...args], {
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
  });
}

function d1(sql, remote, envName) {
  const args = ["d1", "execute", "DB", "--json", "--command", sql];
  args.push(remote ? "--remote" : "--local");
  if (remote && envName) args.push("--env", envName);
  const output = wrangler(args);
  const parsed = JSON.parse(output);
  return parsed[0]?.results ?? [];
}

async function ask(label) {
  const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout,
  });
  const answer = await rl.question(label);
  rl.close();
  return answer.trim();
}

async function promptHidden(label) {
  if (!process.stdin.isTTY || !process.stdout.isTTY) {
    throw new Error("Use --password-env for non-interactive bootstrap.");
  }
  process.stdout.write(label);
  const stdin = process.stdin;
  const wasRaw = stdin.isRaw;
  stdin.setRawMode?.(true);
  stdin.resume();
  stdin.setEncoding("utf8");
  let value = "";
  return await new Promise((resolve, reject) => {
    const finish = (result) => {
      stdin.setRawMode?.(Boolean(wasRaw));
      stdin.pause();
      stdin.off("data", onData);
      process.stdout.write("\n");
      resolve(result);
    };
    const onData = (character) => {
      if (character === "\u0003") {
        stdin.setRawMode?.(Boolean(wasRaw));
        stdin.pause();
        stdin.off("data", onData);
        reject(new Error("Cancelled."));
        return;
      }
      if (character === "\r" || character === "\n") {
        finish(value);
        return;
      }
      if (character === "\u007f" || character === "\b") {
        value = value.slice(0, -1);
        return;
      }
      value += character;
    };
    stdin.on("data", onData);
  });
}

const remote = hasFlag("remote");
const envName = argument("env");
const email = argument("email") ?? (await ask("Owner email: "));
const name = argument("name") ?? (await ask("Owner display name: "));
const passwordEnv = argument("password-env");
const password = passwordEnv
  ? process.env[passwordEnv]
  : await promptHidden("Owner password (hidden): ");

if (!email || !name || !password) {
  throw new Error("Email, name, and password are required.");
}
if (password.length < 12) {
  throw new Error("Owner password must be at least 12 characters.");
}

const existingOwner = d1(
  "SELECT id FROM role_assignments WHERE role_key='owner' AND revoked_at IS NULL LIMIT 1;",
  remote,
  envName,
);
if (existingOwner.length > 0) {
  throw new Error("An active owner already exists. Bootstrap aborted.");
}

const existingUser = d1(
  `SELECT id FROM user WHERE email=${sqlString(email.toLowerCase())} LIMIT 1;`,
  remote,
  envName,
);
if (existingUser.length > 0) {
  throw new Error("A user with that email already exists. Bootstrap aborted.");
}

const userId = crypto.randomUUID().replaceAll("-", "");
const accountId = crypto.randomUUID().replaceAll("-", "");
const roleId = crypto.randomUUID().replaceAll("-", "");
const now = Date.now();
const passwordHash = await hashPassword(password);

const sql = [
  `INSERT INTO user (id,name,email,email_verified,created_at,updated_at,two_factor_enabled) VALUES (${sqlString(userId)},${sqlString(name)},${sqlString(email.toLowerCase())},1,${now},${now},0);`,
  `INSERT INTO account (id,account_id,provider_id,user_id,password,created_at,updated_at) VALUES (${sqlString(accountId)},${sqlString(userId)},'credential',${sqlString(userId)},${sqlString(passwordHash)},${now},${now});`,
  `INSERT INTO role_assignments (id,user_id,role_key,scope_type,scope_id,granted_at) VALUES (${sqlString(roleId)},${sqlString(userId)},'owner','global',NULL,${now});`,
].join(" ");

d1(sql, remote, envName);

console.log(`Owner bootstrap complete for ${email}.`);
console.log("Next steps:");
console.log("1. Sign in at /login.");
console.log("2. Enroll MFA before performing administrative mutations.");
console.log("3. Create additional accounts through the admin workflow when it is implemented.");
console.log("4. Never store the password or bootstrap values in Git or shell history.");
