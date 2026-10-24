// API base. Empty string = same origin (local server / EC2 serving this page).
// For GitHub Pages set it to the Lambda Function URL; override at runtime with ?api=http://<ec2-ip>:8000
window.API_BASE = "";
window.DEMO_TOKEN = "";   // optional X-Demo-Token for the Lambda endpoint
window.REPO_URL = "https://github.com/<you>/humsight";
window.VIDEO_URL = "";
