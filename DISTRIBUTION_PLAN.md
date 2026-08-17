# Distribution plan & sales tracker

How to get the lead packs in front of buyers, and how to track progress.

## Who actually buys lead packs

Ranked by expected value per hour:

1. **Local SEO / marketing agencies** — they sell "we'll find you leads" services.
   One agency buying a bundle = repeat revenue. Pitch: "40-50 fresh local
   businesses per city/niche with phones, ready for your prospecting."
   Find them on LinkedIn (`site:linkedin.com local seo agency dentist`) and
   cold-message ~5/week with the free sample as proof.
2. **Freelancers / solo service providers** — web designers, virtual assistants,
   cold-email freelancers who need lists for their own clients. Facebook/LinkedIn.
3. **Small business owners doing their own outreach** — buy single packs.
   Found in local-business Facebook groups and Reddit.
4. **Cold-callers / appointment setters** — agencies again; buy in volume.

## Channels (value-first, never spam)

- **Free sample (Gumroad, $0 email opt-in)** — every promotion links here first.
  Captured emails are your nurture list: bundle offer later.
- **LinkedIn** — connect with local-SEO/marketing agency owners; share the free
  sample; offer a paid bundle. ~5 connects/week.
- **Reddit** — r/EntrepreneurRideAlong, r/smallbusiness, r/LeadGeneration,
  r/SEO. Comment with real value; only share the free sample where self-promo
  is allowed. Never drop links in communities that ban it.
- **Facebook groups** — "Houston Small Business", "Dentist Marketing", etc.
  Value-first posts; DMs to group owners offering the free sample.
- **Gumroad discovery** — title/tags matter: e.g. "Houston Dentist Leads —
  Business Contact List CSV". Free to list; low organic traffic but zero cost.

## Sales tracker (copy into Google Sheets)

Columns:

```
date | channel | contact | product | price | status | buyer_email | notes
```

`status`: lead → contacted → sample-sent → paid → bundle-upgrade

Sample rows:

```
2026-08-20 | LinkedIn  | Bright Local Agency | free sample (Houston dentists) | 0   | sample-sent | jane@brightlocal.xyz | also wants NY bundle
2026-08-21 | Reddit    | (DM from r/LeadGeneration) | US Restaurant bundle | 49 | paid        | x@gmail.com             | via product page
```

## Weekly cadence (every Friday, 30 min)

1. GitHub → Actions → Lead Packs → Run workflow (fresh packs).
2. Update the free-sample raw URL in Gumroad (see GUMROAD_LISTING.md).
3. Send 5 LinkedIn messages + 5 Reddit/FB value-first comments.
4. Update the tracker (statuses + new leads).
5. Check sales against the kill criterion.

## Kill criterion (honest)

If after **6 weeks** there are fewer than **10 sales total**, the lead-pack
business model is not worth continuing as-is — pivot (API access, custom
lists, or drop the idea) rather than keep pouring time in.

## First 2 weeks, concrete

- Week 1: create Gumroad store + free sample + single-pack product. Post the
  free sample link on r/EntrepreneurRideAlong (share-your-product thread) and
  in 2 Facebook business groups. Send 5 LinkedIn messages.
- Week 2: add the city + mega bundles. Email the free-sample subscribers a
  $29 bundle offer. Send 5 more LinkedIn messages.
- Update the tracker after each action.