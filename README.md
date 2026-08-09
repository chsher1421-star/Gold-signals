# Gold VSA Alert System (XAUUSD)

Yeh system har 5 minute mein Oanda ka fresh XAUUSD candle data check karta hai aur
in signals ko detect karta hai:

- **CAB** — timeframes: M3, M5, M15, H1, H4
- **No Demand / No Supply** — timeframe: H4 only

Jab bhi koi naya signal bane, aapko chart image + details ke sath notification
milegi (ntfy push notification aur/ya email). Duplicate alert nahi ayega — har
candle ka signal sirf ek dafa notify hota hai.

Yeh sirf **alert engine** hai — charting/analysis ke liye aap apna MT5 ya
TradingView jaisa use kar rahe hain waisa hi karte rahein.

---

## Setup — sirf ek dafa karna hai

### Step 1: GitHub account aur naya repo

1. https://github.com pe free account banayein (agar nahi hai)
2. "New repository" pe click karein
3. Naam kuch bhi rakhein (e.g. `gold-signals`), **Public** select karein
4. In sab files (jo yahan hain) ko us repo mein upload kar dein (drag & drop
   se ya "Add file > Upload files" se), folder structure waisi hi rakhein

### Step 2: Oanda se free API token lena

1. https://www.oanda.com/demo-account/tpa/personal_token pe jayein
2. Free **demo/practice account** banayein (real paisa deposit karne ki
   zaroorat nahi — yeh sirf data ke liye hai)
3. Login karke ek **personal access token** generate karein — yeh ek lambi
   string hoti hai, copy kar lein (yehi `OANDA_TOKEN` hai)

### Step 3: Notification setup (ntfy — sabse simple, free, no signup)

1. Phone pe **ntfy** app install karein (Play Store / App Store pe free
   milegi)
2. App mein koi bhi unique topic name choose karein — jitna random utna
   behtar (e.g. `jerry-gold-signals-8842`), kyunke topic name hi security hai
3. App mein us topic ko "Subscribe" kar lein
4. Yehi topic name `NTFY_TOPIC` secret mein daalna hai (neeche Step 4)

*(Agar email pe bhi notification chahiye, "Optional: Email bhi" section
neeche dekh lein)*

### Step 4: GitHub Secrets add karna

Apne repo mein: **Settings > Secrets and variables > Actions > New repository
secret**

In secrets ko add karein:

| Secret name | Value |
|---|---|
| `OANDA_TOKEN` | Step 2 wala token |
| `NTFY_TOPIC` | Step 3 wala topic name |

Yeh secrets hamesha encrypted rehte hain — repo public hone ke bawajood koi
inhe dekh nahi sakta.

### Step 5: Test run karna

1. Repo mein **Actions** tab pe jayein
2. "Gold VSA Alerts" workflow select karein
3. "Run workflow" button pe click karein (manual trigger)
4. Kuch second mein run complete ho jayega — green tick ka matlab sab theek
   chala
5. Agar koi signal us waqt genuinely bana ho to notification aa jayegi,
   warna chup chaap khatam ho jayega (yehi normal behaviour hai)

Bas — ab yeh automatically har 5 minute pe khud chalta rahega, aapke phone/PC
se koi lena dena nahi.

---

## Optional: Email bhi chahiye

Agar ntfy ke sath/bajaye email bhi chahiye:

1. Gmail use kar rahe hain to ek **App Password** banayein (Google Account >
   Security > 2-Step Verification > App Passwords)
2. In secrets ko bhi add karein: `EMAIL_FROM`, `EMAIL_PASSWORD` (app
   password), `EMAIL_TO`
3. `.github/workflows/vsa-alerts.yml` mein `NOTIFY_METHOD: ntfy` ko
   `NOTIFY_METHOD: both` kar dein (ya sirf `email` agar ntfy nahi chahiye)

---

## Kaise verify karein sab sahi chal raha hai

- **Actions** tab mein har 5 min baad ek naya run dikhega — green tick
  matlab OK, red cross matlab error (click karke log dekh sakte hain)
- `state.json` file mein dhire dhire entries add hoti jayengi jab signals
  milte rahenge — yeh automatic commit hoti hai bot ki taraf se

## Kya cheez private rehti hai, kya public

- Code (VSA logic) — public repo mein sab dekh sakte hain
- `OANDA_TOKEN`, `NTFY_TOPIC`, email password — hamesha encrypted secrets,
  kabhi bhi kisi ko nahi dikhte

## Settings jo aap khud change kar sakte hain

`src/main.py` ke top pe yeh lists hain:

```python
CAB_TIMEFRAMES = ["M3", "M5", "M15", "H1", "H4"]
NO_DEMAND_SUPPLY_TIMEFRAMES = ["H4"]
```

Yahan se timeframes add/remove kar sakte hain future mein.

`src/vsa_signals.py` mein rules ke numbers (jaise 10-bar/15-bar CAB lookback,
spread threshold) — agar future mein tweak karne hon to yahan milenge.
