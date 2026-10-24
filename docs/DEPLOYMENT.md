# Deployment guide

> **Not executed from this repository.** These steps are written from the design in [planning/IMPLEMENTATION.md](planning/IMPLEMENTATION.md) §5 and §9 and from the code in `lambda_fn/`, `scripts/` and `deploy/`. The handler is tested against a fake S3; the AWS CLI commands below have not been run, so check each against your account (region, limits, names) as you go. Replace `BUCKET`, `ACCOUNT_ID` and the GitHub Pages origin in `deploy/*.json` first.

Everything uses **us-east-1** to avoid cross-region charges. Expected spend is a few cents to well under a dollar (Spot instance for a few hours; Lambda, S3 and SSM inside free tiers); the real cost is whatever your Billing console shows, so keep the guards below on.

## 0. Guards first

1. Billing → Budgets: a **zero-spend budget** and a **$1 monthly budget** with 50% / 100% alerts.
2. Billing preferences: enable free-tier usage alerts.
3. Only then create anything else.

## 1. S3 bucket

```bash
export BUCKET=humsight-$RANDOM$RANDOM
aws s3api create-bucket --bucket $BUCKET --region us-east-1
aws s3api put-public-access-block --bucket $BUCKET --public-access-block-configuration \
  BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
aws s3api put-bucket-lifecycle-configuration --bucket $BUCKET --lifecycle-configuration file://deploy/lifecycle.json
aws s3api put-bucket-cors --bucket $BUCKET --cors-configuration file://deploy/s3-cors.json
```

`uploads/` and `outputs/` expire after 7 days; `demo/` is kept.

## 2. Gemini key (optional; the rules policy works without it)

```bash
aws ssm put-parameter --name /humsight/gemini_key --type SecureString --tier Standard --value "<key>"
```

(Use the console if you do not want the key in your shell history.)

## 3. Lambda (arm64, python3.12)

```bash
bash lambda_fn/build_layer.sh        # builds layer.zip and function.zip without Docker (manylinux2014_aarch64 wheels)
```

Check that the unzipped layer is under 250 MB together with the function. Layers above 50 MB must be uploaded through S3.

```bash
aws s3 cp layer.zip s3://$BUCKET/_deploy/layer.zip
aws lambda publish-layer-version --layer-name humsight-deps \
  --content S3Bucket=$BUCKET,S3Key=_deploy/layer.zip \
  --compatible-runtimes python3.12 --compatible-architectures arm64

# role
aws iam create-role --role-name humsight-lambda --assume-role-policy-document file://deploy/lambda-trust-policy.json
aws iam put-role-policy --role-name humsight-lambda --policy-name humsight --policy-document file://deploy/lambda-permissions.json

aws lambda create-function --function-name humsight --runtime python3.12 --architectures arm64 \
  --handler handler.handler --memory-size 3008 --timeout 120 \
  --role arn:aws:iam::ACCOUNT_ID:role/humsight-lambda \
  --zip-file fileb://function.zip --layers <LayerVersionArn> \
  --environment "Variables={BUCKET=$BUCKET,GEMINI_PARAM=/humsight/gemini_key,MAX_DURATION_S=4,DEMO_TOKEN=<random>}"
```

Memory above 3008 MB may be refused on new accounts; 3008 MB is enough for 4 s clips.

Reserved concurrency of 2 limits abuse, but accounts with the default concurrency quota cannot reserve below the unreserved minimum; if `put-function-concurrency` is refused, rely on the token, the input caps and the budget alarms instead.

```bash
aws lambda put-function-concurrency --function-name humsight --reserved-concurrent-executions 2
aws lambda create-function-url-config --function-name humsight --auth-type NONE --cors file://deploy/function-url-cors.json
aws lambda add-permission --function-name humsight --statement-id url --action lambda:InvokeFunctionUrl \
  --principal "*" --function-url-auth-type NONE
```

Smoke test:

```bash
curl -s <function-url>/health            # expect "mode":"lambda" and "cool":false (honest)
```

## 4. Demo clips on S3

```bash
python scripts/make_demo_clips.py
BUCKET=$BUCKET python scripts/upload_demo_s3.py
curl -s -X POST <function-url>/jobs -H 'content-type: application/json' \
  -d '{"demo_id":"pump_shake_fault","policy":"rules"}'     # expect "verdict":"FAULT"
```

If you set `DEMO_TOKEN`, add `-H 'x-demo-token: <token>'` and put the same value in `web/config.js` (`DEMO_TOKEN`). It is a speed bump, not authentication.

## 5. Static page on GitHub Pages

1. Edit `web/config.js`: `API_BASE` = the Function URL, `REPO_URL`.
2. Update the CORS origin in `deploy/s3-cors.json` and `deploy/function-url-cors.json` to your Pages origin and re-apply them.
3. Repository Settings → Pages → Source **GitHub Actions**, then run the "Deploy web to GitHub Pages" workflow (manual) from the Actions tab.

On Lambda the job runs synchronously and returns the whole trace; the page replays it at 400 ms per step and labels it "recorded trace". Live SSE streaming is available on the EC2 server.

## 6. COOL on EC2 Spot (benchmark and live session)

See [COOL.md](COOL.md) for the evidence checklist. In short:

1. AWS Marketplace → "Cloud Optimized OpenCV" → Graviton4 listing → read the pricing and trial terms (screenshot them) → subscribe.
2. Launch through EC2: `c8g.large`, Spot, default VPC with a public IP (no Elastic IP), root volume deleted on termination, security group with SSH and port 8000 from **your IP only**.
3. On the instance: `bash scripts/ec2_setup.sh` (COOL venv plus a stock venv on the same box), then `python scripts/verify_cool.py` in both and keep the screenshots.
4. `python scripts/make_demo_clips.py && bash scripts/run_bench_ec2.sh`; commit `bench/*.json` and `bench/RESULTS.md` immediately (Spot can be interrupted).
5. Live session for judges: `uvicorn server.app:app --host 0.0.0.0 --port 8000` in the COOL venv; the startup banner shows `COOL=True`. Open the page with `?api=http://<ip>:8000`.
6. **Terminate the instance** when done.

## 7. Teardown

Follow `scripts/teardown_checklist.md`: terminate the instance, no leftover volumes, snapshots, Elastic IPs or Spot requests, delete the bucket and Lambda after judging, delete the SSM parameter, cancel the Marketplace subscription, and check Billing the next day.
