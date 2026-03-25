# pricealerter.in Fix Guide

This workspace currently runs on Flask plus static HTML/JS, not React + Node.js + MongoDB + Puppeteer.

That means there are 2 tracks:

1. Stabilize the current app now.
2. Use the Node/Puppeteer architecture below if you are migrating to the stack you described.

## 1. Likely causes of your issues

### Scraper fails or misses prices

- Many ecommerce sites render price after JavaScript loads.
- Sites rotate CSS selectors often.
- Some stores return captcha or bot-check pages.
- Generic requests without browser headers are blocked more often.
- Search/listing URLs are used instead of direct product URLs.

### Backend crashes

- Missing request validation.
- Raw exceptions returned directly.
- DB writes happen with invalid payloads.
- Long scraping requests block the same worker.

### APIs fail

- No consistent response shape.
- Invalid tracker payloads are inserted directly.
- Missing auth and ID checks.

### Invalid URLs are not handled

- Local URLs, bad schemes, and non-product pages are not rejected early.
- Unsupported stores are treated like supported ones.

### Email alerts fail

- SMTP config is incomplete.
- SMTP login is retried zero times.
- Short network failures are not handled.

### Cron jobs are unreliable

- Frontend auto-refresh is not a real scheduler.
- Background refresh must run from the server or an external cron service.

### Slow performance

- Price refresh runs too often.
- Repeated scraper logic is duplicated.
- Every dashboard session can trigger many fetches at once.

### Weak UX

- Errors are shown late.
- Refresh intervals are too aggressive.
- Unsupported URLs are not explained clearly.

## 2. Fixes applied in this codebase

### Backend

- Added safer API error responses instead of raw trace text.
- Added validated tracker payload handling.
- Added safer product URL validation.
- Added retried HTTP sessions for scraping.
- Added retried SMTP sending.
- Added `POST /api/internal/run-price-checks` for cron-driven tracker refresh.
- Added API-friendly 404 and 500 handlers.

### Frontend

- Reduced default auto-refresh from seconds to minutes.
- Improved scraper error messages shown in the UI.
- Preserved updated currency values during refresh.

## 3. Recommended Node.js folder structure

```text
pricealerter/
  client/
    src/
      api/
      components/
      pages/
      hooks/
      utils/
      styles/
  server/
    src/
      app.js
      server.js
      config/
      controllers/
      routes/
      services/
        scraper/
        mail/
        alerts/
      jobs/
      models/
      middleware/
      utils/
      validators/
      constants/
    tests/
  shared/
    types/
  docs/
```

## 4. Reliable Puppeteer scraper pattern

Use requests or axios first for fast stores, then fall back to Puppeteer for JS-heavy pages.

```js
import puppeteer from "puppeteer";

const PRICE_SELECTORS = [
  '[data-price]',
  '[itemprop="price"]',
  '.price',
  '.product-price',
  '.a-price .a-offscreen',
  '._30jeq3',
  '.pdp-price',
];

export async function scrapePrice(url) {
  const browser = await puppeteer.launch({
    headless: "new",
    args: ["--no-sandbox", "--disable-setuid-sandbox"],
  });

  try {
    const page = await browser.newPage();
    await page.setUserAgent(
      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    );
    await page.setExtraHTTPHeaders({
      "accept-language": "en-IN,en;q=0.9",
      "upgrade-insecure-requests": "1",
    });

    await page.goto(url, {
      waitUntil: "domcontentloaded",
      timeout: 45000,
    });

    await page.waitForTimeout(2000);

    const result = await page.evaluate((selectors) => {
      const parse = (value) => {
        if (!value) return null;
        const cleaned = String(value).replace(/[^\d.,]/g, "").replace(/,/g, "");
        const num = Number(cleaned);
        return Number.isFinite(num) ? num : null;
      };

      for (const selector of selectors) {
        const el = document.querySelector(selector);
        if (!el) continue;
        const raw =
          el.getAttribute("content") ||
          el.getAttribute("data-price") ||
          el.textContent;
        const price = parse(raw);
        if (price) {
          return {
            price,
            productName: document.title || "Product",
            selector,
          };
        }
      }

      return null;
    }, PRICE_SELECTORS);

    if (!result) {
      throw new Error("Price not found");
    }

    return result;
  } finally {
    await browser.close();
  }
}
```

## 5. Stable Express API structure

```js
import express from "express";
import { z } from "zod";

const app = express();
app.use(express.json());

const trackerSchema = z.object({
  url: z.string().url(),
  targetPrice: z.number().positive(),
});

app.post("/api/trackers", async (req, res, next) => {
  try {
    const body = trackerSchema.parse(req.body);
    const snapshot = await scrapePrice(body.url);

    const tracker = await Tracker.create({
      ...body,
      currentPrice: snapshot.price,
      productName: snapshot.productName,
    });

    res.status(201).json({ tracker });
  } catch (error) {
    next(error);
  }
});

app.use((error, req, res, next) => {
  if (error.name === "ZodError") {
    return res.status(400).json({ error: "Invalid request", details: error.issues });
  }
  res.status(500).json({ error: "Internal server error" });
});
```

## 6. Reliable cron design

Do not depend on a logged-in dashboard tab.

Use either:

- `node-cron` inside the backend if your server is always on.
- Render Cron Jobs calling a protected endpoint.

```js
import cron from "node-cron";

cron.schedule("*/15 * * * *", async () => {
  await refreshAllTrackers();
});
```

Safer for Render:

- Backend endpoint: `POST /api/internal/run-price-checks`
- Protect it with `CRON_SECRET`
- Configure Render Cron to call it every 15 minutes

## 7. Email sending best practices

Use retries and transport verification.

```js
import nodemailer from "nodemailer";

const transporter = nodemailer.createTransport({
  host: process.env.SMTP_HOST,
  port: Number(process.env.SMTP_PORT || 587),
  secure: false,
  auth: {
    user: process.env.SMTP_USER,
    pass: process.env.SMTP_PASS,
  },
});

export async function sendAlertEmail({ to, subject, html }) {
  await transporter.verify();

  for (let attempt = 1; attempt <= 2; attempt += 1) {
    try {
      await transporter.sendMail({
        from: process.env.SMTP_FROM,
        to,
        subject,
        html,
      });
      return true;
    } catch (error) {
      if (attempt === 2) throw error;
      await new Promise((resolve) => setTimeout(resolve, 1500));
    }
  }
}
```

## 8. Performance improvements

- Cache product metadata for a short time.
- Separate fast HTTP scraping from slow browser scraping.
- Use a queue for background refresh jobs.
- Limit concurrent scrapes.
- Store last checked time and skip very recent trackers.
- Add indexes in MongoDB on `userId`, `nextCheckAt`, and `targetReached`.

## 9. UI/UX improvements

- Validate URL before submit.
- Show supported-store warning before tracker creation.
- Show inline status like `Fetching price`, `Blocked by captcha`, or `Unsupported page`.
- Keep refresh interval in minutes, not seconds.
- Show last checked time on each tracker card.
- Use empty, loading, success, and error states clearly.

## 10. Deployment notes

### Vercel frontend

- Put only the React app on Vercel.
- Set `VITE_API_BASE_URL` to the Render backend URL.
- Do not run Puppeteer scraping in Vercel serverless functions for long jobs.

### Render backend

- Run the Express or Flask backend on Render Web Service.
- Set persistent env vars:
  - `SECRET_KEY`
  - `SMTP_*`
  - `CRON_SECRET`
  - `DATABASE_PATH` or Mongo connection string
- If using Puppeteer on Render, use a plan that supports the required Chromium dependencies.
- Add Render Cron Job to call the protected refresh endpoint.

## 11. Next migration recommendation

If you want to keep this current codebase:

- Continue improving the Flask service and move scraping to a dedicated worker.

If you want the React + Node + Mongo + Puppeteer stack you described:

- Keep the frontend on Vercel.
- Move scraping, alerts, and cron into a Render backend plus worker architecture.
- Use MongoDB for trackers, histories, and alert status.
