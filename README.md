# SakuBot

SakuBot watches Sakurazaka46's official channels and posts anything new to a Discord channel through a webhook. It runs entirely on GitHub Actions, so there is no server to host and nothing to install.

> Unofficial fan project. It is not affiliated with or endorsed by Sakurazaka46 or its management.

## What it posts

| Source | Where it comes from | Reliability |
|---|---|---|
| Member blogs | Official site, blog list | Good |
| News | Official site, news list (current month) | Good |
| Daily schedule | Official site, schedule page | Good |
| YouTube | RSS for @sakurazaka46SMEJ and @sakurazakachannel | Good |
| TikTok, X, Instagram | Public RSSHub instance | Best effort |

Blog posts show the member, date, title and an excerpt. News items show their category and date. Once a day, SakuBot also posts that day's schedule (TV, radio, magazines, events).

## How it works

A scheduled GitHub Actions job runs `poll.py` about every 10 minutes. The script fetches each source, compares the results with the IDs it has already seen, and sends anything new to Discord. The list of seen IDs is stored in `state/seen.json` and committed back to the repo after each run.

On the very first run, SakuBot only records what already exists, so your channel is not flooded with old posts.

New posts usually appear 10 to 20 minutes after they go up. GitHub's scheduler can run late, so this is not instant.

## Setup

### 1. Create a Discord webhook
In your server, open the channel's settings, then **Integrations > Webhooks > New Webhook**. Copy the webhook URL. You need the Manage Webhooks permission.

### 2. Create the repository
Create a **public** GitHub repository (public repos get unlimited free Actions minutes) and upload the project files, keeping the folder structure. The workflow file must be at `.github/workflows/poll.yml`.

### 3. Add the webhook as a secret
Go to **Settings > Secrets and variables > Actions > New repository secret** and add:

- Name: `DISCORD_WEBHOOK_URL`
- Value: your webhook URL

Never commit the webhook URL to a file.

### 4. Run it
Open the **Actions** tab, enable workflows if prompted, select **SakuBot poll**, and click **Run workflow**. Check the log for lines like `[blog] seeded 11 items`. After that it runs on its own.

If the "Save state" step fails with a permissions error, set **Settings > Actions > General > Workflow permissions** to *Read and write*.

## Configuration

Edit `config.json` in the repository.

| Key | Description |
|---|---|
| `sources` | Turn individual sources on or off. |
| `schedule_digest` | `enabled` and `hour_jst`. The digest posts on the first run after that hour (Japan time). |
| `ping_role_id` | A Discord role ID to ping on every post. Leave blank for none. |
| `member_pings` | Ping specific users when a member posts a blog, e.g. `{"山﨑天": ["123456789012345678"]}`. Names can be in kanji or the romaji aliases listed in `poll.py`. |
| `max_posts_per_run` | Maximum posts per source per run. Default 5. |
| `youtube_handles` | YouTube channels to follow. |
| `rsshub_base` | RSSHub instance used for TikTok, X and Instagram. |

To send a source to its own channel, add a repository secret named `WEBHOOK_BLOG`, `WEBHOOK_NEWS`, `WEBHOOK_YOUTUBE`, `WEBHOOK_TIKTOK`, `WEBHOOK_X`, `WEBHOOK_INSTAGRAM` or `WEBHOOK_SCHEDULE`. Anything without its own webhook uses `DISCORD_WEBHOOK_URL`.

To use a different RSSHub instance without editing code, add a repository variable named `RSSHUB_BASE`.

## Testing

Check the webhook itself:

```
curl -H "Content-Type: application/json" -d '{"content":"SakuBot test"}' YOUR_WEBHOOK_URL
```

Check posting: open `state/seen.json`, delete two or three IDs from the `blog` or `news` list, commit, then run the workflow again. Those items should be posted.

Check member pings: add your Discord user ID to `member_pings` (enable Developer Mode in Discord, then right-click yourself and choose Copy User ID), remove one of that member's posts from `seen.json`, and run the workflow.

Check the schedule digest: set `hour_jst` to `0`, delete the `digest_date` line from `seen.json`, run the workflow, then set the hour back.

## Running locally

```
pip install -r requirements.txt
DISCORD_WEBHOOK_URL="your-url" python poll.py
```

This reads and updates `state/seen.json` in the same way the workflow does.

## Project layout

```
.github/workflows/poll.yml   Schedule and workflow
poll.py                      Fetching, parsing and posting
config.json                  Settings
requirements.txt             Python dependencies
state/seen.json              IDs already posted
```

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Nothing is posted | Check the Actions log. A `FAILED` line shows the error. |
| `0 blog posts found` or `0 news items found` | The official site changed its layout and the parser needs updating. |
| TikTok, X or Instagram never post | The public RSSHub instance is rate-limited or blocked. Self-host one or leave these sources off. |
| Posts stop after a long time | GitHub pauses scheduled workflows in inactive repos. SakuBot makes a small monthly commit to avoid this, but check the Actions tab occasionally. |

If a source fails 12 runs in a row, SakuBot posts a warning to Discord.

## Limitations

- The member roster in `poll.py` (`ROSTER`) is used to read names from the schedule page. Update it when members join or graduate.
- The schedule parser reads the page's text rather than a stable API, so a site redesign can break it.
- TikTok, X and Instagram have no official free feeds and depend on third-party bridges.
- SakuBot posts titles, short excerpts, thumbnails and links back to the source. It does not republish full blog text.