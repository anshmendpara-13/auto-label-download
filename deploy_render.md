# Deploying Meesho Bot to Render.com

This guide provides step-by-step instructions on deploying the Meesho Bot dashboard and background scheduler to Render using the preconfigured `Dockerfile`.

---

## Prerequisites
1. A free account on [Render.com](https://render.com).
2. A free account on [GitHub](https://github.com) or GitLab.
3. Your local folder committed to a Git repository.

---

## Step-by-Step Deployment

### 1. Push Code to GitHub
Ensure the following files are committed and pushed to your GitHub repository:
- `app.py`
- `scheduler.py`
- `meesho_bot.py`
- `login_setup.py`
- `requirements.txt`
- `Dockerfile`
- `templates/` and `static/` folders

### 2. Create a Web Service on Render
1. Log in to **Render Dashboard** and click **New +** -> **Web Service**.
2. Connect your GitHub account and select your repository.
3. Configure the following service settings:
   - **Name**: `meesho-bot` (or any custom name)
   - **Language/Runtime**: Select **Docker** (Render will automatically detect your `Dockerfile`).
   - **Branch**: `main` (or the branch you pushed to)
   - **Instance Type**: Select **Free**.

### 3. Configure Environment Variables
Scroll down to the **Environment Variables** section and add the following keys to match your `.env` configuration:
- `HEADLESS`: `true` (Must be `true` on server environments!)
- `ACCOUNTS`: `lavanyafashion,lavanzafashion`
- `SCHEDULE_TIMES`: `10:00, 15:05, 15:09`
- `DOWNLOAD_DIR`: `./downloads`
- `MEESHO_EMAIL_LAVANYAFASHION`: `your-email@gmail.com`
- `MEESHO_PASSWORD_LAVANYAFASHION`: `your-password`
- `MEESHO_EMAIL_LAVANZAFASHION`: `your-email@gmail.com`
- `MEESHO_PASSWORD_LAVANZAFASHION`: `your-password`

Click **Create Web Service**. Render will now pull the code, build the Docker container, install Playwright, and launch your server.

---

## CRITICAL: Keeping the App Awake (Uptime Monitoring)

> [!WARNING]
> Render's **Free Tier** automatically puts your application to sleep after **15 minutes of inactivity**. If the application sleeps, the background scheduler thread stops running, and the bot will miss its scheduled execution times!

### How to keep the bot awake 24/7 for free:
1. Go to a free website monitoring service such as [Cron-Job.org](https://cron-job.org/) or [UptimeRobot](https://uptimerobot.com/).
2. Create a free account.
3. Set up a new cron-job or monitor:
   - **URL**: Your Render Web Service URL (e.g., `https://meesho-bot.onrender.com/`)
   - **Method**: `GET`
   - **Interval**: Every **5 minutes** or **10 minutes**.
4. This ensures a request is sent to your server regularly, keeping the container fully awake and active so the background scheduler runs on time!

---

## Managing Sessions
Because Render's free tier uses an ephemeral filesystem, session files (`state.json`) are reset when the container is redeployed or restarted.
* **To upload your sessions**: Simply log in to the dashboard page, navigate to the **Upload Session** section, and upload the generated `state.json` file for each account.
* **Optional Paid Upgrade**: If you upgrade to Render's paid tier ($5/month), you can attach a persistent **Render Disk** to mount the `/app/data` and `/app/downloads` folders, keeping your logins and downloads permanent.
