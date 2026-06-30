# Ship — Definition of Done

<!-- The completeness gate for "is this actually shipped?" — the counter to the
     failure where the audit reports every tiny code detail but never notices the
     ONE fundamental thing that's missing (no product created in the store, no
     required API enabled). Audits are good at present-vs-spec; they are blind to
     ABSENT. This checklist makes the absent things explicit, line by line.

     Project-owned. The lines below target a paid mobile app (Apple + Android);
     trim to your product. The rule is not "tick every box" — it is that every
     line is either DONE or explicitly marked N/A. Silence on a line is the bug. -->

**Last updated:** <ISO-8601 date>

---

## The rule

Before anyone says a release is "done" / "shipped" / "live", walk this list. Each
line must read **DONE** or **N/A — <reason>**. A line that is neither is an open
blocker, even if every test passes and the code is perfect. *No alarm fires for a
thing that was never started* — this list is the alarm.

## Store presence (the big-miss catchers)

- [ ] **Google Play:** app record created in Play Console
- [ ] **Google Play:** store listing complete (title, description, screenshots, icon, privacy policy URL)
- [ ] **Google Play:** for any paid tier — **in-app product / subscription SKU created** (the silent-miss)
- [ ] **Apple App Store:** app record created in App Store Connect
- [ ] **Apple App Store:** store listing complete (description, screenshots per device class, privacy)
- [ ] **Apple App Store:** for any paid tier — **in-app purchase / subscription product created** (the silent-miss)

## Monetization wiring

- [ ] Billing provider (RevenueCat or equivalent): entitlements + offerings configured
- [ ] Products linked to BOTH store products above (not just defined in the dashboard)
- [ ] Provider API key present in the production build (not only local/dev)

## Backend / infra

- [ ] Every API the app calls is **ENABLED** in the cloud project (code referencing an API ≠ API turned on)
- [ ] Production secrets / env vars present in prod (not only `.env.local`)
- [ ] Database migrations applied to the production database

## Build & release

- [ ] Signed release build uploaded to each store
- [ ] Release track / phase set (internal → production) deliberately, not left in draft
- [ ] Version + build numbers bumped past the last published build

## Verification (do, don't assume)

- [ ] Installed from the store / TestFlight on a real device — app launches
- [ ] The paid flow purchased end-to-end at least once (sandbox or real) — entitlement actually unlocks

## Mechanism

- Run: at the "ready to ship / it's live" claim, paste this list into the comms file with each line marked DONE or N/A-<reason>
- Expect: zero lines left unmarked; every paid-tier store-product line explicitly addressed
- Fail if: a release is declared done with any line silent — especially a store-product line. That silence is the exact gap that ships an app with no purchasable product.
