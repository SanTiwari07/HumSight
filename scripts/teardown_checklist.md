# AWS teardown checklist

- [ ] EC2 instance **terminated** (not just stopped), unless needed for a scheduled judge session
- [ ] EBS -> Volumes: none left "available"
- [ ] EBS -> Snapshots: none you created
- [ ] EC2 -> Elastic IPs: none allocated
- [ ] Spot requests: none open
- [ ] Marketplace subscription: cancel after judging (no instances = no software fee, but cancel anyway)
- [ ] S3: lifecycle on; delete the bucket after judging
- [ ] Lambda: delete after judging (an idle Lambda costs nothing)
- [ ] SSM parameter `/humsight/gemini_key` deleted
- [ ] Billing -> Bills: check next day; Budgets alerts silent
