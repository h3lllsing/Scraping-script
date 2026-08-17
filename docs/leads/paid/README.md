# Paid packs — DO NOT STORE PUBLIC PAID DATA

This directory intentionally holds **no paid lead packs**.

Paid packs are delivered through **Gumroad file uploads** (private, buyer-gated),
never through this public repository. Anyone with read access to a public repo
can download every file, so keeping paid data here would make the products free
to copy.

How paid packs are produced and delivered:

1. Generate locally against the live API (weekly, Friday):
   `python generate_leadpack.py --all --base https://<render-service>.onrender.com`
   Output goes to the gitignored `packs/` folder.
2. Zip the packs (one file per product: single pack, city bundle, niche
   mega-bundle, all-packs bundle).
3. Upload the ZIP to the corresponding Gumroad product (file delivery is
   instant and private to buyers).
4. Re-upload only when a pack's data changed meaningfully.

Only `../free-sample/sample-pack.csv` is public — it is the free funnel sample.