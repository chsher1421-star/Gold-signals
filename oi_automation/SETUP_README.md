# CME Open Interest — Auto Update Setup

Ye teen files tumhare `chsher1421-star/Gold-signals` repo mein add karni hain.
Gold-signals ka existing code (`src/`, `.github/workflows/vsa-alerts.yml`) ko
bilkul haath nahi lagana — sab kuch neeche diye gaye naye path mein rakhna hai.

## 1. Repo mein files ka structure

```
Gold-signals/                          <- existing repo (unchanged)
├── src/                               <- existing VSA code (untouched)
├── .github/workflows/
│   ├── vsa-alerts.yml                 <- existing (untouched)
│   └── oi-auto-update.yml             <- NEW (add this)
└── oi_automation/                     <- NEW folder
    ├── update_oi.py                   <- NEW
    ├── requirements.txt               <- NEW
    └── OI_Automatic_Update.xlsm       <- NEW: tumhari existing workbook (upload as-is, one time)
```

## 2. Steps

1. Apne local clone mein `oi_automation/` folder banao, usme
   `update_oi.py`, `requirements.txt` copy kar do.
2. Apni existing `.xlsm` file ko usi folder mein
   `OI_Automatic_Update.xlsm` naam se rakho aur commit kar do
   (ye "seed" file hai — usme jo data pehle se hai wahi se aage
   catch-up start hoga).
3. `oi-auto-update.yml` ko `.github/workflows/` folder mein daal do
   (yaani `vsa-alerts.yml` ke bilkul saath).
4. Commit + push:
   ```
   git add oi_automation .github/workflows/oi-auto-update.yml
   git commit -m "Add CME OI auto-update automation"
   git push
   ```
5. GitHub repo → **Actions** tab → "CME OI Auto Update" workflow → **Run workflow**
   (manual trigger) — pehli baar khud test kar lo before daily schedule pe chhod do.
   Actions log mein dekh sakte ho kya fetch hua, kya update hua.

Koi naya secret / token nahi chahiye — workflow apna default `GITHUB_TOKEN`
use karta hai file commit karne ke liye (isi repo mein, isliye already
allowed hai).

## 3. Local PC pe automatic sync (Windows Task Scheduler)

Ye taake jab bhi tumhara PC on ho, wo GitHub se latest file khud khींچ le
— chahe kitne bhi din baad PC on karo.

1. Ek folder mein repo ko clone karo (agar already nahi kiya):
   ```
   git clone https://github.com/chsher1421-star/Gold-signals.git
   ```
2. Ek chhoti `.bat` file banao, e.g. `C:\Scripts\sync_oi.bat`:
   ```bat
   @echo off
   cd /d "C:\path\to\your\Gold-signals"
   git pull
   ```
3. Task Scheduler khol kar naya task banao:
   - **Trigger:** "At log on" (aur agar chaho, ek aur trigger "daily, repeat
     every 1 hour, for a duration of 12 hours" — isse din mein PC on rehte
     hue bhi refresh milti rahegi)
   - **Action:** Start a program → `C:\Scripts\sync_oi.bat`
   - "Run whether user is logged on or not" (optional) select kar sakte ho

Bas — ab file hamesha khud-ba-khud latest rahegi, tumhe kabhi manually date
daalni ya button click karna nahi parega.

## 4. Notes / limitations (honestly)

- CME ka OI report din mein ek baar aata hai (Preliminary evening, Final
  next trading day morning) — "real-time" nahi, "daily" hai. Script isi
  logic ko follow karta hai jo purani VBA macro follow karti thi.
- Maine ye script yahan (is sandboxed environment) se CME ki website ko
  directly test nahi kar saka — sandbox ka network cmegroup.com ko allow
  nahi karta. GitHub Actions runners ko full internet access hota hai,
  isliye wahan chalega — lekin pehla run **manually trigger karke Actions
  log zaroor check karo** taake koi parsing issue ho to turant pata chal
  jaye.
- Weekends/holidays pe CME ka data nahi hota — script khud skip kar dega,
  error nahi dega.
- `vsa-alerts.yml` ka schedule, secrets, ya code — kuch bhi is setup se
  touch nahi hota.
