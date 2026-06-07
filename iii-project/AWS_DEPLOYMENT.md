# CareCircle AWS Connection Plan

This setup is designed for a strict 20 USD/month cap.

## Cost Guardrails

1. In AWS Billing, create a monthly budget for 20 USD.
2. Add alerts at 5, 10, 15, and 18 USD.
3. Use one Lightsail Linux instance only.
4. Do not start SageMaker, GPU EC2, RDS, NAT Gateway, or provisioned Bedrock throughput.

## Recommended Server

Use Amazon Lightsail Linux/Unix:

- 5 USD/month bundle for the API MVP.
- 7 USD/month bundle if the 5 USD server feels slow.
- Keep AI calls pay-per-request and rate-limited.

## Local Test

```powershell
cd "C:\Users\anshul nautiyal\OneDrive\Pictures\Documents\hackathon final;\iii-project"
node server.js
```

Health check:

```powershell
Invoke-WebRequest -Uri "http://127.0.0.1:8080/api/health" -UseBasicParsing
```

To connect the local frontend to the local API, edit `aws-config.js`:

```js
window.CARECIRCLE_API_BASE_URL = "http://127.0.0.1:8080";
```

## Lightsail Deploy

On your Lightsail instance:

```bash
sudo apt update
sudo apt install -y nodejs npm git
mkdir -p ~/carecircle
```

Upload the project folder to `~/carecircle`, then:

```bash
cd ~/carecircle
cp .env.example .env
nano .env
npm start
```

For a persistent process:

```bash
sudo npm install -g pm2
pm2 start server.js --name carecircle-api
pm2 save
pm2 startup
```

Open port `8080` in the Lightsail firewall.

Then update `aws-config.js` in the website:

```js
window.CARECIRCLE_API_BASE_URL = "http://YOUR_LIGHTSAIL_PUBLIC_IP:8080";
```

## AI Provider

By default the API uses a local safe response mode:

```env
AI_PROVIDER=local
```

Hoon Buddy uses the AWS AI Lambda configured by
`CARECIRCLE_AI_API_BASE_URL`. The Lambda invokes Amazon Bedrock; no
third-party AI key is stored in the browser or server environment.

Do not put AI keys in frontend JavaScript.
