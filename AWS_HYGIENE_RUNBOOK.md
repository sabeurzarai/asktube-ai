# AWS Account Hygiene Runbook

EC2 instance + Elastic IP were already torn down (terminated July 2026). What
remains on the account, in priority order: a Secrets Manager secret, an S3
bucket, possibly orphaned EBS volumes/snapshots, an oversize budget alert, and
root MFA. **Keep the account itself** — it has ~$18.85 of credit through Dec 2026.

> **Why a runbook and not automation?** The AWS CLI isn't installed in the dev
> environment, the project docs don't record the exact resource names/region, and
> guessing a bucket name to delete is dangerous. So: **discover first, delete by
> exact name**. No credentials need to enter the dev environment.

## 0. Before you start

- Sign in to the AWS Console as **root** (or an IAM admin) at
  https://console.aws.com .
- Pick the **region** the project used. Resources are regional — if you don't
  see something, switch the region dropdown (top-right) and look again. If you
  don't remember the region, visit each region in turn, or use the "All regions"
  view in Cost Explorer (step 5) which is global.
- Keep the account — we are deleting leftover **resources**, not the account.

---

## 1. Delete the Secrets Manager secret

The backend used to read its config (e.g. `OPENAI_API_KEY`) from a Secrets
Manager secret on EC2.

**Console:**
1. Services → **Secrets Manager** → **Secrets** (left nav).
2. Set the region dropdown (top-right) to the region the project used. If unsure,
   repeat for each region where you see a secret.
3. Look for a secret with a name containing `asktube`, `AskTube`, or `prod`.
4. Select the secret → **Actions** → **Delete secret**.
5. Secrets Manager forces a **7-day recovery window** by default. For immediate
   deletion, uncheck "Enable recovery window" (or set it to 0) before confirming.
6. Confirm. The secret shows `Pending deletion` until purged.

**CLI equivalent (only if you install awscli):**
```bash
aws secretsmanager list-secrets --query 'SecretList[?contains(Name,`asktube`)]'
# replace <Name> with the exact value returned:
aws secretsmanager delete-secret --secret-id <Name> --force-delete-without-recovery
```

> The deleted secret contained live API keys. **Rotate `OPENAI_API_KEY` and
> `YOUTUBE_API_KEY` if those values are no longer needed** by the Vercel/Render
> deployment — otherwise the keys are still valid out in the world.

---

## 2. Empty + delete the S3 bucket

**Console:**
1. Services → **S3** → **Buckets**.
2. (S3 buckets are global in the console list, but the objects live in one
   region — note the bucket's region column.)
3. Find the bucket named like `asktube-*` (or whatever was wired into the old
   EC2 config).
4. Click the bucket → **Empty** → type `permanently delete` to confirm → **Empty**.
   This deletes all objects (and versions, if versioning was on).
5. Back at the bucket list → select the bucket → **Delete** → type the bucket
   name to confirm → **Delete bucket**.

**CLI equivalent:**
```bash
aws s3api list-buckets --query 'Buckets[?contains(Name,`asktube`)].Name'
# replace <bucket> with the exact name:
aws s3 rb s3://<bucket> --force
```

> ⚠️ `aws s3 rb --force` deletes all objects then the bucket — irreversible.
> Only run it after confirming the name in the `list-buckets` output.

---

## 3. Confirm no "Available" EBS volumes or snapshots

Orphaned EBS volumes (status `Available` = not attached to any instance) bill at
~$0.08–0.10/GB-month even with the instance gone.

**Console:**
1. Services → **EC2** → **Volumes** (left nav, under Elastic Block Store).
2. Filter **State = Available**. The list should be empty (the terminated
   instance's root volume deletes on termination by default).
3. If any `Available` volume shows → select → **Actions** → **Delete volume**.
4. Now **Snapshots** (left nav). Look for snapshots you created (not the
   AWS-default public ones). Delete any owned snapshots you don't need.
5. Repeat for **each region** you ever used (region dropdown, top-right) — EBS
   is regional.

**CLI equivalent:**
```bash
aws ec2 describe-volumes --filters Name=status,Values=available \
  --query 'Volumes[].{ID:VolumeId,Size:Size,Region:AvailabilityZone}'
# if anything is returned:
aws ec2 delete-volume --volume-id <vol-id>
aws ec2 describe-snapshots --owner-ids self --query 'Snapshots[].{ID:SnapshotId,Started:StartTime}'
```

> If `describe-volumes` returns empty in every region, you're clean.

---

## 4. Lower the budget alert to ~$1

A budget alert doesn't cost anything, but a stale high threshold stops warning
you before the credit runs out. Set it to $1 so you get an email if anything
starts billing against the remaining $18.85.

**Console (budgets are global — IAM/root):**
1. Services → **AWS Budgets** (or search "Budgets" in the top bar).
2. Click the existing budget (e.g. "Monthly cost budget").
3. **Edit budget** → set **Budgeted amount** to `1.00` USD.
4. Under **Alert conditions**, set the threshold to **Actual > 50% of budget**
   (i.e. $0.50) so you get warned early, and add **Forecasted > 100%** as a
   second condition.
5. Confirm the **Email recipients** is your real address.
6. **Save**.

**CLI equivalent (budgets CLI is fiddly — console is faster):**
```bash
aws budgets describe-budget --account-id $(aws sts get-caller-identity --query Account --output text) --budget-name "<name>"
```

---

## 5. Enable MFA on the root account

Root MFA has no API — console only.

**Console:**
1. Sign in as root → click the account name (top-right) → **Security credentials**.
2. Under **Multi-factor authentication (MFA)** → **Assign MFA device**.
3. Choose a type:
   - **Authenticator app** (recommended) — Google Authenticator / 1Password /
     Authy. Scan the QR, enter two consecutive codes.
   - **Security key** — a YubiKey or similar (strongest, if you have one).
   - *Avoid "SMS" / virtual MFA unless you have no other option.*
4. Finish, then **sign out and back in** to confirm MFA is enforced.

**Then (recommended hardening while you're here):**
- Under the same Security credentials page, remove any **Access keys** for root
  if present. Root keys are a common source of account compromise; the CLI work
  above can be done from an IAM user instead.
- In **IAM → Account settings**, consider enabling "MFA deletion" / requiring
  MFA for root-level actions.

---

## 6. Final verification

After steps 1–5, do a sanity sweep:

- **Billing → Bills** (current month): should show only the tiny baseline
  (~$0.00) with the credit covering it. No EC2 / EBS / S3 line items.
- **Cost Explorer** (last 30 days, grouped by Service): confirms the teardown is
  reflected; nothing trending upward.
- **S3 / EC2 / Secrets Manager** in every region: all empty for this project.

If all of the above are clean, the account is hygienic and the $18.85 credit is
safe until December 2026.
