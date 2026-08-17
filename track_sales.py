import argparse
import csv
import datetime
import os
import sys

TRACKER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sales_tracker.csv")
FIELDS = ["date", "channel", "contact", "product", "price", "status", "buyer_email", "notes"]
STATUSES = ["lead", "contacted", "sample-sent", "paid", "bundle-upgrade"]
KILL_SALES = 10
KILL_WEEKS = 6


def _rows():
    if not os.path.exists(TRACKER):
        return []
    with open(TRACKER, "r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _append(row):
    os.makedirs(os.path.dirname(TRACKER), exist_ok=True)
    new = not os.path.exists(TRACKER)
    with open(TRACKER, "a+", newline="", encoding="utf-8") as f:
        f.seek(0, os.SEEK_END)
        end = f.tell()
        if end > 0:
            f.seek(end - 1, os.SEEK_SET)
            if f.read(1) != "\n":
                f.write("\n")
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            writer.writeheader()
        writer.writerow(row)


def cmd_add(args):
    status = args.status if args.status in STATUSES else sys.exit(f"status must be one of: {', '.join(STATUSES)}")
    row = {
        "date": args.date or datetime.date.today().isoformat(),
        "channel": args.channel or "",
        "contact": args.contact or "",
        "product": args.product or "",
        "price": args.price if args.price is not None else "",
        "status": status,
        "buyer_email": args.buyer_email or "",
        "notes": args.notes or "",
    }
    _append(row)
    print(f"added: {row['date']} {row['status']:12s} {row['product']}")


def cmd_list(args):
    rows = _rows()
    if not rows:
        print("no entries yet")
        return
    print(f"{'date':10s} {'status':13s} {'price':>6s}  {'channel':10s}  {'product'}")
    for r in rows:
        print(
            f"{r['date']:10s} {r['status']:13s} {r['price']:>6s}  "
            f"{r['channel']:10s}  {r['product']}"
        )


def cmd_stats(args):
    rows = _rows()
    paid = [r for r in rows if r["status"] == "paid"]
    revenue = sum(float(r["price"]) for r in paid if r["price"])
    leads = sum(1 for r in rows if r["status"] in ("lead", "contacted", "sample-sent"))
    by_status = {s: sum(1 for r in rows if r["status"] == s) for s in STATUSES}
    dates = sorted(r["date"] for r in rows if r["date"])
    start = dates[0] if dates else None
    deadline = None
    days_left = None
    if start:
        try:
            d0 = datetime.date.fromisoformat(start)
            deadline = d0 + datetime.timedelta(weeks=KILL_WEEKS)
            today = datetime.date.today()
            days_left = (deadline - today).days
        except ValueError:
            deadline, days_left = None, None
    print(f"total entries : {len(rows)}")
    for s in STATUSES:
        if by_status[s]:
            print(f"  {s:13s}: {by_status[s]}")
    print(f"revenue (paid): ${revenue:.2f}")
    print(f"kill criterion : {len(paid)}/{KILL_SALES} sales by {deadline or '?  '} "
          f"({days_left if days_left is not None else '?'} days left)")


def main():
    parser = argparse.ArgumentParser(prog="track_sales")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_add = sub.add_parser("add", help="add a tracker entry")
    p_add.add_argument("--date")
    p_add.add_argument("--channel")
    p_add.add_argument("--contact")
    p_add.add_argument("--product", required=True)
    p_add.add_argument("--price", type=float)
    p_add.add_argument("--status", default="lead")
    p_add.add_argument("--buyer-email")
    p_add.add_argument("--notes")
    p_add.set_defaults(fn=cmd_add)

    p_list = sub.add_parser("list", help="show all entries")
    p_list.set_defaults(fn=cmd_list)

    p_stats = sub.add_parser("stats", help="sales totals vs kill criterion")
    p_stats.set_defaults(fn=cmd_stats)

    args = parser.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()