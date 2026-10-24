// API base. Empty string = same origin (local server / EC2 serving this page).
// On GitHub Pages this is the AWS Lambda Function URL; override at runtime with ?api=http://<ec2-ip>:8000
window.API_BASE = "https://ce75ttmqcc5g3il7yefnupx6ee0qydmz.lambda-url.us-east-1.on.aws";
// Speed bump against casual abuse of the public endpoint. It is visible to anyone who opens this file,
// so it is NOT a secret; the real limits are the input caps, the 4 s clip cap and the AWS budgets.
window.DEMO_TOKEN = "DP2BlLdVThQZUWaP";
window.REPO_URL = "https://github.com/SanTiwari07/HumSight";
window.VIDEO_URL = "";
